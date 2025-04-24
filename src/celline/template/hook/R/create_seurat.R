pacman::p_load(
    Seurat,
    tidyverse
)
args <- commandArgs(trailingOnly = TRUE)
input_h5_path <- args[1]
data_dir_path <- args[2]
proj_name <- args[3]
useqc_matrix <- args[4] # "true" or "false" as string

seurat <-
    Read10X_h5(input_h5_path) %>%
    CreateSeuratObject(
        project = proj_name
    )
seurat@meta.data <-
    seurat@meta.data %>%
    tibble::rownames_to_column("cell") %>%
    left_join(
        read_tsv(
            paste0(
                data_dir_path, "/doublet_filtered.tsv"
            ),
            show_col_types = FALSE
        ) %>%
            dplyr::select(cell, is_doublet_95),
        by = "cell"
    ) %>%
    left_join(
        read_tsv(
            paste0(
                data_dir_path, "/qc_matrix.tsv"
            ),
            show_col_types = FALSE
        ),
        by = "cell"
    ) %>%
    left_join(
        read_tsv(
            paste0(
                data_dir_path, "/celltype_predicted.tsv"
            ),
            show_col_types = FALSE
        ),
        by = "cell"
    ) %>%
    dplyr::rename(
        celltype_predicted = scpred_prediction
    ) %>%
    tibble::column_to_rownames("cell")
seurat <-
    seurat %>%
    subset(
        is_doublet_95 == FALSE
    )
if (useqc_matrix == "true") {
    seurat <-
        seurat %>%
        subset(keep_mitochondrial)
}
seurat <-
    seurat %>%
    NormalizeData(verbose = FALSE) %>%
    FindVariableFeatures(verbose = FALSE) %>%
    ScaleData(verbose = FALSE)
seurat <-
    seurat %>%
    RunPCA(features = VariableFeatures(object = seurat), verbose = FALSE) %>%
    FindNeighbors(dims = 1:20, verbose = FALSE) %>%
    FindClusters(verbose = FALSE) %>%
    RunUMAP(dims = 1:20, verbose = FALSE)
seurat %>%
    saveRDS(
        paste0(
            data_dir_path, "/seurat.rds"
        )
    )
ggsave(
    paste0(
        data_dir_path, "/celltype_predicted.png"
    ),
    seurat %>%
        DimPlot(
            group.by = "celltype_predicted"
        ),
    width = 22,
    height = 20,
    units = "cm"
)
