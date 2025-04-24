pacman::p_load(
    Seurat, tidyverse, SeuratDisk,
    SingleCellPipeline
)

args <- commandArgs(trailingOnly = TRUE)
project_name <- args[1]
total_sample_name <- args[2]
directory <- args[3]
# Get projects in target directory
seurats <-
    list.dirs(directory, recursive = FALSE) %>%
    as.list() %>%
    lapply(
        function(target_sample) {
            paste0(
                target_sample,
                "/outs/filtered_feature_bc_matrix.h5"
            ) %>%
                Read10X_h5() %>%
                CreateSeuratObject(
                    project = project_name
                ) %>%
                NormalizeData() %>%
                FindVariableFeatures(
                    selection.method = "vst"
                )
        }
    )
seurats <-
    seurats %>%
    FindIntegrationAnchors(
        anchor.features = SelectIntegrationFeatures(seurats)
    ) %>%
    IntegrateData() %>%
    set_default_assay("integrated") %>%
    ScaleData(verbose = FALSE) %>%
    RunPCA(npcs = 30, verbose = FALSE) %>%
    RunUMAP(reduction = "pca", dims = 1:30) %>%
    FindNeighbors(reduction = "pca", dims = 1:30) %>%
    FindClusters(resolution = 1)

seurats@meta.data <-
    seurats@meta.data %>%
    mutate(
        sample = total_sample_name
    )
ggsave(
    paste0(
        directory,
        "/2_seurat/__integrated/clusters.png"
    ),
    DimPlot(
        seurats,
        reduction = "umap", label = TRUE, repel = TRUE
    ) + NoLegend(),
    width = 20,
    height = 20,
    units = "cm"
)

SaveH5Seurat(
    paste0(
        directory,
        "/2_seurat/seurat"
    )
)
