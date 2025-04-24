pacman::p_load(
    Seurat, tidyverse,
    SeuratDisk, scPred
)
#### PARAMS ###################
args <- commandArgs(trailingOnly = TRUE)
reference_seurat <- args[1]
reference_celltype <- args[2]
projects <- unlist(strsplit(args[3], split = ","))
samples <- unlist(strsplit(args[4], split = ","))
resources_path <- args[5]
data_path <- args[6]
################################

build_h5_path <- function(cnt) {
    return(
        paste0(
            resources_path, "/", projects[cnt], "/", samples[cnt],
            "/counted/outs/filtered_feature_bc_matrix.h5"
        )
    )
}
build_dist_path <- function(cnt) {
    return(
        paste0(
            data_path, "/", projects[cnt], "/", samples[cnt],
            "/celltype_predicted.tsv"
        )
    )
}
build_seurat_path <- function(cnt) {
    return(
        paste0(
            data_path, "/", projects[cnt], "/", samples[cnt],
            "/seurat.rds"
        )
    )
}
reference <-
    readRDS(reference_seurat)
reference@misc$scPred <- readRDS(reference_celltype)
cnt <- 1
for (sample in samples) {
    sample_path <- build_h5_path(cnt)
    dist_path <- build_dist_path(cnt)
    if (!file.exists(sample_path)) {
        message(
            paste0(
                "[ERROR!] Cound not resolved: ",
                sample_path,
                ". Skip"
            )
        )
    } else {
        message(
            paste0(
                "@ Predicting ", cnt, "/", length(projects), "\n",
                "└ ( ", sample_path, " )"
            )
        )
        query <-
            Read10X_h5(sample_path) %>%
            CreateSeuratObject() %>%
            NormalizeData()
        query[["data"]] <- query[["RNA"]]
        query <-
            query %>%
            scPredict(reference) %>%
            RunUMAP(reduction = "scpred", dims = 1:30)
        query@meta.data <-
            query@meta.data %>%
            tibble::rownames_to_column("barcode") %>%
            dplyr::mutate(
                cell = paste0(
                    samples[cnt], "_", row_number()
                ),
                project = projects[cnt],
                sample = samples[cnt]
            ) %>%
            tibble::column_to_rownames("cell")
        query@meta.data %>%
            tibble::rownames_to_column("cell") %>%
            dplyr::select(cell, scpred_prediction) %>%
            write_tsv(dist_path)
        query %>%
            saveRDS(build_seurat_path(cnt))
    }
    cnt <- cnt + 1
}
