pacman::p_load(
    Seurat, SeuratDisk, tidyverse
)
test <- "INTIALIZED"
args <- commandArgs(trailingOnly = TRUE)

h5seurat_path <- args[1]

seurat <- LoadH5Seurat(h5seurat_path)
