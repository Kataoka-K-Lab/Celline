###############################################################################
# streamlined_slingshot_pipeline.R
#   A lean, “latent‑only” trajectory‑analysis pipeline.
#   • No PCA / ScaleData / FindVariableFeatures
#   • Cell metadata are already embedded in the AnnData object (no separate TSV)
#   • English comments and messages only
#   • Stops immediately if any required gene is missing
#   • Namespace‑qualified function calls for clarity
###############################################################################

# ────────────────────────────── 0. Packages ────────────────────────────────
load_libraries <- function() {
  suppressPackageStartupMessages({
    library(tidyverse)            # dplyr, ggplot2, readr, purrr, etc.
    library(Seurat)
    library(slingshot)
    library(SingleCellExperiment)
    library(jsonlite)
    library(cowplot);    library(patchwork)
    library(Polychrome); library(scales)
    library(fs)
  })
  # Use environment variable or default path to find readh5ad.R
  celline_root <- Sys.getenv("CELLINE_ROOT", "")
  if (celline_root != "" && file.exists(file.path(celline_root, "template", "hook", "R", "readh5ad.R"))) {
    readh5ad_path <- file.path(celline_root, "template", "hook", "R", "readh5ad.R")
  } else {
    # Fallback: assume readh5ad.R is in the parent directory
    script_dir <- dirname(sys.frame(1)$ofile)
    if (is.null(script_dir) || script_dir == "" || script_dir == ".") {
      script_dir <- getwd()
    }
    readh5ad_path <- file.path(dirname(script_dir), "readh5ad.R")
  }

  if (!file.exists(readh5ad_path)) {
    stop("Cannot find readh5ad.R at: ", readh5ad_path)
  }
  source(readh5ad_path)
}

# ─────────────────── 1. Input & required‑gene validation ───────────────────
read_inputs <- function(h5ad_path,
                        progenitor_markers,
                        differentiation_markers,
                        marker_file) {
  # Read AnnData → Seurat
  seurat_obj <- read_h5ad(h5ad_path)

  # Build required gene list (A–D)
  data("cc.genes.updated.2019", package = "Seurat")
  cell_cycle_genes <- unlist(cc.genes.updated.2019)

  mst_markers <- readr::read_tsv(marker_file,
                                 show_col_types = FALSE)$gene

  required_genes <- union(cell_cycle_genes,
                    union(progenitor_markers,
                    union(differentiation_markers,
                          mst_markers)))

  missing <- setdiff(required_genes, rownames(seurat_obj))
  if (length(missing) > 0) {
    stop("Required genes are missing: ",
         paste(head(missing, 10), collapse = ", "),
         if (length(missing) > 10) " …" else "")
  }
  message("[INFO] All required genes present (n = ", length(required_genes), ").")
  seurat_obj
}

# ───────────────────── 2. Minimal preprocessing (latent only) ──────────────
preprocess_seurat_latent <- function(seurat,
                                     latent_dims = 1:10,
                                     resolution  = 0.5) {

  # Validate parameters
  if (resolution <= 0) stop("resolution must be positive")

  message("[INFO] Starting latent-space preprocessing pipeline...")
  message("[DEBUG] Initial object: ", ncol(seurat), " cells, ", nrow(seurat), " genes")

  # Check for latent embeddings - prefer 'latent', then 'scvi', then 'X_scvi'
  latent_reduction_name <- NULL
  if ("latent" %in% names(seurat@reductions)) {
    latent_reduction_name <- "latent"
  } else if ("scvi" %in% names(seurat@reductions)) {
    latent_reduction_name <- "scvi"
  } else if ("X_scvi" %in% names(seurat@reductions)) {
    latent_reduction_name <- "X_scvi"
  } else {
    available_reductions <- names(seurat@reductions)
    stop("No latent embedding found. Available reductions: ",
         paste(available_reductions, collapse = ", "))
  }

  message("[DEBUG] Using latent reduction: ", latent_reduction_name)

  latent_embeddings <- Seurat::Embeddings(seurat, latent_reduction_name)
  available_dims <- ncol(latent_embeddings)
  max_dim <- min(max(latent_dims), available_dims)
  dims_to_use <- 1:max_dim

  message("[DEBUG] Latent embedding dimensions: ", available_dims, ", using: ", max_dim)

  # Apply QC filter if present
  if ("filter" %in% colnames(seurat@meta.data)) {
    n_before <- ncol(seurat)

    # Debug filter column
    filter_summary <- table(seurat@meta.data$filter, useNA = "ifany")
    message("[DEBUG] Filter column summary: ", paste(names(filter_summary), "=", filter_summary, collapse = ", "))

    seurat <- subset(seurat, filter == FALSE)
    n_after <- ncol(seurat)
    message("[INFO] Filtered out ", n_before - n_after, " cells (", n_before, " → ", n_after, ")")

    # Check if any cells remain
    if (n_after == 0) {
      stop("No cells remaining after QC filtering")
    }

    # Check for minimum cell count
    if (n_after < 100) {
      message("[WARNING] Very few cells remaining after filtering (", n_after, "). This may cause downstream issues.")
    }
  } else {
    message("[INFO] No filter column found, skipping QC filtering")
  }

  # Wrap each step with error handling
  tryCatch({
    seurat <- seurat |>
      # Find neighbors
      {\(so) {
        message("[INFO] Building neighbor graph...")
        message("[DEBUG] Using latent dimensions: ", paste(range(dims_to_use), collapse = "-"))
        result <- Seurat::FindNeighbors(so, reduction = latent_reduction_name,
                                      dims = dims_to_use,
                                      verbose = FALSE)
        message("[DEBUG] Neighbor graph completed")
        result
      }}() |>
      # Find clusters
      {\(so) {
        message("[INFO] Finding clusters with resolution ", resolution, "...")
        result <- Seurat::FindClusters(so, resolution = resolution,
                                     verbose = FALSE)
        n_clusters <- length(levels(result$seurat_clusters))
        message("[DEBUG] Found ", n_clusters, " clusters")

        if (n_clusters < 2) {
          message("[WARNING] Only ", n_clusters, " cluster found. Consider adjusting resolution.")
        }

        result
      }}() |>
      # UMAP
      {\(so) {
        message("[INFO] Computing UMAP...")
        result <- Seurat::RunUMAP(so, reduction = latent_reduction_name,
                                dims = dims_to_use,
                                verbose = FALSE)
        message("[DEBUG] UMAP completed")
        result
      }}()

    return(seurat)

  }, error = function(e) {
    message("[ERROR] Latent preprocessing failed: ", e$message)
    message("[DEBUG] Current object state:")
    message("  - Cells: ", ncol(seurat))
    message("  - Genes: ", nrow(seurat))
    message("  - Reductions: ", paste(names(seurat@reductions), collapse = ", "))
    stop("Preprocessing failed: ", e$message)
  })
}

# ───────────────────── 3. Cell‑cycle scoring ───────────────────────────────
score_cell_cycle <- function(seurat) {
  data("cc.genes.updated.2019", package = "Seurat")
  s_genes   <- intersect(cc.genes.updated.2019$s.genes,   rownames(seurat))
  g2m_genes <- intersect(cc.genes.updated.2019$g2m.genes, rownames(seurat))

  seurat |>
    Seurat::AddModuleScore(list(s_genes),   name = "S_phase") |>
    Seurat::AddModuleScore(list(g2m_genes), name = "G2M_phase") |>
    Seurat::CellCycleScoring(s.features   = s_genes,
                             g2m.features = g2m_genes,
                             set.ident    = FALSE)
}

