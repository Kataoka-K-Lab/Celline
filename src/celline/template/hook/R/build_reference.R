pacman::p_load(
    Seurat, scPred,
    tidyverse, SeuratDisk,
    doParallel
)
args <- commandArgs(trailingOnly = TRUE)
nthread <- args[1]
seurat_10x_file_path <- args[2]
celltype_path <- args[3]
dist_path <- args[4]

if (stringr::str_ends(seurat_10x_file_path, "\\.h5")) {
    reference <-
        Read10X_h5(seurat_10x_file_path) %>%
        CreateSeuratObject()
} else if (stringr::str_ends(seurat_10x_file_path, "\\.loom")) {
    reference <-
        Connect(
            filename = seurat_10x_file_path, mode = "r"
        ) %>%
        as.Seurat() %>%
        CreateSeuratObject()
} else if (stringr::str_ends(seurat_10x_file_path, "\\.h5seurat")) {
    reference <-
        LoadH5Seurat(seurat_10x_file_path)
} else if (stringr::str_ends(seurat_10x_file_path, "\\.h5seuratv5")) {
    reference <-
        readRDS(seurat_10x_file_path)
} else {
    stop("Unknown identifier")
}
reference <-
    reference %>%
    NormalizeData() %>%
    FindVariableFeatures() %>%
    ScaleData() %>%
    RunPCA() %>%
    RunUMAP(dims = 1:30)

celltype <-
    read_tsv(
        celltype_path,
        show_col_types = FALSE
    )

reference@meta.data <-
    reference@meta.data %>%
    tibble::rownames_to_column("cell") %>%
    left_join(
        celltype,
        by = "cell"
    ) %>%
    tibble::column_to_rownames("cell")

reference <- getFeatureSpace(reference, "Subclass")

cl <- makePSOCKcluster(nthread)
registerDoParallel(cl)
reference <- trainModel(reference, allowParallel = TRUE)
stopCluster(cl)

get_probabilities(reference) %>%
    tibble::rownames_to_column("cell") %>%
    write_tsv(
        paste0(
            dist_path,
            "/probability.tsv"
        )
    )
saveRDS(
    get_scpred(reference),
    paste0(
        dist_path,
        "/reference.pred"
    )
)
reference %>%
    SaveH5Seurat(
        paste0(
            dist_path,
            "/reference.h5seurat"
        ),
        overwrite = TRUE
    )
ggsave(
    paste0(
        dist_path,
        "/plot_probabilities.png"
    ),
    plot_probabilities(reference),
    width = 60,
    height = 60,
    units = "cm"
)
