pacman::p_load(Seurat, tidyverse, scran, batchelor, Matrix)
options(future.globals.maxSize = 1e9)
options(Seurat.object.assay.version = "v5")

#### PARAM Settings #####
args <- commandArgs(trailingOnly = TRUE)
# `<List<str>>` Sample IDs
sample_ids <- unlist(strsplit(args[1], split = ","))
# `<List<str>>` Project IDs
project_ids <- unlist(strsplit(args[2], split = ","))
# `<str>` Output file name (excluding .rds)
outfile_path <- args[3]
# `<str>` Log file path
logpath_runtime <- args[4]
proj_path <- args[5]
rm(args)
#########################

log_out <- function(content) {
    write(
        content,
        file = logpath_runtime, append = TRUE
    )
}
counts <- seq(from = 1, to = length(sample_ids))
seurats <-
    counts %>%
    as.list() %>%
    lapply(function(cnt) {
        message(paste0(
            proj_path, "/resources/", project_ids[cnt], "/", sample_ids[cnt], "/counted/outs/filtered_feature_bc_matrix.h5"
        ))
        seurat <-
            Read10X_h5(paste0(
                proj_path, "/resources/", project_ids[cnt], "/", sample_ids[cnt], "/counted/outs/filtered_feature_bc_matrix.h5"
            )) %>%
            CreateSeuratObject(project = "VascAging") %>%
            NormalizeData() %>%
            FindVariableFeatures() %>%
            ScaleData()
        seurat@meta.data <-
            seurat@meta.data %>%
            tibble::rownames_to_column("id") %>%
            mutate(
                sample = sample_ids[cnt],
                cell = paste0(sample_ids[cnt], "_", row_number())
            ) %>%
            left_join(
                read_tsv(
                    paste0("../../../data/", project_ids[cnt], "/", sample_ids[cnt], "/celltype_predicted.tsv"),
                    show_col_types = FALSE
                ),
                by = "cell"
            ) %>%
            tibble::column_to_rownames("id")
        return(seurat)
    })
gene_names_list <- lapply(seurats, function(seurat) {
    seurat %>%
        GetAssayData(assay = "RNA", slot = "data") %>%
        rownames() %>%
        return()
})
common_genes <- Reduce(intersect, gene_names_list)
# 各Seuratオブジェクトから共通遺伝子を抽出し、データを抽出
data_list <- lapply(seurats, function(seurat) {
    # 共通遺伝子でフィルタリング
    seurat_common <- seurat[common_genes, ]
    # 数値データを抽出
    GetAssayData(seurat_common, assay = "RNA", slot = "data")
})
# MNN補正の適用
mnn_out <- do.call(mnnCorrect, data_list)
sparse_counts <- as(assay(mnn_out), "sparseMatrix")

# 新しいSeuratオブジェクトを作成
integrated <-
    CreateSeuratObject(counts = sparse_counts, project = "Integrated") %>%
    NormalizeData() %>%
    ScaleData() %>%
    FindVariableFeatures() %>%
    RunPCA() %>%
    FindNeighbors(dims = 1:30) %>%
    FindClusters(dims = 1:30) %>%
    RunUMAP(dims = 1:30)
integrated@meta.data <-
    integrated@meta.data %>%
    cbind(seurats %>%
        lapply(function(seurat) {
            seurat@meta.data %>%
                tibble::rownames_to_column("id") %>%
                dplyr::select(id, scpred_prediction)
        }) %>%
        bind_rows())
integrated %>%
    saveRDS(outfile_path)