# ───────────────────── 4. Root‑cluster selection ───────────────────────────
select_root_cluster <- function(seurat,
                                progenitor_markers,
                                differentiation_markers) {

  message("[INFO] Selecting root cluster based on marker expression...")

  # Validate marker genes
  prog <- intersect(progenitor_markers,      rownames(seurat))
  diff <- intersect(differentiation_markers, rownames(seurat))

  message("[DEBUG] Progenitor markers found: ", length(prog), "/", length(progenitor_markers),
          " (", paste(head(prog, 3), collapse = ", "), if(length(prog) > 3) "..." else "", ")")
  message("[DEBUG] Differentiation markers found: ", length(diff), "/", length(differentiation_markers),
          " (", paste(head(diff, 3), collapse = ", "), if(length(diff) > 3) "..." else "", ")")

  if (length(prog) == 0) {
    stop("No progenitor markers found in dataset. Available genes: ",
         paste(head(rownames(seurat), 10), collapse = ", "), "...")
  }

  if (length(diff) == 0) {
    stop("No differentiation markers found in dataset. Available genes: ",
         paste(head(rownames(seurat), 10), collapse = ", "), "...")
  }

  seurat |>
    Seurat::AddModuleScore(list(prog), name = "Prog") |>
    Seurat::AddModuleScore(list(diff), name = "Diff") |>
    {\(so) {
      meta <- so@meta.data |>
        dplyr::transmute(cluster = as.character(seurat_clusters),
                         prog   = Prog1,
                         cycle  = S.Score + G2M.Score,
                         diff   = Diff1)

      scores <- meta |>
        dplyr::group_by(cluster) |>
        dplyr::summarise(dplyr::across(c(prog, cycle, diff), mean),
                         n = dplyr::n(),
                         .groups = "drop") |>
        dplyr::mutate(prog_sc  = scales::rescale(prog,  to = c(0, 1)),
                      cycle_sc = scales::rescale(cycle, to = c(0, 1)),
                      diff_sc  = scales::rescale(diff,  to = c(0, 1)),
                      root_score = 2*prog_sc + 0.5*cycle_sc - 3*diff_sc) |>
        dplyr::arrange(dplyr::desc(root_score))

      message("[INFO] Root cluster selected: ", scores$cluster[1], " (score: ", round(scores$root_score[1], 3), ")")
      message("[DEBUG] Root cluster details - prog: ", round(scores$prog[1], 3),
              ", cycle: ", round(scores$cycle[1], 3), ", diff: ", round(scores$diff[1], 3), ")")

      list(start_cluster = scores$cluster[1],
           score_table   = scores,
           seurat        = so)
    }}()
}

# ───────────────────── 5. Slingshot (latent) ───────────────────────────────
run_slingshot_latent <- function(seurat,
                                 start_cluster,
                                 latent_dims = 1:10,
                                 latent_reduction_name = "scvi") {

  message("[INFO] Running Slingshot on latent space...")

  # Validate input parameters
  if (is.null(seurat) || ncol(seurat) == 0) {
    stop("Seurat object is empty or NULL")
  }

  if (is.null(start_cluster) || !start_cluster %in% levels(seurat$seurat_clusters)) {
    stop("Invalid start_cluster: ", start_cluster, ". Available clusters: ",
         paste(levels(seurat$seurat_clusters), collapse = ", "))
  }

  # Check cluster sizes
  cluster_sizes <- table(seurat$seurat_clusters)
  message("[DEBUG] Cluster sizes: ", paste(names(cluster_sizes), "=", cluster_sizes, collapse = ", "))

  small_clusters <- names(cluster_sizes)[cluster_sizes < 10]
  if (length(small_clusters) > 0) {
    message("[WARNING] Small clusters detected (< 10 cells): ", paste(small_clusters, collapse = ", "))
  }

  # Validate latent dimensions
  if (!(latent_reduction_name %in% names(seurat@reductions))) {
    stop("Latent embedding not found in Seurat object")
  }

  latent_data <- Seurat::Embeddings(seurat, latent_reduction_name)
  available_dims <- ncol(latent_data)
  latent_dims <- intersect(latent_dims, 1:available_dims)
  message("[DEBUG] Using latent dimensions: ", paste(latent_dims, collapse = ", "))

  if (length(latent_dims) < 2) {
    stop("Need at least 2 latent dimensions, but only ", length(latent_dims), " available")
  }

  sce <- as.SingleCellExperiment(seurat)
  # Properly assign to SingleCellExperiment colData
  coldata_df <- colData(sce)
  coldata_df$traj_cluster <- seurat$seurat_clusters
  colData(sce) <- coldata_df

  # Debug: Check what reductions are available in SingleCellExperiment
  available_reduced_dims <- names(reducedDims(sce))
  message("[DEBUG] Available reducedDims in SCE: ", paste(available_reduced_dims, collapse = ", "))

  # Get latent embeddings directly from Seurat and add to SCE
  latent_embeddings <- Embeddings(seurat, latent_reduction_name)
  message("[DEBUG] Latent embeddings dimensions: ", paste(dim(latent_embeddings), collapse = " x "))

  # Add latent embeddings to SCE as "latent" if not already present
  if (!"latent" %in% available_reduced_dims) {
    reducedDim(sce, "latent") <- latent_embeddings[, latent_dims]
    message("[DEBUG] Added latent embeddings to SCE as 'latent'")
    sce_reduction_name <- "latent"
  } else {
    sce_reduction_name <- "latent"
  }

  message("[DEBUG] Using SCE reduction name: ", sce_reduction_name)
  message("[DEBUG] SCE latent dimensions: ", paste(dim(reducedDim(sce, sce_reduction_name)), collapse = " x "))

  # Check for sufficient cluster connectivity
  n_clusters <- length(unique(seurat$seurat_clusters))
  message("[DEBUG] Number of clusters: ", n_clusters)

  if (n_clusters < 2) {
    stop("Need at least 2 clusters for trajectory analysis, found: ", n_clusters)
  }

  # Run slingshot with performance optimizations and error handling
  tryCatch({
    message("[INFO] Starting slingshot analysis with ", ncol(sce), " cells...")

    # For large datasets, use approx_points to speed up slingshot
    use_approx <- ncol(sce) > 5000
    if (use_approx) {
      message("[INFO] Using approx_points for large dataset optimization")
      slingshot_result <- slingshot::slingshot(
        sce,
        clusterLabels = "traj_cluster",
        reducedDim    = sce_reduction_name,
        start.clus    = start_cluster,
        extend        = "n",
        shrink        = TRUE,
        omega         = TRUE,
        approx_points = 300  # Reduce computational burden
      )
    } else {
      slingshot_result <- slingshot::slingshot(
        sce,
        clusterLabels = "traj_cluster",
        reducedDim    = sce_reduction_name,
        start.clus    = start_cluster,
        extend        = "n",
        shrink        = TRUE,
        omega         = TRUE
      )
    }

    # Validate slingshot results
    n_lineages <- length(slingshot::slingLineages(slingshot_result))
    message("[INFO] Slingshot completed successfully with ", n_lineages, " lineages")

    if (n_lineages == 0) {
      stop("Slingshot failed to identify any lineages")
    }

    return(slingshot_result)

  }, error = function(e) {
    message("[ERROR] Slingshot failed with error: ", e$message)

    # Provide diagnostic information
    message("[DEBUG] Diagnostic information:")
    message("  - Start cluster: ", start_cluster)
    message("  - Total cells: ", ncol(seurat))
    message("  - Latent dimensions used: ", paste(latent_dims, collapse = ", "))
    message("  - Cluster sizes: ", paste(names(cluster_sizes), "=", cluster_sizes, collapse = ", "))

    # Check if error is due to singular matrix
    if (grepl("singular|condition number", e$message, ignore.case = TRUE)) {
      message("[ERROR] Singular matrix detected. This usually indicates:")
      message("  1. Too few cells in some clusters")
      message("  2. Clusters are too similar (no clear trajectory)")
      message("  3. Latent dimensions may need adjustment")
      message("[SUGGESTION] Try increasing clustering resolution or using fewer latent dimensions")
    }

    stop("Slingshot analysis failed: ", e$message)
  })
}

