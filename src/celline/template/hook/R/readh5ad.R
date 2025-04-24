pacman::p_load(rhdf5, tidyverse, Matrix, Seurat)

readh5ad <- function(file_path) {
    convert_to_df <- function(h5data) {
        rows <- list()
        for (prop in names(h5data)) {
            # 各プロパティを取得
            property <- h5data[[prop]]

            # 値を取得
            if (is.list(property) && !is.null(property$categories) && !is.null(property$codes)) {
                values <- property$categories[property$codes + 1]
            } else if (is.atomic(property)) {
                values <- property
            } else {
                stop(paste("Unable to process property:", prop))
            }

            # 行データをリストとして追加
            rows[[prop]] <- values
        }
        return(as.data.frame(rows, check.names = FALSE))
    }
    convert_to_sparse <- function(data, indices, indptr) {
        # 行数と列数を推測
        n_rows <- length(indptr) - 1 # indptrの要素数 - 1 が行数
        n_cols <- max(indices) + 1 # indicesの最大値 + 1 が列数

        # 各行のインデックスを生成
        row_indices <- unlist(lapply(seq_along(indptr[-length(indptr)]), function(i) {
            rep(i - 1, indptr[i + 1] - indptr[i]) # indptr間の差分から各行のインデックスを生成
        }))

        # スパース行列を作成
        sparse_matrix <- sparseMatrix(
            i = as.integer(row_indices) + 1, # 行インデックス（1-based, integer型）
            j = as.integer(indices) + 1, # 列インデックス（1-based, integer型）
            x = as.numeric(data), # 非ゼロ要素の値（numeric型）
            dims = c(n_rows, n_cols) # 推測された行列サイズ
        )

        # 転置を行う
        transposed_matrix <- t(sparse_matrix) # 転置（メモリ効率的に処理）

        return(transposed_matrix)
    }

    metadata <-
        convert_to_df(rhdf5::h5read(file_path, "/obs", bit64conversion = "bit64")) %>%
        tibble::column_to_rownames("_index")
    rhdf5::h5closeAll()
    X <- rhdf5::h5read(file_path, "/X", bit64conversion = "bit64")
    rhdf5::h5closeAll()
    sparse_matrix <- convert_to_sparse(
        data = X$data,
        indices = X$indices,
        indptr = X$indptr
    )
    rm(X)
    features <- rhdf5::h5read(file_path, "/var")$gene
    rhdf5::h5closeAll()
    rownames(sparse_matrix) <- features
    colnames(sparse_matrix) <- metadata %>%
        tibble::rownames_to_column("cell") %>%
        dplyr::select(cell) %>%
        dplyr::pull()
    gc(reset = TRUE)

    Seurat::CreateSeuratObject(
        counts = sparse_matrix,
        assay = "RNA",
        meta.data = metadata,
        features = features
    ) %>%
        return()
}
