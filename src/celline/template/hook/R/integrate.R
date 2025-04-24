pacman::p_load(
    Seurat, SeuratDisk, tidyverse, SeuratObject
)
options(future.globals.maxSize = 1e9)
options(Seurat.object.assay.version = "v5")

#### PARAM Settings #####
args <- commandArgs(trailingOnly = TRUE)
# `<List<str>>` Sample IDs
sample_ids <- unlist(strsplit(args[1], split = ","))
# `<List<str>>` Project IDs
project_ids <- unlist(strsplit(args[2], split = ","))
# `<List<str>>` filtered_feature_bc_matrix.h5
all_bcmat_path <- unlist(strsplit(args[3], split = ","))
# `<List<str>>` Directory of `data/GSE*/GSM*`
all_data_sample_dir_path <- unlist(strsplit(args[4], split = ","))
# `<str>` Output file name (excluding .rds)
outfile_path <- args[5]
# `<str>` Log file path
logpath_runtime <- args[6]
# `<str>` Project name
project_name <- args[7]
rm(args)
#########################

log_out <- function(content) {
    write(
        content,
        file = logpath_runtime, append = TRUE
    )
}
log_out_apply <- function(seurat, content) {
    write(
        content,
        file = logpath_runtime, append = TRUE
    )
    return(seurat)
}

if (length(all_bcmat_path) != length(all_data_sample_dir_path)) {
    print(
        "INTERNAL ERR: all_bcmat_path and all_data_sample_dir_path should be same length" # nolint: line_length_linter.
    )
}
log_out(
    "\n├─ Processing..." # nolint: line_length_linter.
)

cnt <- 1
for (path in all_bcmat_path) {
    log_out(paste0(
        "├─ Loading ", all_bcmat_path[cnt],
        cnt, "/", length(all_bcmat_path)
    ))
    celltype_pred_path <-
        paste0(
            all_data_sample_dir_path[cnt], "/celltype_predicted.tsv"
        )
    doublet_info_path <-
        paste0(
            all_data_sample_dir_path[cnt], "/doublet_filtered.tsv"
        )
    qc_matrix_path <-
        paste0(
            all_data_sample_dir_path[cnt], "/qc_matrix.tsv"
        )
    if (file.exists(all_bcmat_path[cnt])) {
        seurat <-
            Read10X_h5(all_bcmat_path[cnt]) %>%
            CreateSeuratObject(
                project = project_name
            )
        seurat@meta.data <-
            seurat@meta.data %>%
            tibble::rownames_to_column("barcodes") %>%
            mutate(
                sample = sample_ids[cnt],
                project = project_ids[cnt],
                cell = paste0(
                    sample, "_", row_number()
                )
            )
        if (file.exists(celltype_pred_path)) {
            seurat@meta.data <-
                seurat@meta.data %>%
                left_join(
                    read_tsv(
                        celltype_pred_path,
                        show_col_types = FALSE
                    ),
                    by = "cell"
                )
        }
        if (file.exists(doublet_info_path)) {
            seurat@meta.data <-
                seurat@meta.data %>%
                left_join(
                    read_tsv(
                        doublet_info_path,
                        show_col_types = FALSE
                    ),
                    by = c("barcodes" = "cell")
                )
        }
        if (file.exists(qc_matrix_path)) {
            seurat@meta.data <-
                seurat@meta.data %>%
                left_join(
                    read_tsv(
                        qc_matrix_path,
                        show_col_types = FALSE
                    ),
                    by = c("barcodes" = "cell")
                )
        }
        seurat@meta.data <-
            seurat@meta.data %>%
            tibble::column_to_rownames("barcodes")
        seurat <-
            seurat %>%
            RenameCells(
                new.names =
                    seurat@meta.data %>%
                        distinct(cell) %>%
                        pull()
            )
        log_out("├─ └─ Done!")
        if (cnt == 1) {
            merged <- seurat
        } else {
            merged <- merge(
                merged, seurat
            )
        }
        rm(seurat)
        gc(verbose = FALSE, reset = FALSE)
    } else {
        log_out("├─ └─ Project does not exists. Skip.")
    }
    cnt <- cnt + 1
}
merged <- JoinLayers(merged)
merged[["RNA"]] <- split(merged[["RNA"]], f = merged$project)
log_out("├─ Normalizing...")
merged <- NormalizeData(merged, verbose = FALSE)
log_out("├─ FindVariableFeatures...")
merged <- FindVariableFeatures(merged, verbose = FALSE)
log_out("├─ ScaleData...")
merged <- ScaleData(merged, verbose = FALSE)
log_out("├─ RunPCA...")
merged <- RunPCA(merged, verbose = FALSE)
log_out("├─ FindNeighbors...")
merged <- FindNeighbors(
    merged,
    dims = 1:30, reduction = "pca",
    verbose = FALSE
)
log_out("├─ FindClusters...")
merged <- FindClusters(
    merged,
    resolution = 1, cluster.name = "unintegrated_clusters",
    verbose = FALSE
)
log_out("├─ RunUMAP...")
merged <- RunUMAP(
    merged,
    dims = 1:30, reduction = "pca", reduction.name = "unintegrated",
    verbose = FALSE
)
log_out("├─ IntegrateLayers...")
merged <- IntegrateLayers(
    object = merged, method = HarmonyIntegration,
    orig.reduction = "pca", new.reduction = "harmony",
    verbose = FALSE
)
log_out("├─ FindNeighbors...")
merged <- FindNeighbors(
    merged,
    reduction = "harmony", dims = 1:30, verbose = FALSE
)
log_out("├─ FindClusters...")
merged <- FindClusters(
    merged,
    resolution = 1, cluster.name = "cluster.harmony",
    verbose = FALSE
)
log_out("├─ RunUMAP...")
merged <- RunUMAP(
    merged,
    reduction = "harmony", dims = 1:30, reduction.name = "harmony",
    verbose = FALSE
)
gc(verbose = FALSE, reset = FALSE)
log_out("├─ Writing h5 seurat file...")
merged %>%
    saveRDS(
        paste0(
            outfile_path,
            ".rds"
        )
    )
log_out("└─ Done!")