# ───────────────────── 6a. Utility: vector accessor ────────────────────────
vec_from_col <- function(sce, col) {
  v <- SingleCellExperiment::colData(sce)[[col]]
  if (is(v, "DataFrame")) v <- unlist(as.list(v))
  as.vector(v)
}

# ───────────────────── 6b. Result export helpers ───────────────────────────
export_pseudotime <- function(sce, file_path = "pseudotime.tsv") {
  slingshot::slingPseudotime(sce) |>
    as.data.frame() |>
    tibble::rownames_to_column("cell") |>
    readr::write_tsv(file_path)
  message("[INFO] Pseudotime saved → ", fs::path_abs(file_path))
}

export_lineage_celltypes <- function(sce,
                                     cell_type_col = NULL,
                                     file_path    = "lineage_celltypes.json") {

  # Auto-detect cell type column if not specified
  if (is.null(cell_type_col)) {
    potential_cols <- c("scpred_prediction", "cell_type_cluster_weighted", "cell_type_cluster", 
                       "cell_type", "celltype", "predicted.celltype", "predicted_celltype",
                       "annotation", "leiden_scvi", "seurat_clusters")
    
    available_cols <- colnames(SingleCellExperiment::colData(sce))
    
    for (col in potential_cols) {
      if (col %in% available_cols) {
        cell_type_col <- col
        message("[DEBUG] Auto-detected cell type column: ", col)
        break
      }
    }
    
    if (is.null(cell_type_col)) {
      stop("No suitable cell type column found. Available columns: ", 
           paste(available_cols, collapse = ", "))
    }
  }
  
  # Verify the column exists
  if (!cell_type_col %in% colnames(SingleCellExperiment::colData(sce))) {
    stop("Cell type column '", cell_type_col, "' not found in SCE object. Available columns: ",
         paste(colnames(SingleCellExperiment::colData(sce)), collapse = ", "))
  }

  long_tbl <- slingshot::slingPseudotime(sce) |>
    as.data.frame() |>
    tibble::rownames_to_column("cell") |>
    tidyr::pivot_longer(-cell,
                        names_to  = "lineage",
                        values_to = "pt") |>
    tidyr::drop_na(pt)

  meta_tbl <- tibble::tibble(cell      = colnames(sce),
                             cell_type = vec_from_col(sce, cell_type_col))

  long_tbl <- dplyr::left_join(long_tbl, meta_tbl, by = "cell")

  lineage_tbl <- long_tbl |>
    dplyr::group_by(lineage, cell_type) |>
    dplyr::summarise(median_pt = median(pt), .groups = "drop") |>
    dplyr::arrange(lineage, median_pt) |>
    dplyr::summarise(cell_types = list(unique(cell_type)),
                     .by = lineage)

  jsonlite::write_json(setNames(lineage_tbl$cell_types, lineage_tbl$lineage),
                       file_path,
                       pretty     = TRUE,
                       auto_unbox = TRUE)
  message("[INFO] Lineage‑celltype JSON saved → ", fs::path_abs(file_path), " using column: ", cell_type_col)
}

# ───────────────────── 7. Plots (UMAP, heatmap, MST) ───────────────────────
make_plots <- function(seurat,
                       score_table,
                       start_cluster) {

  umap <- Seurat::Embeddings(seurat, "umap") |>
          as.data.frame() |>
          dplyr::rename(U1 = 1, U2 = 2)

  meta <- dplyr::bind_cols(seurat@meta.data, umap)

  cluster_palette <- {
    n <- length(unique(meta$seurat_clusters))
    if (n <= 36) {
      setNames(Polychrome::palette36.colors(n),
               sort(unique(as.character(meta$seurat_clusters))))
    } else {
      setNames(scales::hue_pal()(n),
               sort(unique(as.character(meta$seurat_clusters))))
    }
  }

  p_umap <- ggplot2::ggplot(meta,
                            ggplot2::aes(U1, U2,
                                         colour = seurat_clusters)) +
              ggplot2::geom_point(size = 0.5) +
              ggplot2::geom_point(data = meta |>
                                   dplyr::filter(seurat_clusters == start_cluster),
                                   colour = "red",
                                   size   = 1) +
              ggplot2::scale_colour_manual(values = cluster_palette) +
              ggplot2::theme_minimal() +
              ggplot2::theme(panel.background = ggplot2::element_rect(fill = "white", color = NA),
                             plot.background = ggplot2::element_rect(fill = "white", color = NA)) +
              ggplot2::labs(title = "UMAP (clusters)")

  p_heat <- score_table |>
    tidyr::pivot_longer(-cluster,
                        names_to  = "metric",
                        values_to = "value") |>
    dplyr::mutate(metric = factor(metric,
                                  c("prog", "cycle", "diff", "root_score"))) |>
    ggplot2::ggplot(ggplot2::aes(cluster, metric, fill = value)) +
      ggplot2::geom_tile() +
      ggplot2::geom_text(ggplot2::aes(label = round(value, 2)),
                         size = 3) +
      ggplot2::scale_fill_gradient2(midpoint = 0) +
      ggplot2::theme_minimal() +
      ggplot2::theme(panel.background = ggplot2::element_rect(fill = "white", color = NA),
                     plot.background = ggplot2::element_rect(fill = "white", color = NA)) +
      ggplot2::labs(title = "Cluster scores")

  # Try to create cell type UMAP if cell type annotation is available
  p_celltype <- NULL
  # Prioritize proper cell type annotations over clustering results
  potential_celltype_cols <- c("cell_type_cluster_weighted", "cell_type_cluster", "cell_type", "celltype",
                              "predicted.celltype", "predicted_celltype", "annotation",
                              "leiden_scvi", "scpred_prediction")

  for (col in potential_celltype_cols) {
    if (col %in% colnames(meta)) {
      celltype_values <- meta[[col]]
      if (!is.null(celltype_values) && !all(is.na(celltype_values))) {
        # Create color palette for cell types
        unique_celltypes <- unique(as.character(celltype_values))
        unique_celltypes <- unique_celltypes[!is.na(unique_celltypes)]

        if (length(unique_celltypes) > 0 && length(unique_celltypes) <= 20) {  # Reasonable limit
          celltype_palette <- if (length(unique_celltypes) <= 36) {
                                setNames(Polychrome::palette36.colors(length(unique_celltypes)),
                                        unique_celltypes)
                              } else {
                                setNames(scales::hue_pal()(length(unique_celltypes)),
                                        unique_celltypes)
                              }

          p_celltype <- ggplot2::ggplot(meta, ggplot2::aes(U1, U2, colour = !!rlang::sym(col))) +
                          ggplot2::geom_point(size = 0.6, alpha = 0.8) +
                          ggplot2::scale_colour_manual(values = celltype_palette, na.value = "gray") +
                          ggplot2::theme_minimal() +
                          ggplot2::theme(panel.background = ggplot2::element_rect(fill = "white", color = NA),
                                         plot.background = ggplot2::element_rect(fill = "white", color = NA)) +
                          ggplot2::labs(title = paste("UMAP (", col, ")"))

          message("[DEBUG] Created cell type UMAP using column: ", col)
          break  # Use the first available cell type column
        }
      }
    }
  }

  # Return plots (include cell type UMAP if created successfully)
  plots <- list(umap = p_umap, heat = p_heat)
  if (!is.null(p_celltype)) {
    plots[["celltype_umap"]] <- p_celltype
  }

  return(plots)
}

save_plots <- function(plot_list,
                       dir_path,
                       width_cm  = 20,
                       height_cm = 18) {
  purrr::iwalk(plot_list, function(p, n) {
    ggplot2::ggsave(file.path(dir_path, paste0(n, ".pdf")),
                    plot   = p,
                    width  = width_cm,
                    height = height_cm,
                    units  = "cm")
  })
  message("[INFO] Figures saved → ", fs::path_abs(dir_path))
}

