# 必要なパッケージをロード
suppressMessages({
    library(Seurat)
    library(rhdf5)
    library(Matrix)
    library(tibble)
    library(dplyr)
    library(parallel)
    library(ggplot2)
    library(cluster) # For silhouette scores
    library(mclust)  # For adjusted Rand index
    library(lisi)    # For LISI computation
    library(kBET)    # For kBET acceptance rates
    library(cowplot) # For arranging plots
    library(tidyverse)
    library(bit64)   # 64ビット整数を扱うため（必要に応じて）
})

# ログメッセージを出力する関数
log_message <- function(message_text) {
    message(sprintf("[%s] %s", format(Sys.time(), "%Y-%m-%d %H:%M:%S"), message_text))
}

# CSR形式のデータをdgCMatrixに変換する関数
convert_csr_to_dgCMatrix <- function(data, indices, indptr, n_rows, n_cols) {
    # データをdouble型で受け取っているため、整数範囲を確認
    log_message("Validating 'indices' and 'indptr' for integer overflow")

    if (!all(indices >= 0 & indices < 2^31)) {
        stop("`indices` に32ビット整数の範囲を超える値が含まれています。")
    }
    if (!all(indptr >= 0 & indptr < 2^31)) {
        stop("`indptr` に32ビット整数の範囲を超える値が含まれています。")
    }

    # integerに変換
    indptr <- as.integer(indptr)
    indices <- as.integer(indices)
    data <- as.numeric(data)

    n_nonzero <- length(data)

    # rowとcolの次元を自動検出
    #   ・indptr が (n_rows + 1) なら「CSR (genes × cells) のまま」
    #   ・indptr が (n_cols + 1) なら「実際には (cells × genes) になっているので転置が必要」
    log_message("Checking if the matrix is transposed")
    if (length(indptr) == (n_rows + 1)) {
        transposed <- FALSE
    } else if (length(indptr) == (n_cols + 1)) {
        transposed <- TRUE
    } else {
        stop(sprintf("Length of indptr (%d) does not match n_rows + 1 (%d) nor n_cols + 1 (%d).",
                     length(indptr), n_rows + 1, n_cols + 1))
    }

    # indptr の検証
    if (any(diff(indptr) < 0)) {
        stop("indptr is not non-decreasing.")
    }
    if (tail(indptr, n = 1) != n_nonzero) {
        stop(sprintf("Last element of indptr (%d) does not match n_nonzero (%d).",
                     tail(indptr, n = 1), n_nonzero))
    }

    #----------------------------------------------------------------------
    # rows, cols を高速に生成
    #  - diff(indptr) は各「行」(または転置時は各 row-chunk) が持つ要素数
    #  - rep(seq_len(行数), times= diff(indptr)) で一気に rows (or cols) を作成
    #----------------------------------------------------------------------
    if (!transposed) {
        # そのまま (genes × cells) 形状のCSR
        # rows = 各行番号を繰り返し, cols = indices + 1
        rows <- rep(seq_len(n_rows), times = diff(indptr))
        cols <- indices + 1
        # 最終的な行列サイズは dims = c(n_rows, n_cols)
    } else {
        # 実は (cells × genes) のCSRとして格納されており、転置が必要
        # 物理的に t(...) する代わりに、行列生成時に row/col を逆に使う
        # rows = indices + 1, cols = 各行番号を繰り返し
        rows <- indices + 1
        cols <- rep(seq_len(n_cols), times = diff(indptr))
        # ただし最終的な形は (genes × cells) にしたいので dims=c(n_rows, n_cols)
    }

    cat(sprintf("Rows: min=%d, max=%d\n", min(rows), max(rows)))
    cat(sprintf("Cols: min=%d, max=%d\n", min(cols), max(cols)))

    if (any(rows <= 0)) {
        stop("Error: 'rows' に0以下の値が含まれています。")
    }
    if (any(cols <= 0)) {
        stop("Error: 'cols' に0以下の値が含まれています。")
    }
    if (length(rows) != length(data) || length(cols) != length(data)) {
        stop("Lengths of rows, cols, and data do not match.")
    }

    # dgCMatrix を作成
    sparse_matrix <- sparseMatrix(
        i = rows,
        j = cols,
        x = data,
        dims = c(n_rows, n_cols)
    )

    # ここでは物理的に転置する操作は不要。
    # if (transposed) { sparse_matrix <- t(sparse_matrix) } を削除

    return(sparse_matrix)
}