# ─────────────────── 8. Slingshot MST plotting (latent) ────────────────────

# Function to create separate MST plots for clusters, cell types, and markers
create_separate_mst_plots <- function(sce,
                                     seurat_obj,
                                     output_dir,
                                     umap_dims = 1:2,
                                     linewidth = 0.8,
                                     arrow_len = 0.35,
                                     arrow_angle = 25) {

  message("[INFO] Creating separate MST plots...")

  # Ensure output directory exists
  if (!dir.exists(output_dir)) {
    dir.create(output_dir, recursive = TRUE)
  }

  # Create markers subdirectory
  markers_dir <- file.path(output_dir, "markers")
  if (!dir.exists(markers_dir)) {
    dir.create(markers_dir, recursive = TRUE)
  }

  # Define variables for different plot types
  cluster_vars <- c("leiden_scvi", "seurat_clusters")
  # Prioritize proper cell type annotations over clustering results
  celltype_vars <- c("cell_type_cluster_weighted", "cell_type_cluster", "cell_type",
                     "celltype", "predicted.celltype", "predicted_celltype", "annotation", "scpred_prediction")
  print(colnames(seurat_obj@meta.data))
  seurat_obj@meta.data %>%
  write_tsv("/home/yuyasato/work3/vhco_season2/2_vascularized/trajectory/integrated/test.metadata.tsv")
  # Find available cluster variables
  available_cluster_vars <- cluster_vars[
    cluster_vars %in% c(colnames(seurat_obj@meta.data),
                        colnames(SingleCellExperiment::colData(sce)))
  ]

  # Find available cell type variables
  available_celltype_vars <- celltype_vars[
    celltype_vars %in% c(colnames(seurat_obj@meta.data),
                         colnames(SingleCellExperiment::colData(sce)))
  ]

  # Get marker genes - USE ALL MARKERS instead of limited subset
  marker_file <- "/home/yuyasato/work3/vhco_season2/meta/__markers.tsv"
  if (file.exists(marker_file)) {
    all_marker_genes <- readr::read_tsv(marker_file, show_col_types = FALSE)$gene |>
                        intersect(rownames(seurat_obj))

    # Use ALL available marker genes for comprehensive visualization
    selected_marker_genes <- all_marker_genes

    message("[DEBUG] Found ", length(all_marker_genes), " marker genes in dataset")
  } else {
    selected_marker_genes <- c()
    message("[WARNING] Marker file not found: ", marker_file)
  }

  message("[DEBUG] Available cluster vars: ", paste(available_cluster_vars, collapse = ", "))
  message("[DEBUG] Available celltype vars: ", paste(available_celltype_vars, collapse = ", "))
  message("[DEBUG] Selected marker genes: ", paste(selected_marker_genes, collapse = ", "))

  # Create individual MST plotting function
  create_single_mst_plot <- function(var_name) {
    tryCatch({
      mst_plot <- plotSlingshotMST_latent(sce,
                                         seurat_obj,
                                         group_vars = var_name,
                                         umap_dims = umap_dims,
                                         linewidth = linewidth,
                                         arrow_len = arrow_len,
                                         arrow_angle = arrow_angle,
                                         ncol_panels = 1)
      return(mst_plot)
    }, error = function(e) {
      message("[ERROR] Failed to create MST plot for '", var_name, "': ", e$message)
      return(NULL)
    })
  }

  plots_created <- 0

  # 1. Create mst_clusters.png
  if (length(available_cluster_vars) > 0) {
    cluster_var <- available_cluster_vars[1]  # Use first available cluster variable
    cluster_plot <- create_single_mst_plot(cluster_var)

    if (!is.null(cluster_plot)) {
      tryCatch({
        ggplot2::ggsave(file.path(output_dir, "mst_clusters.png"),
                        plot = cluster_plot,
                        width = 20,
                        height = 18,
                        units = "cm",
                        dpi = 300)
        message("[INFO] Saved mst_clusters.png using '", cluster_var, "'")
        plots_created <- plots_created + 1
      }, error = function(e) {
        message("[ERROR] Failed to save mst_clusters.png: ", e$message)
      })
    }
  }

  # 2. Create mst_celltypes.png
  if (length(available_celltype_vars) > 0) {
    celltype_var <- available_celltype_vars[1]  # Use first available celltype variable
    celltype_plot <- create_single_mst_plot(celltype_var)

    if (!is.null(celltype_plot)) {
      tryCatch({
        ggplot2::ggsave(file.path(output_dir, "mst_celltypes.png"),
                        plot = celltype_plot,
                        width = 20,
                        height = 18,
                        units = "cm",
                        dpi = 300)
        message("[INFO] Saved mst_celltypes.png using '", celltype_var, "'")
        plots_created <- plots_created + 1
      }, error = function(e) {
        message("[ERROR] Failed to save mst_celltypes.png: ", e$message)
      })
    }
  }

  # 3. Create individual marker gene plots
  for (marker in selected_marker_genes) {
    marker_plot <- create_single_mst_plot(marker)

    if (!is.null(marker_plot)) {
      marker_filename <- paste0(marker, ".png")
      tryCatch({
        ggplot2::ggsave(file.path(markers_dir, marker_filename),
                        plot = marker_plot,
                        width = 20,
                        height = 18,
                        units = "cm",
                        dpi = 300)
        message("[INFO] Saved markers/", marker_filename)
        plots_created <- plots_created + 1
      }, error = function(e) {
        message("[ERROR] Failed to save markers/", marker_filename, ": ", e$message)
      })
    }
  }

  message("[INFO] Successfully created ", plots_created, " separate MST plots")
  return(plots_created)
}

create_lineage_legend <- function(sce, lineage_colors) {
  lin_list <- slingshot::slingLineages(sce)
  n_lin    <- length(lin_list)

  legend_tbl <- tibble::tibble(
    lineage_num = seq_len(n_lin),
    lineage_id  = paste0("Lineage", seq_len(n_lin)),
    color       = lineage_colors[seq_len(n_lin)],
    path        = purrr::map_chr(lin_list, ~ paste(.x, collapse = " → "))
  )

  ggplot2::ggplot(legend_tbl,
                  ggplot2::aes(x = 1, y = lineage_num)) +
    ggplot2::geom_point(ggplot2::aes(color = lineage_id), size = 4) +
    ggplot2::geom_text(ggplot2::aes(label = paste0("L", lineage_num,
                                                   ": ", path)),
                       hjust = 0, nudge_x = 0.1, size = 3) +
    ggplot2::scale_color_manual(values = setNames(lineage_colors,
                                                  legend_tbl$lineage_id)) +
    ggplot2::scale_y_reverse() +
    ggplot2::theme_void() +
    ggplot2::theme(legend.position = "none",
                   plot.margin = ggplot2::margin(10, 10, 10, 10),
                   panel.background = ggplot2::element_rect(fill = "white", color = NA),
                   plot.background = ggplot2::element_rect(fill = "white", color = NA)) +
    ggplot2::labs(title = "Lineage color legend") +
    ggplot2::xlim(0.5, 8)
}

plotSlingshotMST_latent <- function(sce,
                                    seurat_obj,
                                    group_vars,
                                    umap_dims   = 1:2,
                                    linewidth   = 0.8,
                                    arrow_len   = 0.35,
                                    arrow_angle = 25,
                                    ncol_panels = 3) {

  stopifnot(length(umap_dims) == 2)

  # Debug: Check available reductions in SCE
  available_sce_reductions <- names(SingleCellExperiment::reducedDims(sce))
  cat("[DEBUG] Available SCE reductions: ", paste(available_sce_reductions, collapse = ", "), "\n")

  # Get UMAP coordinates with fallback options
  coord <- NULL
  umap_reduction_name <- NULL

  # Try different UMAP reduction names
  umap_candidates <- c("UMAP", "umap", "X_umap")
  for (candidate in umap_candidates) {
    if (candidate %in% available_sce_reductions) {
      tryCatch({
        coord <- SingleCellExperiment::reducedDims(sce)[[candidate]][, umap_dims, drop = FALSE]
        umap_reduction_name <- candidate
        cat("[DEBUG] Using SCE UMAP reduction: ", candidate, "\n")
        break
      }, error = function(e) {
        cat("[WARNING] Failed to get coordinates from SCE reduction '", candidate, "': ", e$message, "\n")
      })
    }
  }

  # If SCE UMAP failed, try to get from Seurat object
  if (is.null(coord)) {
    cat("[DEBUG] SCE UMAP not found, trying Seurat UMAP...\n")
    tryCatch({
      coord <- Seurat::Embeddings(seurat_obj, "umap")[, umap_dims, drop = FALSE]
      umap_reduction_name <- "umap (from Seurat)"
      cat("[DEBUG] Using Seurat UMAP coordinates\n")
    }, error = function(e) {
      stop("Failed to get UMAP coordinates from both SCE and Seurat objects: ", e$message)
    })
  }

  if (is.null(coord) || nrow(coord) == 0) {
    stop("No valid UMAP coordinates found")
  }

  colnames(coord) <- c("d1", "d2")
  cat("[DEBUG] UMAP coordinates dimensions: ", nrow(coord), " x ", ncol(coord), "\n")
  cat("[DEBUG] UMAP coordinate ranges: d1 [", min(coord[,1]), ", ", max(coord[,1]),
          "], d2 [", min(coord[,2]), ", ", max(coord[,2]), "]\n")

  cell_df_base <- tibble::tibble(d1 = coord[, 1],
                                 d2 = coord[, 2],
                                 cluster = as.character(sce$traj_cluster))

  # Debug: Check cell_df_base
  cat("[DEBUG] cell_df_base dimensions: ", nrow(cell_df_base), " x ", ncol(cell_df_base), "\n")
  cat("[DEBUG] Unique clusters: ", paste(unique(cell_df_base$cluster), collapse = ", "), "\n")

  centers <- cell_df_base |>
    dplyr::group_by(cluster) |>
    dplyr::summarise(cen1 = mean(d1),
                     cen2 = mean(d2),
                     .groups = "drop")

  cat("[DEBUG] Centers calculated: ", nrow(centers), " clusters\n")
  print(centers)

  lin_list <- slingshot::slingLineages(sce)
  cat("[DEBUG] Number of lineages: ", length(lin_list), "\n")
  cat("[DEBUG] Lineage paths: ", paste(sapply(lin_list, function(x) paste(x, collapse=" → ")), collapse="; "), "\n")

  edge_df  <- purrr::map_dfr(seq_along(lin_list), function(i) {
                tibble::tibble(from    = head(lin_list[[i]], -1),
                               to      = tail(lin_list[[i]], -1),
                               lineage = paste0("Lineage", i))
              }) |>
              dplyr::group_by(from, to) |>
              dplyr::slice(1) |>
              dplyr::ungroup() |>
              dplyr::left_join(centers, by = c("from" = "cluster")) |>
              dplyr::rename(x = cen1, y = cen2) |>
              dplyr::left_join(centers, by = c("to"   = "cluster")) |>
              dplyr::rename(xend = cen1, yend = cen2) |>
              tidyr::drop_na()

  cat("[DEBUG] Edge_df dimensions: ", nrow(edge_df), " x ", ncol(edge_df), "\n")
  if (nrow(edge_df) > 0) {
    cat("[DEBUG] Edge coordinate ranges: x [", min(edge_df$x), ", ", max(edge_df$x),
            "], y [", min(edge_df$y), ", ", max(edge_df$y), "]\n")
  }

  n_lin <- length(lin_list)
  lineage_cols <- if (n_lin <= 36) {
                    Polychrome::palette36.colors(n_lin)
                  } else {
                    scales::hue_pal()(n_lin)
                  }
  names(lineage_cols) <- paste0("Lineage", seq_len(n_lin))

  root_tbl <- tibble::tibble(cluster = purrr::map_chr(lin_list, dplyr::first),
                             lineage = names(lineage_cols))
  centers  <- dplyr::left_join(centers, root_tbl, by = "cluster")

  build_panel <- function(var) {
    cat("[DEBUG] Building panel for variable: ", var, "\n")

    # Add error handling for variable access
    val <- tryCatch({
      if (var %in% colnames(SingleCellExperiment::colData(sce))) {
        cat("[DEBUG] Found '", var, "' in SCE colData\n")
        SingleCellExperiment::colData(sce)[[var]]
      } else if (var %in% colnames(seurat_obj@meta.data)) {
        cat("[DEBUG] Found '", var, "' in Seurat metadata\n")
        seurat_obj[[var]][, 1]
      } else if (var %in% rownames(seurat_obj)) {
        cat("[DEBUG] Found '", var, "' as gene in Seurat\n")
        # Use normalized expression from data layer (log-normalized counts)
        expr_data <- tryCatch({
          LayerData(seurat_obj, layer = "data", features = var)
        }, error = function(e) {
          cat("[WARNING] Failed to get data layer, trying counts layer: ", e$message, "\n")
          LayerData(seurat_obj, layer = "counts", features = var)
        })
        as.numeric(expr_data[1, ])
      } else {
        cat("[WARNING] Variable '", var, "' not found anywhere, skipping\n")
        return(NULL)
      }
    }, error = function(e) {
      cat("[ERROR] Failed to access variable '", var, "': ", e$message, "\n")
      return(NULL)
    })

    if (is.null(val)) {
      cat("[DEBUG] Variable '", var, "' returned NULL, skipping panel\n")
      return(NULL)
    }

    is_num <- is.numeric(val)
    cat("[DEBUG] Variable '", var, "' is numeric: ", is_num, ", length: ", length(val), "\n")

    if (length(val) != nrow(cell_df_base)) {
      cat("[ERROR] Variable '", var, "' length (", length(val), ") doesn't match cell number (",
              nrow(cell_df_base), "), skipping\n")
      return(NULL)
    }

    cell_df <- dplyr::mutate(cell_df_base, val = val)
    cat("[DEBUG] Created cell_df for '", var, "' with ", nrow(cell_df), " rows\n")

    # Create base plot with points
    p <- ggplot2::ggplot(cell_df, ggplot2::aes(d1, d2))

    # Add cell points first (background layer) with appropriate color scale
    if (is_num) {
      p <- p +
        ggplot2::geom_point(ggplot2::aes(colour = val),
                           size = .6, alpha = .7) +
        ggplot2::scale_colour_viridis_c(name = var, option = "D")
    } else {
      # For categorical variables (like cell types)
      n_cat <- length(unique(val))
      cat_cols <- if (n_cat <= 36) {
                    Polychrome::palette36.colors(n_cat)
                  } else {
                    scales::hue_pal()(n_cat)
                  }
      names(cat_cols) <- sort(unique(as.character(val)))

      p <- p +
        ggplot2::geom_point(ggplot2::aes(colour = as.factor(val)),
                           size = .8, alpha = .8) +  # Slightly larger and more opaque for categorical
        ggplot2::scale_colour_manual(values = cat_cols, name = var)
    }

    # Add lineage segments (middle layer) with fixed colors, no conflicting scale
    if (nrow(edge_df) > 0) {
      # Ensure safe color assignment by converting to character
      segment_colors <- tryCatch({
        lineage_cols[as.character(edge_df$lineage)]
      }, error = function(e) {
        message("[WARNING] Color assignment failed for lineage segments, using default colors")
        rep("darkgray", nrow(edge_df))
      })

      p <- p +
        ggplot2::geom_segment(data = edge_df,
                              ggplot2::aes(x = x, y = y,
                                           xend = xend, yend = yend),
                              colour = segment_colors,
                              linewidth = linewidth + 0.2,  # Slightly thicker for visibility
                              arrow = ggplot2::arrow(type = "closed",
                                                   length = grid::unit(arrow_len, "cm"),
                                                   angle = arrow_angle),
                              alpha = 0.9)  # More opaque for better visibility
    }

    # Add cluster center points and text (top layer - most visible)
    center_colors <- tryCatch({
      ifelse(is.na(centers$lineage), "white",
             lineage_cols[as.character(centers$lineage)])
    }, error = function(e) {
      message("[WARNING] Center color assignment failed, using default colors")
      rep("white", nrow(centers))
    })

    p <- p +
      ggplot2::geom_point(data = centers,
                          ggplot2::aes(cen1, cen2),
                          fill = center_colors,
                          shape = 21,
                          colour = "black",
                          size = 5,    # Larger for better visibility
                          stroke = 1.5) +  # Thicker border
      ggplot2::geom_text(data = centers,
                         ggplot2::aes(cen1, cen2, label = cluster),
                         size = 3.5, vjust = -1.2, fontface = "bold")  # Bolder text

    p <- p +
      ggplot2::coord_equal() +
      ggplot2::theme_minimal(base_size = 13) +
      ggplot2::theme(panel.background = ggplot2::element_rect(fill = "white", color = NA),
                     plot.background = ggplot2::element_rect(fill = "white", color = NA)) +
      ggplot2::labs(title = paste("MST (", var, ")", sep = ""),
                    x = paste("UMAP", umap_dims[1]),
                    y = paste("UMAP", umap_dims[2]))

    cat("[DEBUG] Panel for '", var, "' created successfully\n")

    # Check if plot has valid data
    tryCatch({
      plot_data <- ggplot2::ggplot_build(p)
      n_data_points <- sum(sapply(plot_data$data, nrow))
      cat("[DEBUG] Panel for '", var, "' has ", n_data_points, " data points across layers\n")
    }, error = function(e) {
      cat("[WARNING] Could not build plot data for '", var, "': ", e$message, "\n")
    })

    return(p)
  }

  # Create panels with enhanced error handling
  cat("[DEBUG] Creating panels for ", length(group_vars), " variables...\n")
  cat("[DEBUG] Variables: ", paste(group_vars, collapse = ", "), "\n")

  panels <- list()
  for (i in seq_along(group_vars)) {
    var <- group_vars[i]
    cat("[DEBUG] Processing variable ", i, "/", length(group_vars), ": ", var, "\n")

    panel <- tryCatch({
      build_panel(var)
    }, error = function(e) {
      cat("[ERROR] Failed to create panel for '", var, "': ", e$message, "\n")
      return(NULL)
    })

    if (!is.null(panel) && inherits(panel, "ggplot")) {
      panels[[var]] <- panel
      cat("[DEBUG] Successfully created panel for '", var, "'\n")
    } else {
      cat("[WARNING] Panel for '", var, "' is NULL or not a ggplot object\n")
    }
  }

  # Filter out NULL panels (failed variables)
  valid_panels <- purrr::compact(panels)
  message("[DEBUG] Successfully created ", length(valid_panels), " panels out of ", length(panels))

  # Debug: Check each valid panel more thoroughly
  for (panel_name in names(valid_panels)) {
    panel <- valid_panels[[panel_name]]
    if (!is.null(panel)) {
      is_ggplot <- inherits(panel, "ggplot")
      message("[DEBUG] Panel '", panel_name, "' is valid ggplot object: ", is_ggplot)

      if (!is_ggplot) {
        message("[WARNING] Panel '", panel_name, "' is not a ggplot object, removing from list")
        valid_panels[[panel_name]] <- NULL
      } else {
        # Additional check: try to build the plot to ensure it's valid
        tryCatch({
          ggplot2::ggplot_build(panel)
          message("[DEBUG] Panel '", panel_name, "' builds successfully")
        }, error = function(e) {
          message("[WARNING] Panel '", panel_name, "' failed to build: ", e$message)
          valid_panels[[panel_name]] <- NULL
        })
      }
    }
  }

  # Re-compact the list after removing invalid panels
  valid_panels <- purrr::compact(valid_panels)

  if (length(valid_panels) == 0) {
    stop("No valid panels could be created for MST plot")
  }

  # Create legend with error handling
  legend_plot <- tryCatch({
    create_lineage_legend(sce, lineage_cols)
  }, error = function(e) {
    message("[WARNING] Failed to create lineage legend: ", e$message)
    # Create a simple placeholder legend
    ggplot2::ggplot() +
      ggplot2::geom_text(ggplot2::aes(x = 1, y = 1, label = "Legend unavailable"), size = 4) +
      ggplot2::theme_void() +
      ggplot2::labs(title = "Legend")
  })

  valid_panels[["Legend"]] <- legend_plot

  # Enhanced approach: create multiple meaningful visualizations
  cat("[DEBUG] Creating enhanced MST visualizations with ", length(valid_panels), " panels...\n")
  cat("[DEBUG] Panel names: ", paste(names(valid_panels), collapse = ", "), "\n")

  if (length(valid_panels) == 0) {
    stop("No valid panels created")
  }

  # Separate panels by type
  non_legend_panels <- valid_panels[names(valid_panels) != "Legend"]
  legend_panel <- valid_panels[["Legend"]]

  if (length(non_legend_panels) == 0) {
    message("[DEBUG] Only legend panel available, returning it")
    return(legend_panel)
  }

  # Prioritize important panels
  cell_type_panels <- non_legend_panels[grepl("leiden_scvi|cell_type|celltype|annotation",
                                             names(non_legend_panels), ignore.case = TRUE)]
  marker_panels <- non_legend_panels[!names(non_legend_panels) %in% names(cell_type_panels)]

  cat("[DEBUG] Cell type panels: ", length(cell_type_panels), " (", paste(names(cell_type_panels), collapse = ", "), ")\n")
  cat("[DEBUG] Marker panels: ", length(marker_panels), " (", paste(names(marker_panels), collapse = ", "), ")\n")

  # Create a comprehensive visualization with 2x2 or 3x2 layout
  selected_panels <- list()

  # Add the best cell type panel
  if (length(cell_type_panels) > 0) {
    selected_panels[["CellType"]] <- cell_type_panels[[1]] +
      ggplot2::labs(title = paste("Cell Types (", names(cell_type_panels)[1], ")"))
  }

  # Add top 3 marker panels
  if (length(marker_panels) > 0) {
    n_markers <- min(3, length(marker_panels))
    for (i in 1:n_markers) {
      marker_name <- names(marker_panels)[i]
      selected_panels[[paste0("Marker_", i)]] <- marker_panels[[i]] +
        ggplot2::labs(title = paste("Expression:", marker_name))
    }
  }

  # Add legend if available
  if (!is.null(legend_panel)) {
    selected_panels[["Legend"]] <- legend_panel
    cat("[DEBUG] Added Legend panel\n")
  }

  cat("[DEBUG] Selected ", length(selected_panels), " panels for final visualization\n")
  cat("[DEBUG] Selected panel names: ", paste(names(selected_panels), collapse = ", "), "\n")

  # Create combined visualization using proper patchwork approach
  if (length(selected_panels) == 1) {
    # Single panel - return directly
    cat("[DEBUG] Single panel - returning directly\n")
    return(selected_panels[[1]])

  } else if (length(selected_panels) <= 6) {
    # Try patchwork with proper error handling and debugging
    cat("[DEBUG] Attempting patchwork combination with ", length(selected_panels), " panels\n")

    # Load patchwork library
    if (!requireNamespace("patchwork", quietly = TRUE)) {
      cat("[ERROR] patchwork package not available, installing...\n")
      install.packages("patchwork", repos = "https://cran.r-project.org/")
    }

    tryCatch({
      # Verify all panels are ggplot objects
      for (name in names(selected_panels)) {
        if (!inherits(selected_panels[[name]], "ggplot")) {
          stop("Panel '", name, "' is not a ggplot object")
        }
        cat("[DEBUG] Verified panel '", name, "' is ggplot object\n")
      }

      # Load patchwork
      library(patchwork, quietly = TRUE)
      cat("[DEBUG] Patchwork library loaded successfully\n")

      # Use wrap_plots with proper parameters
      n_panels <- length(selected_panels)
      ncol_val <- min(2, n_panels)  # 2 columns max

      cat("[DEBUG] Using wrap_plots with ", n_panels, " panels, ncol = ", ncol_val, "\n")

      # Create the combined plot using wrap_plots
      plot_grid <- patchwork::wrap_plots(selected_panels, ncol = ncol_val)

      cat("[DEBUG] Successfully created ", n_panels, "-panel patchwork grid\n")

      # TEMPORARY FIX: Due to patchwork data frame comparison issue,
      # return the most important individual panel instead of combined plot
      cat("[DEBUG] Avoiding patchwork issue - returning primary CellType panel\n")

      if ("CellType" %in% names(selected_panels)) {
        primary_panel <- selected_panels[["CellType"]] +
          ggplot2::labs(subtitle = paste("Cell Types with MST Trajectory - Showing leiden_scvi clusters"))
        return(primary_panel)
      } else {
        return(selected_panels[[1]])
      }

    }, error = function(e) {
      cat("[ERROR] Patchwork combination failed: ", e$message, "\n")
      cat("[DEBUG] Error details: ", paste(capture.output(traceback()), collapse = "\n"), "\n")

      # Fallback strategy
      cat("[DEBUG] Using fallback strategy - returning primary panel\n")
      if ("CellType" %in% names(selected_panels)) {
        fallback_panel <- selected_panels[["CellType"]] +
          ggplot2::labs(subtitle = paste("Fallback view - patchwork failed with",
                                        length(selected_panels), "panels"))
        return(fallback_panel)
      } else {
        fallback_panel <- selected_panels[[1]] +
          ggplot2::labs(subtitle = paste("Fallback view - patchwork failed with",
                                        length(selected_panels), "panels"))
        return(fallback_panel)
      }
    })

  } else {
    # Too many panels for clean layout
    cat("[DEBUG] Too many panels (", length(selected_panels), "), returning primary panel\n")

    if ("CellType" %in% names(selected_panels)) {
      primary_panel <- selected_panels[["CellType"]] +
        ggplot2::labs(subtitle = paste("Primary view - showing cell types (",
                                      length(selected_panels), "panels available)"))
      return(primary_panel)
    } else {
      primary_panel <- selected_panels[[1]] +
        ggplot2::labs(subtitle = paste("Primary view (",
                                      length(selected_panels), "panels available)"))
      return(primary_panel)
    }
  }
}