# スパースマトリックスをデンスマトリックスに変換する関数
sparse_to_dense <- function(sparse_matrix) {
    log_message("Converting sparse matrix to dense matrix")
    dense_matrix <- as.matrix(sparse_matrix)
    log_message("Conversion to dense matrix completed")
    return(dense_matrix)
}

# H5ADファイルを読み込んでSeuratオブジェクトを作成する関数
read_h5ad <- function(
    file_path,
    n_threads = 1,
    use_raw = FALSE,
    convert_sparse = FALSE,
    convert_sparse_raw = FALSE,
    feature_names_key = "_index",
    metadata_rownames_key = NULL
) {
    # 必要なライブラリをロード
    library(rhdf5)
    library(Matrix)
    library(Seurat)
    library(tibble)
    library(dplyr)
    library(parallel)

    log_message("Start: Reading H5AD file")

    # H5ADファイルの内容をリストする
    log_message("Listing H5AD file contents")
    h5_contents <- h5ls(file_path, recursive = TRUE)

    # H5メタデータをデータフレームに変換する関数
    convert_to_df <- function(h5data) {
        log_message("Converting metadata to a data frame")
        rows <- list()
        for (prop in names(h5data)) {
            log_message(sprintf("Processing property '%s'", prop))
            property <- h5data[[prop]]

            if (is.list(property) && !is.null(property$categories) && !is.null(property$codes)) {
                values <- property$categories[property$codes + 1]
            } else if (is.atomic(property)) {
                values <- property
            } else {
                stop(paste("Unable to process property:", prop))
            }

            rows[[prop]] <- values
        }
        df <- as.data.frame(rows, check.names = FALSE)
        log_message("Metadata conversion to data frame completed")
        return(df)
    }

    log_message("Reading metadata from '/obs'")
    if (any(h5_contents$group == "/obs")) {
        obs_data <- h5read(file_path, "/obs", bit64conversion = "double")

        # メタデータの各列がinteger型であれば範囲を確認し、integerに変換
        for (col in names(obs_data)) {
            if (is.numeric(obs_data[[col]])) {
                # 判定基準として、最大値が2^31-1以下かを確認
                if (all(obs_data[[col]] >= 0 & obs_data[[col]] < 2^31)) {
                    obs_data[[col]] <- as.integer(obs_data[[col]])
                } else {
                    log_message(sprintf("Column '%s' exceeds int32 range and remains as double.", col))
                }
            }
        }

        metadata <- convert_to_df(obs_data)
        rm(obs_data)
        h5closeAll()
        gc()
        log_message("Metadata from '/obs' read successfully")
    } else {
        stop("'/obs' group not found in the H5AD file.")
    }

    # メタデータの行名をユーザー指定のキーで設定
    if (!is.null(metadata_rownames_key)) {
        if (metadata_rownames_key %in% colnames(metadata)) {
            log_message(sprintf("Setting row names for metadata using key '%s'", metadata_rownames_key))
            rownames(metadata) <- metadata[[metadata_rownames_key]]
            metadata[[metadata_rownames_key]] <- NULL # 行名に使用した列は削除
        } else {
            available_keys <- colnames(metadata)
            stop(sprintf(
                "The specified metadata row names key '%s' does not exist.\nAvailable keys are: %s",
                metadata_rownames_key, paste(available_keys, collapse = ", ")
            ))
        }
    } else {
        # キーが指定されていない場合、既に行名が設定されているか確認
        if (is.null(rownames(metadata)) || all(rownames(metadata) == "")) {
            stop("Row names for metadata are not set. Please provide 'metadata_rownames_key'.")
        } else {
            log_message("Metadata row names are already set.")
        }
    }

    # '/var' から遺伝子メタデータを読み込んでデータフレームに変換
    log_message("Reading metadata from '/var'")
    if (any(h5_contents$group == "/var")) {
        var_data <- h5read(file_path, "/var", bit64conversion = "double")

        # メタデータの各列がinteger型であれば範囲を確認し、integerに変換
        for (col in names(var_data)) {
            if (is.numeric(var_data[[col]])) {
                # 判定基準として、最大値が2^31-1以下かを確認
                if (all(var_data[[col]] >= 0 & var_data[[col]] < 2^31)) {
                    var_data[[col]] <- as.integer(var_data[[col]])
                } else {
                    log_message(sprintf("Column '%s' exceeds int32 range and remains as double.", col))
                }
            }
        }

        var_metadata <- convert_to_df(var_data)
        rm(var_data)
        h5closeAll()
        gc()
        log_message("Metadata from '/var' read successfully")
    } else {
        stop("'/var' group not found in the H5AD file.")
    }

    # ユーザー指定のキーで遺伝子名を抽出
    log_message("Extracting feature (gene) names from '/var'")
    if (feature_names_key %in% colnames(var_metadata)) {
        feature_names <- var_metadata[[feature_names_key]]
        log_message(sprintf("Feature names extracted using key '%s'", feature_names_key))
    } else {
        available_keys <- colnames(var_metadata)
        stop(sprintf(
            "The specified feature names key '%s' does not exist.\nAvailable keys are: %s",
            feature_names_key, paste(available_keys, collapse = ", ")
        ))
    }

    # '/X' からカウントマトリックスを読み込む
    log_message("Checking if '/X' is a sparse matrix")
    is_X_sparse <- any(h5_contents$group == "/X" & h5_contents$name == "data")

    if (is_X_sparse) {
        log_message("'/X' is detected as a sparse matrix")
        if (convert_sparse) {
            log_message("Converting '/X' to sparse dgCMatrix as per 'convert_sparse=TRUE'")
            # スパースコンポーネントを読み込む（bit64conversion = "double" を設定）
            X_data <- h5read(file_path, "/X/data", bit64conversion = "double")
            X_indices <- h5read(file_path, "/X/indices", bit64conversion = "double")
            X_indptr <- h5read(file_path, "/X/indptr", bit64conversion = "double")

            # n_rows を遺伝子数、n_cols を細胞数として設定
            n_rows <- length(feature_names)  # 遺伝子数
            n_cols <- nrow(metadata)         # 細胞数

            # スパースマトリックスに変換
            sparse_matrix <- tryCatch(
                {
                    convert_csr_to_dgCMatrix(
                        data = X_data,
                        indices = X_indices,
                        indptr = X_indptr,
                        n_rows = n_rows,
                        n_cols = n_cols
                    )
                },
                error = function(e) {
                    log_message(sprintf("Error converting '/X' with genes as rows: %s", e$message))
                    log_message("Attempting to convert '/X' with cells as rows by swapping n_rows and n_cols.")
                    # スワップして再試行
                    tryCatch(
                        {
                            convert_csr_to_dgCMatrix(
                                data = X_data,
                                indices = X_indices,
                                indptr = X_indptr,
                                n_rows = n_cols,  # スワップ
                                n_cols = n_rows
                            )
                        },
                        error = function(e2) {
                            stop(sprintf("Failed to convert '/X' after swapping dimensions: %s", e2$message))
                        }
                    )
                }
            )
            rm(X_data, X_indices, X_indptr)
            gc()
            log_message("Converted the matrix to genes x cells")
        } else {
            log_message("Converting '/X' to dense matrix as per 'convert_sparse=FALSE'")
            X_data <- h5read(file_path, "/X/data", bit64conversion = "double")
            X_indices <- h5read(file_path, "/X/indices", bit64conversion = "double")
            X_indptr <- h5read(file_path, "/X/indptr", bit64conversion = "double")

            n_rows <- length(feature_names)
            n_cols <- nrow(metadata)

            sparse_matrix <- tryCatch(
                {
                    convert_csr_to_dgCMatrix(
                        data = X_data,
                        indices = X_indices,
                        indptr = X_indptr,
                        n_rows = n_rows,
                        n_cols = n_cols
                    )
                },
                error = function(e) {
                    log_message(sprintf("Error converting '/X' with genes as rows: %s", e$message))
                    log_message("Attempting to convert '/X' with cells as rows by swapping n_rows and n_cols.")
                    tryCatch(
                        {
                            convert_csr_to_dgCMatrix(
                                data = X_data,
                                indices = X_indices,
                                indptr = X_indptr,
                                n_rows = n_cols,
                                n_cols = n_rows
                            )
                        },
                        error = function(e2) {
                            stop(sprintf("Failed to convert '/X' after swapping dimensions: %s", e2$message))
                        }
                    )
                }
            )
            rm(X_data, X_indices, X_indptr)
            gc()
            log_message("Converted the matrix to genes x cells")
            # デンスマトリックスに変換
            sparse_matrix <- sparse_to_dense(sparse_matrix)
        }
    } else {
        log_message("'/X' is detected as a dense matrix")
        log_message("Reading '/X' as dense matrix")
        X_dense <- h5read(file_path, "/X", bit64conversion = "double")
        n_rows <- length(feature_names)
        n_cols <- nrow(metadata)
        sparse_matrix <- X_dense
        rm(X_dense)
        gc()
    }

    log_message("'/X' data read successfully")

    # カウントマトリックスに行名と列名を設定
    log_message("Setting row and column names for the matrix")
    if (nrow(sparse_matrix) != length(feature_names)) {
        stop(sprintf("Mismatch in number of features: %d (feature_names) vs %d (sparse_matrix rows)",
                     length(feature_names), nrow(sparse_matrix)))
    }
    if (ncol(sparse_matrix) != nrow(metadata)) {
        stop(sprintf("Mismatch in number of cells: %d (metadata) vs %d (sparse_matrix columns)",
                     nrow(metadata), ncol(sparse_matrix)))
    }
    rownames(sparse_matrix) <- feature_names
    colnames(sparse_matrix) <- rownames(metadata)
    gc(reset = TRUE)
    log_message("Row and column names set successfully")

    # raw データを処理
    if (use_raw) {
        log_message("Handling raw data as per 'use_raw=TRUE'")
        # '/raw/X' が存在するか確認
        has_raw <- any(h5_contents$group == "/raw/X" & h5_contents$name == "data") ||
            any(h5_contents$name == "X" & h5_contents$group == "/raw")
        if (!has_raw) {
            log_message("No '/raw/X' found in the H5AD file")
        } else {
            log_message("Reading raw data from '/raw/X'")
            is_raw_sparse <- any(h5_contents$group == "/raw/X" & h5_contents$name == "data")

            if (is_raw_sparse) {
                log_message("'/raw/X' is detected as a sparse matrix")
                if (convert_sparse_raw) {
                    log_message("Converting '/raw/X' to sparse dgCMatrix as per 'convert_sparse_raw=TRUE'")
                    raw_X_data <- h5read(file_path, "/raw/X/data", bit64conversion = "double")
                    raw_X_indices <- h5read(file_path, "/raw/X/indices", bit64conversion = "double")
                    raw_X_indptr <- h5read(file_path, "/raw/X/indptr", bit64conversion = "double")

                    n_rows_raw <- length(feature_names)
                    n_cols_raw <- nrow(metadata)

                    raw_sparse_matrix <- tryCatch(
                        {
                            convert_csr_to_dgCMatrix(
                                data = raw_X_data,
                                indices = raw_X_indices,
                                indptr = raw_X_indptr,
                                n_rows = n_rows_raw,
                                n_cols = n_cols_raw
                            )
                        },
                        error = function(e) {
                            log_message(sprintf("Error converting '/raw/X' with genes as rows: %s", e$message))
                            log_message("Attempting to convert '/raw/X' with cells as rows by swapping n_rows and n_cols.")
                            tryCatch(
                                {
                                    convert_csr_to_dgCMatrix(
                                        data = raw_X_data,
                                        indices = raw_X_indices,
                                        indptr = raw_X_indptr,
                                        n_rows = n_cols_raw,
                                        n_cols = n_rows_raw
                                    )
                                },
                                error = function(e2) {
                                    stop(sprintf("Failed to convert '/raw/X' after swapping dimensions: %s", e2$message))
                                }
                            )
                        }
                    )
                    rm(raw_X_data, raw_X_indices, raw_X_indptr)
                    gc()
                    log_message("Converted the raw matrix to genes x cells")
                } else {
                    log_message("Converting '/raw/X' to dense matrix as per 'convert_sparse_raw=FALSE'")
                    raw_X_data <- h5read(file_path, "/raw/X/data", bit64conversion = "double")
                    raw_X_indices <- h5read(file_path, "/raw/X/indices", bit64conversion = "double")
                    raw_X_indptr <- h5read(file_path, "/raw/X/indptr", bit64conversion = "double")

                    n_rows_raw <- length(feature_names)
                    n_cols_raw <- nrow(metadata)

                    raw_sparse_matrix <- tryCatch(
                        {
                            convert_csr_to_dgCMatrix(
                                data = raw_X_data,
                                indices = raw_X_indices,
                                indptr = raw_X_indptr,
                                n_rows = n_rows_raw,
                                n_cols = n_cols_raw
                            )
                        },
                        error = function(e) {
                            log_message(sprintf("Error converting '/raw/X' with genes as rows: %s", e$message))
                            log_message("Attempting to convert '/raw/X' with cells as rows by swapping n_rows and n_cols.")
                            tryCatch(
                                {
                                    convert_csr_to_dgCMatrix(
                                        data = raw_X_data,
                                        indices = raw_X_indices,
                                        indptr = raw_X_indptr,
                                        n_rows = n_cols_raw,
                                        n_cols = n_rows_raw
                                    )
                                },
                                error = function(e2) {
                                    stop(sprintf("Failed to convert '/raw/X' after swapping dimensions: %s", e2$message))
                                }
                            )
                        }
                    )
                    rm(raw_X_data, raw_X_indices, raw_X_indptr)
                    gc()
                    log_message("Converted the raw matrix to genes x cells")
                    raw_sparse_matrix <- sparse_to_dense(raw_sparse_matrix)
                }
                raw_matrix <- raw_sparse_matrix
            } else {
                log_message("'/raw/X' is detected as a dense matrix")
                log_message("Reading '/raw/X' as dense matrix")
                raw_X_dense <- h5read(file_path, "/raw/X", bit64conversion = "double")
                n_rows_raw <- length(feature_names)
                n_cols_raw <- nrow(metadata)
                raw_matrix <- raw_X_dense
                rm(raw_X_dense)
                gc()
            }

            log_message("'/raw/X' data read successfully")

            # raw 特徴（遺伝子）メタデータを読み込む
            log_message("Reading metadata from '/raw/var'")
            if (any(h5_contents$group == "/raw/var")) {
                raw_var_data <- h5read(file_path, "/raw/var", bit64conversion = "double")

                for (col in names(raw_var_data)) {
                    if (is.numeric(raw_var_data[[col]])) {
                        if (all(raw_var_data[[col]] >= 0 & raw_var_data[[col]] < 2^31)) {
                            raw_var_data[[col]] <- as.integer(raw_var_data[[col]])
                        } else {
                            log_message(sprintf("Column '%s' in raw_var_data exceeds int32 range and remains as double.", col))
                        }
                    }
                }

                raw_var_metadata <- convert_to_df(raw_var_data)
                rm(raw_var_data)
                h5closeAll()
                gc()
                log_message("Metadata from '/raw/var' read successfully")
            } else {
                log_message("'/raw/var' group not found in the H5AD file. Using existing feature names.")
                raw_var_metadata <- var_metadata
            }

            # raw 特徴（遺伝子）名を抽出
            log_message("Extracting feature (gene) names from '/raw/var'")
            if (feature_names_key %in% colnames(raw_var_metadata)) {
                raw_feature_names <- raw_var_metadata[[feature_names_key]]
                log_message(sprintf("Raw feature names extracted using key '%s'", feature_names_key))
            } else {
                available_raw_keys <- colnames(raw_var_metadata)
                stop(sprintf(
                    "The specified raw feature names key '%s' does not exist.\nAvailable keys are: %s",
                    feature_names_key, paste(available_raw_keys, collapse = ", ")
                ))
            }

            # raw_matrix に行名と列名を設定
            log_message("Setting row and column names for the raw matrix")
            if (nrow(raw_matrix) != length(raw_feature_names)) {
                stop(sprintf("Mismatch in number of raw features: %d (raw_feature_names) vs %d (raw_matrix rows)",
                             length(raw_feature_names), nrow(raw_matrix)))
            }
            if (ncol(raw_matrix) != nrow(metadata)) {
                stop(sprintf("Mismatch in number of cells for raw data: %d (metadata) vs %d (raw_matrix columns)",
                             nrow(metadata), ncol(raw_matrix)))
            }
            rownames(raw_matrix) <- raw_feature_names
            colnames(raw_matrix) <- rownames(metadata)
            gc(reset = TRUE)
            log_message("Row and column names for raw matrix set successfully")
        }
    }

    # Seurat オブジェクトを作成
    log_message("Creating Seurat object")
    seurat_obj <- CreateSeuratObject(
        counts = sparse_matrix,
        assay = "RNA",
        meta.data = metadata
    )
    log_message("Seurat object created successfully")
    
    # Copy counts to data layer (needed for scVI processed data)
    log_message("Copying counts to data layer for scVI compatibility")
    seurat_obj[["RNA"]]$data <- seurat_obj[["RNA"]]$counts
    log_message("Data layer populated successfully")
    
    # Copy data to scale.data layer to avoid "empty scale.data" errors
    # For processed scVI data, this is already normalized/scaled
    log_message("Creating scale.data layer for downstream compatibility")
    n_genes_to_scale <- min(3000, nrow(seurat_obj))  # Use more genes for better coverage
    genes_to_scale <- head(rownames(seurat_obj), n_genes_to_scale)
    seurat_obj[["RNA"]]$scale.data <- as.matrix(seurat_obj[["RNA"]]$data[genes_to_scale, ])
    log_message(paste("Scale.data layer created with", n_genes_to_scale, "genes"))

    # raw データを Seurat オブジェクトに追加
    if (use_raw && exists("raw_matrix")) {
        log_message("Adding raw data to Seurat object")
        raw_assay <- CreateAssayObject(counts = raw_matrix)
        seurat_obj[["RNA_raw"]] <- raw_assay
        log_message("Raw data added as 'RNA_raw' assay in Seurat object")
    }

    # '/obsm' から埋め込み（embeddings）を読み込んで Seurat オブジェクトに追加
    log_message("Reading embeddings from '/obsm'")
    if (any(h5_contents$group == "/obsm")) {
        obsm_datasets <- h5_contents %>%
            filter(group == "/obsm", otype == "H5I_DATASET")
        for (i in 1:nrow(obsm_datasets)) {
            dataset_name <- obsm_datasets$name[i]
            dataset_path <- paste0("/obsm/", dataset_name)
            log_message(sprintf("Reading embedding '%s' from '%s'", dataset_name, dataset_path))
            embedding_data <- h5read(file_path, dataset_path, bit64conversion = "double")

            embedding_dims <- dim(embedding_data)
            log_message(sprintf("Embedding '%s' dimensions: %s", dataset_name, paste(embedding_dims, collapse = " x ")))

            # セル数と埋め込み次元数を確認
            n_cells <- ncol(seurat_obj)
            if (length(embedding_dims) == 2) {
                if (embedding_dims[1] == n_cells) {
                    embeddings <- embedding_data
                } else if (embedding_dims[2] == n_cells) {
                    embeddings <- t(embedding_data)
                } else {
                    stop(sprintf("Embedding '%s' dimensions do not match the number of cells.", dataset_name))
                }
            } else {
                stop(sprintf("Embedding '%s' is not a 2D matrix.", dataset_name))
            }

            embedding_name_seurat <- sub("^X_|^X", "", dataset_name)
            log_message(sprintf("Adding embedding '%s' to Seurat object as '%s'", dataset_name, embedding_name_seurat))

            rownames(embeddings) <- colnames(seurat_obj)
            colnames(embeddings) <- paste0(embedding_name_seurat, "_", 1:ncol(embeddings))

            dim_reduc <- tryCatch(
                {
                    Seurat::CreateDimReducObject(
                        embeddings = embeddings,
                        key = paste0(embedding_name_seurat, "_"),
                        assay = "RNA"
                    )
                },
                error = function(e) {
                    log_message(sprintf("Error in CreateDimReducObject for embedding '%s': %s", dataset_name, e$message))
                    return(NULL)
                },
                warning = function(w) {
                    log_message(sprintf("Warning in CreateDimReducObject for embedding '%s': %s", dataset_name, w$message))
                    return(NULL)
                }
            )

            if (!is.null(dim_reduc)) {
                log_message(sprintf("DimReduc object for embedding '%s' created successfully", dataset_name))
                seurat_obj[[embedding_name_seurat]] <- dim_reduc
            } else {
                log_message(sprintf("Failed to create DimReduc object for embedding '%s'", dataset_name))
            }
        }
        h5closeAll()
        gc()
        log_message("Embeddings from '/obsm' added successfully")
    }

    # '/obsp' からグラフ（neighbor graphs）を読み込んで Seurat オブジェクトに追加
    log_message("Reading graphs from '/obsp'")
    if (any(h5_contents$group == "/obsp")) {
        obsp_groups <- h5_contents %>%
            filter(group == "/obsp", otype == "H5I_GROUP")
        for (i in 1:nrow(obsp_groups)) {
            graph_name <- obsp_groups$name[i]
            graph_path <- paste0("/obsp/", graph_name)
            log_message(sprintf("Processing graph '%s' at '%s'", graph_name, graph_path))

            # グラフが 'data', 'indices', 'indptr' を含んでいるか確認
            graph_contents <- h5_contents %>%
                filter(group == graph_path)
            if (all(c("data", "indices", "indptr") %in% graph_contents$name)) {
                graph_data <- h5read(file_path, paste0(graph_path, "/data"), bit64conversion = "double")
                graph_indices <- h5read(file_path, paste0(graph_path, "/indices"), bit64conversion = "double")
                graph_indptr <- h5read(file_path, paste0(graph_path, "/indptr"), bit64conversion = "double")

                # 次元を推定
                n_rows_graph <- length(graph_indptr) - 1
                n_cols_graph <- ncol(seurat_obj)

                log_message(sprintf("Inferred graph dimensions: Rows = %d, Columns = %d", n_rows_graph, n_cols_graph))

                graph_sparse_matrix <- tryCatch(
                    {
                        convert_csr_to_dgCMatrix(
                            data = graph_data,
                            indices = graph_indices,
                            indptr = graph_indptr,
                            n_rows = n_rows_graph,
                            n_cols = n_cols_graph
                        )
                    },
                    error = function(e) {
                        log_message(sprintf("Error converting graph '%s' to dgCMatrix: %s", graph_name, e$message))
                        return(NULL)
                    }
                )

                if (!is.null(graph_sparse_matrix)) {
                    rownames(graph_sparse_matrix) <- colnames(seurat_obj)
                    colnames(graph_sparse_matrix) <- colnames(seurat_obj)

                    # グラフ名を Seurat の慣例にあわせて適当に調整
                    graph_name_seurat <- paste0("snn_", graph_name)
                    seurat_obj@graphs[[graph_name_seurat]] <- graph_sparse_matrix
                    log_message(sprintf("Graph '%s' added to Seurat object as '%s'", graph_name, graph_name_seurat))
                } else {
                    log_message(sprintf("Failed to convert graph '%s' to dgCMatrix", graph_name))
                }
            } else {
                log_message(sprintf("Graph '%s' does not contain 'data', 'indices', 'indptr'", graph_name))
            }
        }
        h5closeAll()
        gc()
        log_message("Graphs from '/obsp' added successfully")
    }

    # '/uns' から追加のreduction情報を読み込んでSeurat オブジェクトに追加
    log_message("=== DEBUG: Starting /uns processing ===")
    log_message(sprintf("Available groups in h5_contents: %s", paste(unique(h5_contents$group), collapse = ", ")))
    log_message(sprintf("Current Seurat reductions: %s", paste(names(seurat_obj@reductions), collapse = ", ")))
    
    if (any(h5_contents$group == "/uns")) {
        log_message("Found /uns group in h5_contents")
        
        # DEBUG: Show all /uns contents
        uns_contents <- h5_contents %>% filter(grepl("^/uns", group))
        log_message(sprintf("All /uns contents: %s", paste(apply(uns_contents, 1, function(x) paste(x["group"], x["name"], x["otype"], sep="/")), collapse = ", ")))
        
        # Get all groups under /uns
        uns_groups <- h5_contents %>%
            filter(grepl("^/uns/", group), otype == "H5I_GROUP") %>%
            mutate(reduction_name = sub("^/uns/", "", group)) %>%
            distinct(reduction_name)
        
        log_message(sprintf("Found /uns groups: %s", paste(uns_groups$reduction_name, collapse = ", ")))
        
        # Process existing reductions for variance/variance_ratio
        for (reduction_name in uns_groups$reduction_name) {
            # Check if this reduction exists in Seurat object
            if (reduction_name %in% names(seurat_obj@reductions)) {
                log_message(sprintf("Processing existing reduction '%s' from '/uns/%s'", reduction_name, reduction_name))
                
                # Handle variance information
                variance_path <- sprintf("/uns/%s/variance", reduction_name)
                if (any(h5_contents$group == sprintf("/uns/%s", reduction_name) & h5_contents$name == "variance")) {
                    variance_data <- h5read(file_path, variance_path, bit64conversion = "double")
                    # Seurat expects standard deviation, so take square root of variance
                    seurat_obj[[reduction_name]]@stdev <- sqrt(as.numeric(variance_data))
                    log_message(sprintf("%s variance added to Seurat object", reduction_name))
                }
                
                # Handle variance ratio information
                variance_ratio_path <- sprintf("/uns/%s/variance_ratio", reduction_name)
                if (any(h5_contents$group == sprintf("/uns/%s", reduction_name) & h5_contents$name == "variance_ratio")) {
                    variance_ratio_data <- h5read(file_path, variance_ratio_path, bit64conversion = "double")
                    seurat_obj[[reduction_name]]@misc$variance_ratio <- as.numeric(variance_ratio_data)
                    log_message(sprintf("%s variance ratio added to Seurat object", reduction_name))
                }
            } else {
                log_message(sprintf("Reduction '%s' found in /uns but not in Seurat reductions - will not process variance info", reduction_name))
            }
        }
        
        # Special handling for 'latent' reduction - check multiple possible paths
        latent_paths_to_check <- c("latent", "X_latent", "latent_embedding")
        latent_found <- FALSE
        
        for (latent_name in latent_paths_to_check) {
            latent_direct_check <- any(h5_contents$group == "/uns" & h5_contents$name == latent_name)
            log_message(sprintf("DEBUG: Checking for direct /uns/%s: %s", latent_name, latent_direct_check))
            
            if (latent_direct_check) {
                latent_path <- paste0("/uns/", latent_name)
                log_message(sprintf("Found '%s' embedding at %s, adding as reduction", latent_name, latent_path))
                latent_data <- h5read(file_path, latent_path, bit64conversion = "double")
                
                # DEBUG: Show latent data info
                latent_dims <- dim(latent_data)
                n_cells <- ncol(seurat_obj)
                log_message(sprintf("DEBUG: Latent data dimensions: %s, Seurat n_cells: %d", paste(latent_dims, collapse = " x "), n_cells))
                
                if (length(latent_dims) == 2) {
                    if (latent_dims[1] == n_cells) {
                        latent_embeddings <- latent_data
                        log_message("DEBUG: Using latent data as-is (cells x features)")
                    } else if (latent_dims[2] == n_cells) {
                        latent_embeddings <- t(latent_data)
                        log_message("DEBUG: Transposing latent data (features x cells -> cells x features)")
                    } else {
                        log_message(sprintf("WARNING: Latent embedding dimensions (%s) do not match cell count (%d), trying next path", paste(latent_dims, collapse = " x "), n_cells))
                        next
                    }
                    
                    rownames(latent_embeddings) <- colnames(seurat_obj)
                    colnames(latent_embeddings) <- paste0("latent_", seq_len(ncol(latent_embeddings)))
                    
                    log_message(sprintf("DEBUG: Creating latent reduction with dimensions: %s", paste(dim(latent_embeddings), collapse = " x ")))
                    
                    latent_reduction <- Seurat::CreateDimReducObject(
                        embeddings = latent_embeddings,
                        key = "latent_",
                        assay = "RNA"
                    )
                    
                    seurat_obj[["latent"]] <- latent_reduction
                    log_message(sprintf("SUCCESS: Latent embedding from %s added to Seurat object as 'latent' reduction", latent_path))
                    latent_found <- TRUE
                    break
                } else {
                    log_message(sprintf("ERROR: Latent data at %s is not 2D matrix, has %d dimensions", latent_path, length(latent_dims)))
                }
            }
        }
        
        # If direct paths didn't work, check for group structure
        if (!latent_found) {
            log_message("DEBUG: Direct latent paths not found, checking for group structures")
            
            # Check if latent exists as a group with embeddings inside
            latent_group_check <- any(grepl("^/uns/latent", h5_contents$group))
            log_message(sprintf("DEBUG: Checking for /uns/latent/ group: %s", latent_group_check))
            
            if (latent_group_check) {
                # Look for common embedding names within latent group
                latent_embedding_paths <- c("/uns/latent/X", "/uns/latent/embeddings", "/uns/latent/X_latent")
                
                for (embedding_path in latent_embedding_paths) {
                    if (any(h5_contents$group == dirname(embedding_path) & h5_contents$name == basename(embedding_path))) {
                        log_message(sprintf("Found latent embedding at: %s", embedding_path))
                        
                        latent_data <- h5read(file_path, embedding_path, bit64conversion = "double")
                        latent_dims <- dim(latent_data)
                        n_cells <- ncol(seurat_obj)
                        log_message(sprintf("DEBUG: Latent data dimensions: %s, Seurat n_cells: %d", paste(latent_dims, collapse = " x "), n_cells))
                        
                        if (length(latent_dims) == 2) {
                            if (latent_dims[1] == n_cells) {
                                latent_embeddings <- latent_data
                            } else if (latent_dims[2] == n_cells) {
                                latent_embeddings <- t(latent_data)
                            } else {
                                log_message(sprintf("WARNING: Latent embedding dimensions do not match cell count, skipping %s", embedding_path))
                                next
                            }
                            
                            rownames(latent_embeddings) <- colnames(seurat_obj)
                            colnames(latent_embeddings) <- paste0("latent_", seq_len(ncol(latent_embeddings)))
                            
                            latent_reduction <- Seurat::CreateDimReducObject(
                                embeddings = latent_embeddings,
                                key = "latent_",
                                assay = "RNA"
                            )
                            
                            seurat_obj[["latent"]] <- latent_reduction
                            log_message(sprintf("SUCCESS: Latent embedding from %s added to Seurat object", embedding_path))
                            latent_found <- TRUE
                            break
                        }
                    }
                }
            }
            
            if (!latent_found) {
                log_message("WARNING: No latent embeddings found in any expected location")
            }
        }
        
        # Final check: Report current reductions after processing
        log_message(sprintf("Final Seurat reductions after /uns processing: %s", paste(names(seurat_obj@reductions), collapse = ", ")))
    } else {
        log_message("No /uns group found in h5_contents")
    }
    
    log_message("=== DEBUG: Finished /uns processing ===")

    log_message("End: H5AD file read successfully")
    return(seurat_obj)
}