# ───────────────────── 9. Main pipeline ────────────────────────────────────
run_pipeline <- function(sample_id,
                         h5ad_file,
                         out_dir,
                         progenitor      = c("SOX2", "NES", "HES1", "PAX6", "ASCL1"),
                         differentiation = c("MAP2", "DCX"),
                         marker_file     = "/home/yuyasato/work3/vhco_season2/meta/__markers.tsv",
                         resolution      = 0.5,
                         latent_dims     = 1:10,
                         use_cache       = FALSE) {

  load_libraries()

  # Output paths
  path_dist  <- fs::path(out_dir, "dist",  sample_id)
  path_fig   <- fs::path(out_dir, "figs",  sample_id)
  path_cache <- fs::path(out_dir, "cache", sample_id)
  walk(list(path_dist, path_fig, path_cache), dir.create,
       recursive = TRUE, showWarnings = FALSE)

  cache_seu <- fs::path(path_cache, "seurat.rds")
  cache_sce <- fs::path(path_cache, "sce.rds")

  # ── 1. Seurat object ──────────────────────────────────────────────────
  seurat <- if (use_cache && file.exists(cache_seu)) {
              message("[INFO] Reusing cached Seurat → ", cache_seu)
              readRDS(cache_seu)
            } else {
              read_inputs(h5ad_file,
                          progenitor,
                          differentiation,
                          marker_file) |>
              preprocess_seurat_latent(latent_dims = latent_dims,
                                       resolution  = resolution) |>
              score_cell_cycle()
            }

  saveRDS(seurat, cache_seu)

  # ── 2. Root cluster ───────────────────────────────────────────────────
  root_info <- select_root_cluster(seurat,
                                   progenitor,
                                   differentiation)

  # ── 3. Slingshot ──────────────────────────────────────────────────────
  # Detect the latent reduction name
  latent_reduction_name <- NULL
  if ("latent" %in% names(root_info$seurat@reductions)) {
    latent_reduction_name <- "latent"
  } else if ("scvi" %in% names(root_info$seurat@reductions)) {
    latent_reduction_name <- "scvi"
  } else if ("X_scvi" %in% names(root_info$seurat@reductions)) {
    latent_reduction_name <- "X_scvi"
  } else {
    stop("No latent embedding found. Available reductions: ",
         paste(names(root_info$seurat@reductions), collapse = ", "))
  }
  message("[DEBUG] Using latent reduction for slingshot: ", latent_reduction_name)

  sce <- if (use_cache && file.exists(cache_sce)) {
           message("[INFO] Reusing cached SCE → ", cache_sce)
           readRDS(cache_sce)
         } else {
           message("[INFO] Running slingshot trajectory analysis...")
           tryCatch({
             result <- run_slingshot_latent(root_info$seurat,
                                          root_info$start_cluster,
                                          latent_dims = latent_dims,
                                          latent_reduction_name = latent_reduction_name)
             message("[DEBUG] Slingshot analysis completed successfully")
             result
           }, error = function(e) {
             message("[ERROR] Slingshot analysis failed: ", e$message)

             # Provide suggestions for common issues
             if (grepl("singular|condition number", e$message, ignore.case = TRUE)) {
               message("[SUGGESTION] Try one of the following:")
               message("  1. Increase clustering resolution (current: ", resolution, ")")
               message("  2. Use fewer latent dimensions")
               message("  3. Filter out very small clusters")
               message("  4. Check if your data has clear developmental trajectories")
             }

             stop("Slingshot trajectory analysis failed. See suggestions above.")
           })
         }

  # Save results with error handling
  tryCatch({
    saveRDS(sce, cache_sce)
    message("[DEBUG] SCE object cached successfully")
  }, error = function(e) {
    message("[WARNING] Failed to cache SCE object: ", e$message)
  })

  # ── 4. Plots & exports ────────────────────────────────────────────────
  tryCatch({
    message("[INFO] Creating basic plots...")
    plots <- make_plots(root_info$seurat,
                        root_info$score_table,
                        root_info$start_cluster)
    save_plots(plots, path_fig)
    message("[DEBUG] Basic plots saved successfully")
  }, error = function(e) {
    message("[ERROR] Failed to create basic plots: ", e$message)
    message("[WARNING] Continuing without basic plots...")
  })

  # Define plot variables with priority: cell types first, then ALL markers
  # Prioritize proper cell type annotations over clustering results
  potential_cell_type_vars <- c("cell_type_cluster_weighted", "cell_type_cluster", "cell_type", "celltype",
                               "predicted.celltype", "predicted_celltype",
                               "annotation", "cluster_annotation",
                               "leiden_scvi", "scpred_prediction")

  # Find which cell type variables actually exist in the data
  available_cell_type_vars <- potential_cell_type_vars[
    potential_cell_type_vars %in% c(colnames(root_info$seurat@meta.data),
                                   colnames(SingleCellExperiment::colData(sce)))
  ]

  # Get marker genes that exist in the dataset - USE ALL MARKERS
  all_marker_genes <- readr::read_tsv(marker_file, show_col_types = FALSE)$gene |>
                      intersect(rownames(root_info$seurat))

  # Use ALL available marker genes for comprehensive visualization
  selected_marker_genes <- all_marker_genes

  message("[DEBUG] Found ", length(all_marker_genes), " marker genes in dataset for main pipeline")

  # Combine with priority: cell types first, then selected markers
  plot_vars <- c(available_cell_type_vars, selected_marker_genes)

  message("[DEBUG] Available cell type variables: ",
          if(length(available_cell_type_vars) > 0)
            paste(available_cell_type_vars, collapse = ", ")
          else "none found")
  message("[DEBUG] Selected marker genes (", length(selected_marker_genes), "): ",
          paste(selected_marker_genes, collapse = ", "))

  # No limit on plot variables - create separate plots for ALL markers
  message("[INFO] Will create separate plots for ALL ", length(selected_marker_genes), " marker genes")

  # Create separate MST plots instead of combined plot
  message("[INFO] Creating separate MST plots for clusters, cell types, and markers...")

  tryCatch({
    plots_created <- create_separate_mst_plots(sce,
                                              root_info$seurat,
                                              output_dir = path_fig)

    if (plots_created > 0) {
      message("[INFO] Successfully created ", plots_created, " separate MST plots")
      message("[INFO] Available plots:")
      message("  - mst_clusters.png (cluster visualization)")
      message("  - mst_celltypes.png (cell type visualization)")
      message("  - markers/ directory (individual marker gene plots)")
    } else {
      message("[WARNING] No MST plots were created successfully")
    }

  }, error = function(e) {
    message("[ERROR] Failed to create separate MST plots: ", e$message)

    # Fallback: try to create at least one plot with the old method
    message("[DEBUG] Attempting fallback with single combined plot...")

    # Try with just the first few variables for fallback
    reduced_vars <- head(plot_vars, 3)
    fallback_plot <- tryCatch({
      plotSlingshotMST_latent(sce,
                              root_info$seurat,
                              group_vars = reduced_vars,
                              ncol_panels = 1)
    }, error = function(e2) {
      message("[ERROR] Fallback MST plot also failed: ", e2$message)
      return(NULL)
    })

    if (!is.null(fallback_plot)) {
      tryCatch({
        ggplot2::ggsave(fs::path(path_fig, "mst_fallback.png"),
                        plot = fallback_plot,
                        width = 20,
                        height = 18,
                        units = "cm",
                        dpi = 300)
        message("[INFO] Saved fallback MST plot as mst_fallback.png")
      }, error = function(e3) {
        message("[ERROR] Failed to save fallback MST plot: ", e3$message)
        message("[WARNING] No MST plots will be available in results")
      })
    }
  })

  # Export results with error handling
  tryCatch({
    message("[INFO] Exporting pseudotime data...")
    export_pseudotime(sce,
                      file_path = fs::path(path_dist, "pseudotime.tsv"))
    message("[DEBUG] Pseudotime export completed")
  }, error = function(e) {
    message("[ERROR] Failed to export pseudotime: ", e$message)
  })

  tryCatch({
    message("[INFO] Exporting lineage-celltype mapping...")
    export_lineage_celltypes(sce,
                             file_path = fs::path(path_dist,
                                                  "lineage_celltypes.json"))
    message("[DEBUG] Lineage-celltype export completed")
  }, error = function(e) {
    message("[ERROR] Failed to export lineage-celltypes: ", e$message)
  })

  message("[INFO] Pipeline completed for sample: ", sample_id)
  message("[INFO] Results directory: ", fs::path_abs(path_dist))
  message("[INFO] Figures directory: ", fs::path_abs(path_fig))
  invisible(list(seurat = seurat, sce = sce))
}

# ───────────────────── Main Execution (Command Line Interface) ─────────────
if (!interactive()) {
  # Parse command line arguments
  args <- commandArgs(trailingOnly = TRUE)

  # Default values
  sample_id <- NULL
  h5ad_file <- NULL
  out_dir <- NULL
  resolution <- 0.5
  latent_dims <- 1:10
  cell_cycle_tsv <- "/home/yuyasato/work3/vhco_season2/meta/__cell_cycle_markers.tsv"
  root_marker_tsv <- "/home/yuyasato/work3/vhco_season2/meta/__root_markers.tsv"
  canonical_marker_tsv <- "/home/yuyasato/work3/vhco_season2/meta/__markers.tsv"
  force_rerun <- FALSE

  # Parse arguments
  i <- 1
  while (i <= length(args)) {
    if (args[i] == "--sample_id") {
      sample_id <- args[i + 1]
      i <- i + 2
    } else if (args[i] == "--h5ad_file") {
      h5ad_file <- args[i + 1]
      i <- i + 2
    } else if (args[i] == "--out_dir") {
      out_dir <- args[i + 1]
      i <- i + 2
    } else if (args[i] == "--resolution") {
      resolution <- as.numeric(args[i + 1])
      i <- i + 2
    } else if (args[i] == "--latent_dims") {
      # Parse R-style range like "1:10"
      latent_range <- args[i + 1]
      if (grepl(":", latent_range)) {
        parts <- strsplit(latent_range, ":")[[1]]
        latent_dims <- as.numeric(parts[1]):as.numeric(parts[2])
      } else {
        latent_dims <- as.numeric(strsplit(latent_range, ",")[[1]])
      }
      i <- i + 2
    } else if (args[i] == "--cell_cycle_tsv") {
      cell_cycle_tsv <- args[i + 1]
      i <- i + 2
    } else if (args[i] == "--root_marker_tsv") {
      root_marker_tsv <- args[i + 1]
      i <- i + 2
    } else if (args[i] == "--canonical_marker_tsv") {
      canonical_marker_tsv <- args[i + 1]
      i <- i + 2
    } else if (args[i] == "--force_rerun") {
      force_rerun <- toupper(args[i + 1]) == "TRUE"
      i <- i + 2
    } else {
      i <- i + 1
    }
  }

  # Validate required arguments
  if (is.null(sample_id) || is.null(h5ad_file) || is.null(out_dir)) {
    cat("Usage: Rscript slingshot.R --sample_id SAMPLE --h5ad_file FILE --out_dir DIR [OPTIONS]\n")
    cat("Required arguments:\n")
    cat("  --sample_id SAMPLE           Sample identifier\n")
    cat("  --h5ad_file FILE             Path to input H5AD file\n")
    cat("  --out_dir DIR                Output directory\n")
    cat("Optional arguments:\n")
    cat("  --resolution FLOAT           Clustering resolution (default: 0.5)\n")
    cat("  --latent_dims RANGE          Latent dimensions range (default: 1:10)\n")
    cat("  --cell_cycle_tsv FILE        Cell cycle markers file\n")
    cat("  --root_marker_tsv FILE       Root markers file\n")
    cat("  --canonical_marker_tsv FILE  Canonical markers file\n")
    cat("  --force_rerun TRUE/FALSE     Force rerun (default: FALSE)\n")
    quit(status = 1)
  }

  # Run the pipeline
  tryCatch({
    run_pipeline(
      sample_id = sample_id,
      h5ad_file = h5ad_file,
      out_dir = out_dir,
      marker_file = canonical_marker_tsv,
      resolution = resolution,
      latent_dims = latent_dims,
      use_cache = !force_rerun
    )
    cat("Pipeline completed successfully for sample:", sample_id, "\n")
  }, error = function(e) {
    cat("Pipeline failed:", e$message, "\n")
    quit(status = 1)
  })
}
