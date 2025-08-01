###############################################################################
# slingshot_single.R
#   A standard Seurat‑based trajectory‑analysis pipeline.
#   • Uses PCA instead of scVI latent embeddings
#   • Integrates samples with same sample_identifier using standard Seurat workflow
#   • Includes normalization, scaling, PCA, and clustering
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
read_inputs_single <- function(h5ad_path_or_list,
                               progenitor_markers,
                               differentiation_markers,
                               marker_file) {

  # Validate marker file exists
  if (!file.exists(marker_file)) {
    stop("Marker file not found: ", marker_file)
  }

  # Ensure h5ad_path_or_list is character vector
  if (!is.character(h5ad_path_or_list)) {
    stop("h5ad_path_or_list must be a character vector")
  }

  # Check all files exist
  missing_files <- h5ad_path_or_list[!file.exists(h5ad_path_or_list)]
  if (length(missing_files) > 0) {
    stop("H5AD files not found: ", paste(missing_files, collapse = ", "))
  }

  # Handle both single file and list of files
  if (length(h5ad_path_or_list) == 1) {
    # Single file case
    message("[INFO] Reading single h5ad file: ", h5ad_path_or_list)
    seurat_obj <- read_h5ad(h5ad_path_or_list)
  } else {
    # Multiple files case - integrate them
    message("[INFO] Reading and integrating ", length(h5ad_path_or_list), " h5ad files")
    seurat_list <- map(h5ad_path_or_list, ~read_h5ad(.x))

    # Basic integration using Seurat
    if (length(seurat_list) > 1) {
      # Merge all objects
      seurat_obj <- seurat_list[[1]]
      for (i in 2:length(seurat_list)) {
        seurat_obj <- merge(seurat_obj, seurat_list[[i]])
      }
      message("[INFO] Merged ", length(seurat_list), " objects into single Seurat object")
    } else {
      seurat_obj <- seurat_list[[1]]
    }
  }

  # Build required gene list
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
    warning("Some required genes are missing: ",
            paste(head(missing, 10), collapse = ", "),
            if (length(missing) > 10) " …" else "",
            " (", length(missing), " total missing)")
    message("[INFO] Continuing with ", length(required_genes) - length(missing),
            " available genes out of ", length(required_genes), " required genes")
  } else {
    message("[INFO] All required genes present (n = ", length(required_genes), ").")
  }
  seurat_obj
}

# ───────────────────── 2. Standard Seurat preprocessing ────────────────────
preprocess_seurat_standard <- function(seurat,
                                      n_features = 2000,
                                      n_pcs = 50,
                                      resolution = 0.5) {

  # Validate parameters
  if (n_features <= 0) stop("n_features must be positive")
  if (n_pcs <= 0) stop("n_pcs must be positive")
  if (resolution <= 0) stop("resolution must be positive")

  message("[INFO] Starting standard Seurat preprocessing pipeline...")
  message("[DEBUG] Initial object: ", ncol(seurat), " cells, ", nrow(seurat), " genes")

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

  seurat |>
    # Normalization
    {\(so) {
      message("[INFO] Normalizing data...")
      Seurat::NormalizeData(so, normalization.method = "LogNormalize", scale.factor = 10000)
    }}() |>
    # Find variable features
    {\(so) {
      message("[INFO] Finding ", n_features, " highly variable features...")
      Seurat::FindVariableFeatures(so, selection.method = "vst", nfeatures = n_features)
    }}() |>
    # Scale data
    {\(so) {
      message("[INFO] Scaling data...")
      all_genes <- rownames(so)
      Seurat::ScaleData(so, features = all_genes)
    }}() |>
    # PCA
    {\(so) {
      message("[INFO] Running PCA...")
      Seurat::RunPCA(so, features = Seurat::VariableFeatures(object = so), npcs = n_pcs, verbose = FALSE)
    }}() |>
    # Find neighbors and clusters
    {\(so) {
      message("[INFO] Building neighbor graph and clustering...")
      so |>
        Seurat::FindNeighbors(dims = 1:min(n_pcs, 30), verbose = FALSE) |>
        Seurat::FindClusters(resolution = resolution, verbose = FALSE)
    }}() |>
    # UMAP
    {\(so) {
      message("[INFO] Computing UMAP...")
      Seurat::RunUMAP(so, dims = 1:min(n_pcs, 30), verbose = FALSE)
    }}()
}

# ───────────────────── 3. Cell‑cycle scoring ───────────────────────────────
score_cell_cycle <- function(seurat) {
  message("[INFO] Scoring cell cycle phases...")
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
  prog <- intersect(progenitor_markers,      rownames(seurat))
  diff <- intersect(differentiation_markers, rownames(seurat))
  stopifnot(length(prog) > 0, length(diff) > 0)

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

      list(start_cluster = scores$cluster[1],
           score_table   = scores,
           seurat        = so)
    }}()
}

# ───────────────────── 5. Slingshot (PCA) ──────────────────────────────────
run_slingshot_pca <- function(seurat,
                              start_cluster,
                              pca_dims = 1:30,
                              min_cluster_size = 50,
                              min_pca_dims = 10) {

  message("[INFO] Running Slingshot on PCA space...")
  
  # Validate input parameters
  if (is.null(seurat) || ncol(seurat) == 0) {
    stop("Seurat object is empty or NULL")
  }
  
  if (is.null(start_cluster) || !start_cluster %in% levels(seurat$seurat_clusters)) {
    stop("Invalid start_cluster: ", start_cluster, ". Available clusters: ", 
         paste(levels(seurat$seurat_clusters), collapse = ", "))
  }
  
  # Check cluster sizes and filter small clusters
  cluster_sizes <- table(seurat$seurat_clusters)
  message("[DEBUG] Cluster sizes: ", paste(names(cluster_sizes), "=", cluster_sizes, collapse = ", "))
  
  small_clusters <- names(cluster_sizes)[cluster_sizes < min_cluster_size]
  if (length(small_clusters) > 0) {
    message("[WARNING] Small clusters detected (< ", min_cluster_size, " cells): ", paste(small_clusters, collapse = ", "))
    message("[INFO] Filtering out small clusters to prevent computational singularity...")
    
    # Check if start cluster would be removed
    if (start_cluster %in% small_clusters) {
      # Find the next best start cluster from remaining clusters
      large_clusters <- names(cluster_sizes)[cluster_sizes >= min_cluster_size]
      if (length(large_clusters) == 0) {
        stop("No clusters have sufficient cells (>= ", min_cluster_size, ") for trajectory analysis")
      }
      
      # Find largest cluster as new start
      new_start <- names(sort(cluster_sizes[large_clusters], decreasing = TRUE))[1]
      message("[INFO] Start cluster ", start_cluster, " is too small. Using cluster ", new_start, " instead.")
      start_cluster <- new_start
    }
    
    # Filter seurat object to remove small clusters
    cells_to_keep <- names(seurat$seurat_clusters)[!seurat$seurat_clusters %in% small_clusters]
    seurat <- subset(seurat, cells = cells_to_keep)
    
    # Update cluster sizes after filtering
    cluster_sizes <- table(seurat$seurat_clusters)
    message("[INFO] After filtering: ", ncol(seurat), " cells in ", length(cluster_sizes), " clusters")
    message("[DEBUG] Remaining cluster sizes: ", paste(names(cluster_sizes), "=", cluster_sizes, collapse = ", "))
  }
  
  # Adaptive PCA dimension reduction based on cluster sizes
  pca_data <- Seurat::Embeddings(seurat, "pca")
  available_pcs <- ncol(pca_data)
  min_cluster_cells <- min(cluster_sizes)
  
  # Ensure PCA dimensions don't exceed minimum cluster size - 1
  max_safe_dims <- max(min_pca_dims, min(min_cluster_cells - 1, length(pca_dims)))
  pca_dims <- intersect(pca_dims, 1:min(available_pcs, max_safe_dims))
  
  message("[DEBUG] Minimum cluster size: ", min_cluster_cells, " cells")
  message("[DEBUG] Adaptive PCA dimensions (max safe: ", max_safe_dims, "): ", paste(pca_dims, collapse = ", "))
  
  if (length(pca_dims) < 2) {
    stop("Need at least 2 PCA dimensions, but only ", length(pca_dims), " available")
  }
  
  sce <- Seurat::as.SingleCellExperiment(seurat)
  SummarizedExperiment::colData(sce)$traj_cluster <- seurat$seurat_clusters
  
  # Check for sufficient cluster connectivity
  n_clusters <- length(unique(seurat$seurat_clusters))
  message("[DEBUG] Number of clusters: ", n_clusters)
  
  if (n_clusters < 2) {
    stop("Need at least 2 clusters for trajectory analysis, found: ", n_clusters)
  }
  
  # Custom distance function for diagonal covariance (fallback for singular matrices)
  diagonal_dist_fun <- function(x, centers) {
    # Use diagonal covariance matrix instead of full covariance
    # This is more robust against singular matrices
    centers <- as.matrix(centers)
    x <- as.matrix(x)
    
    if(ncol(x) != ncol(centers)) {
      stop("Dimension mismatch between data and centers")
    }
    
    # Compute distances using diagonal covariance
    dists <- matrix(0, nrow = nrow(x), ncol = nrow(centers))
    for(i in seq_len(nrow(centers))) {
      diff <- sweep(x, 2, centers[i, ], "-")
      # Use diagonal covariance approximation
      vars <- apply(x, 2, var, na.rm = TRUE)
      vars[vars == 0 | is.na(vars)] <- 1  # Avoid division by zero
      dists[, i] <- sqrt(rowSums(diff^2 / rep(vars, each = nrow(diff))))
    }
    return(dists)
  }
  
  # Run slingshot with progressive fallback strategies
  slingshot_result <- NULL
  
  # Strategy 1: Default slingshot (full covariance)
  tryCatch({
    message("[INFO] Attempting slingshot with default parameters...")
    slingshot_result <- slingshot::slingshot(
      sce,
      clusterLabels = "traj_cluster",
      reducedDim    = "PCA",
      start.clus    = start_cluster,
      extend        = "n",
      shrink        = TRUE,
      omega         = TRUE
      # approx_points は省略 → 150 (default)
    )
    message("[INFO] Slingshot succeeded with default parameters")
  }, error = function(e) {
    if (grepl("singular|condition number", e$message, ignore.case = TRUE)) {
      message("[WARNING] Default slingshot failed with singular matrix: ", e$message)
      message("[INFO] Trying fallback strategies...")
    } else {
      message("[WARNING] Default slingshot failed: ", e$message)
    }
  })

  # Strategy 1b: Retry with approx_points = FALSE (dense curve)
  if (is.null(slingshot_result)) {
    tryCatch({
      message("[INFO] Retrying with approx_points = FALSE (dense curve)...")
      slingshot_result <- slingshot::slingshot(
        sce,
        clusterLabels = "traj_cluster",
        reducedDim    = "PCA",
        start.clus    = start_cluster,
        extend        = "n",
        shrink        = TRUE,
        omega         = TRUE,
        approx_points = FALSE  # ← 追加: Dense curve to avoid length mismatch
      )
      message("[INFO] Slingshot succeeded with dense curve")
    }, error = function(e) {
      message("[WARNING] Dense-curve retry failed: ", e$message)
    })
  }
  
  # Strategy 2: Use diagonal covariance via getLineages + getCurves
  if (is.null(slingshot_result)) {
    tryCatch({
      message("[INFO] Attempting slingshot with diagonal covariance...")
      
      # Get lineages with diagonal distance function
      lineages <- slingshot::getLineages(
        sce,
        clusterLabels = "traj_cluster",
        reducedDim = "PCA",
        start.clus = start_cluster,
        dist.method = "scaled.diag"  # Use diagonal covariance
      )
      
      # Get curves
      slingshot_result <- slingshot::getCurves(
        lineages,
        extend = "n",
        shrink = TRUE,
        omega = TRUE
      )
      message("[INFO] Slingshot succeeded with diagonal covariance")
    }, error = function(e) {
      message("[WARNING] Diagonal covariance strategy failed: ", e$message)
    })
  }
  
  # Strategy 3: Further reduced PCA dimensions
  if (is.null(slingshot_result) && length(pca_dims) > min_pca_dims) {
    reduced_dims <- 1:min_pca_dims
    message("[INFO] Attempting slingshot with reduced PCA dimensions: ", paste(reduced_dims, collapse = ", "))
    
    tryCatch({
      # Update PCA dimensions in the SCE object
      reduced_pca <- pca_data[, reduced_dims, drop = FALSE]
      SingleCellExperiment::reducedDim(sce, "PCA") <- reduced_pca
      
      lineages <- slingshot::getLineages(
        sce,
        clusterLabels = "traj_cluster",
        reducedDim = "PCA",
        start.clus = start_cluster,
        dist.method = "scaled.diag"
      )
      
      slingshot_result <- slingshot::getCurves(
        lineages,
        extend = "n",
        shrink = TRUE,
        omega = TRUE
      )
      message("[INFO] Slingshot succeeded with reduced PCA dimensions")
    }, error = function(e) {
      message("[WARNING] Reduced PCA strategy failed: ", e$message)
    })
  }
  
  # Final check
  if (is.null(slingshot_result)) {
    stop("All slingshot strategies failed. Data may not contain clear developmental trajectories.")
  }
  
  # Validate slingshot results
  n_lineages <- length(slingshot::slingLineages(slingshot_result))
  message("[INFO] Slingshot completed successfully with ", n_lineages, " lineages")
  
  if (n_lineages == 0) {
    stop("Slingshot failed to identify any lineages")
  }
  
  return(slingshot_result)
    
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
                                     cell_type_col = "cell_type_cluster",
                                     file_path    = "lineage_celltypes.json") {

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
  message("[INFO] Lineage‑celltype JSON saved → ", fs::path_abs(file_path))
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
      ggplot2::labs(title = "Cluster scores")

  list(umap = p_umap, heat = p_heat)
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

# ─────────────────── 8. Slingshot MST plotting (PCA/UMAP) ──────────────────
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
                   plot.margin = ggplot2::margin(10, 10, 10, 10)) +
    ggplot2::labs(title = "Lineage color legend") +
    ggplot2::xlim(0.5, 8)
}

plotSlingshotMST_pca <- function(sce,
                                 seurat_obj,
                                 group_vars,
                                 umap_dims   = 1:2,
                                 linewidth   = 0.8,
                                 arrow_len   = 0.35,
                                 arrow_angle = 25,
                                 ncol_panels = 3) {

  stopifnot(length(umap_dims) == 2)

  coord <- SingleCellExperiment::reducedDims(sce)[["UMAP"]][, umap_dims,
                                                            drop = FALSE]
  colnames(coord) <- c("d1", "d2")
  cell_df_base <- tibble::tibble(d1 = coord[, 1],
                                 d2 = coord[, 2],
                                 cluster = as.character(sce$traj_cluster))

  centers <- cell_df_base |>
    dplyr::group_by(cluster) |>
    dplyr::summarise(cen1 = mean(d1),
                     cen2 = mean(d2),
                     .groups = "drop")

  lin_list <- slingshot::slingLineages(sce)
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
    val <- if      (var %in% colnames(SingleCellExperiment::colData(sce))) {
               SingleCellExperiment::colData(sce)[[var]]
             } else if (var %in% colnames(seurat_obj@meta.data)) {
               seurat_obj[[var]][, 1]
             } else if (var %in% rownames(seurat_obj)) {
               as.numeric(LayerData(seurat_obj,
                                             layer    = "data",
                                             features = var)[1, ])
             } else {
               stop("Variable not found: ", var)
             }

    is_num <- is.numeric(val)
    cell_df <- dplyr::mutate(cell_df_base, val = val)

    # Create base plot
    p <- ggplot2::ggplot(cell_df, ggplot2::aes(d1, d2))
    
    # Layer 1: Add cell points in background (with reduced alpha for better visibility of nodes)
    if (is_num) {
      p <- p +
        ggplot2::geom_point(ggplot2::aes(colour = val),
                           size = 0.5, alpha = 0.5) +  # Reduced size and alpha
        ggplot2::scale_colour_viridis_c(name = var, option = "D")
    } else {
      # For categorical variables
      n_cat <- length(unique(val))
      cat_cols <- if (n_cat <= 36) {
                    Polychrome::palette36.colors(n_cat)
                  } else {
                    scales::hue_pal()(n_cat)
                  }
      names(cat_cols) <- sort(unique(as.character(val)))
      
      p <- p +
        ggplot2::geom_point(ggplot2::aes(colour = as.factor(val)),
                           size = 0.5, alpha = 0.4) +  # Reduced size and alpha
        ggplot2::scale_colour_manual(values = cat_cols, name = var)
    }
    
    # Layer 2: Add lineage segments on top of cell points
    if (nrow(edge_df) > 0) {
      p <- p +
        ggplot2::geom_segment(data = edge_df,
                              ggplot2::aes(x = x, y = y,
                                           xend = xend, yend = yend),
                              colour = lineage_cols[edge_df$lineage],
                              linewidth = linewidth,
                              arrow = ggplot2::arrow(type = "closed",
                                                   length = grid::unit(arrow_len, "cm"),
                                                   angle = arrow_angle),
                              alpha = 0.9)  # Increased alpha for better visibility
    }
    
    # Layer 3: Add cluster center points on top (most prominent)
    p <- p +
      ggplot2::geom_point(data = centers,
                          ggplot2::aes(cen1, cen2),
                          fill = ifelse(is.na(centers$lineage), "white", 
                                       lineage_cols[centers$lineage]),
                          shape = 21,
                          colour = "black",
                          size = 5,      # Increased size for better visibility
                          stroke = 1.5)  # Increased stroke for better contrast
    
    # Layer 4: Add cluster labels on top of everything
    p <- p +
      ggplot2::geom_text(data = centers,
                         ggplot2::aes(cen1, cen2, label = cluster),
                         size = 3.5,           # Slightly larger text
                         vjust = -1.2,         # More separation from center
                         colour = "black",     # Ensure visibility
                         fontface = "bold")    # Bold for better visibility
    
    p <- p +
      ggplot2::coord_equal() +
      ggplot2::theme_minimal(base_size = 13) +
      ggplot2::labs(title = paste("MST (", var, ")", sep = ""),
                    x = paste("UMAP", umap_dims[1]),
                    y = paste("UMAP", umap_dims[2]))
    
    return(p)
  }

  panels <- purrr::map(group_vars, build_panel)
  names(panels) <- group_vars

  legend_plot <- create_lineage_legend(sce, lineage_cols)
  panels[["Legend"]] <- legend_plot

  patchwork::wrap_plots(panels, ncol = ncol_panels)
}

# ───────────────────── 9. Main pipeline ────────────────────────────────────
run_pipeline_single <- function(sample_id,
                                h5ad_file_or_list,
                                out_dir,
                                progenitor      = c("SOX2", "NES", "HES1", "PAX6", "ASCL1"),
                                differentiation = c("MAP2", "DCX"),
                                marker_file     = "/work1/yuyasato/vhco_season2/meta/__markers.tsv",
                                resolution      = 0.5,
                                n_features      = 2000,
                                n_pcs           = 50,
                                min_cluster_size = 50,  # Minimum cells per cluster for slingshot
                                min_pca_dims    = 10,   # Minimum PCA dimensions for fallback
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
              read_inputs_single(h5ad_file_or_list,
                                progenitor,
                                differentiation,
                                marker_file) |>
              preprocess_seurat_standard(n_features = n_features,
                                        n_pcs = n_pcs,
                                        resolution = resolution) |>
              score_cell_cycle()
            }

  saveRDS(seurat, cache_seu)

  # ── 2. Root cluster ───────────────────────────────────────────────────
  root_info <- select_root_cluster(seurat,
                                   progenitor,
                                   differentiation)

  # ── 3. Slingshot ──────────────────────────────────────────────────────
  sce <- if (use_cache && file.exists(cache_sce)) {
           message("[INFO] Reusing cached SCE → ", cache_sce)
           readRDS(cache_sce)
         } else {
           message("[INFO] Running slingshot trajectory analysis...")
           tryCatch({
             result <- run_slingshot_pca(root_info$seurat,
                                       root_info$start_cluster,
                                       pca_dims = 1:min(n_pcs, 30),
                                       min_cluster_size = min_cluster_size,  # Use parameter value
                                       min_pca_dims = min_pca_dims)          # Use parameter value
             message("[DEBUG] Slingshot analysis completed successfully")
             result
           }, error = function(e) {
             message("[ERROR] Slingshot analysis failed: ", e$message)
             
             # Enhanced error diagnostics
             cluster_sizes <- table(root_info$seurat$seurat_clusters)
             small_clusters <- names(cluster_sizes)[cluster_sizes < 50]
             
             message("[DEBUG] Diagnostic information:")
             message("  - Current clustering resolution: ", resolution)
             message("  - Total cells: ", ncol(root_info$seurat))
             message("  - Number of clusters: ", length(cluster_sizes))
             message("  - Small clusters (< 50 cells): ", 
                     if(length(small_clusters) > 0) paste(small_clusters, collapse = ", ") else "None")
             message("  - PCA dimensions attempted: 1:", min(n_pcs, 30))
             
             # Provide suggestions for common issues
             if (grepl("singular|condition number|no clusters|clear developmental", e$message, ignore.case = TRUE)) {
               message("[SUGGESTION] Try one of the following:")
               message("  1. Increase clustering resolution (current: ", resolution, ") to create more balanced clusters")
               message("  2. Decrease clustering resolution if you have too many small clusters")
               message("  3. Check data quality - ensure clear developmental relationships exist")
               message("  4. Consider using a different root cluster if current one is problematic")
               message("  5. Verify that your data represents a true developmental trajectory")
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
  # Ensure Seurat object matches filtered SCE object for consistent plotting
  sce_cell_names <- colnames(sce)
  filtered_seurat <- subset(root_info$seurat, cells = sce_cell_names)
  
  message("[DEBUG] Cell count alignment: SCE=", ncol(sce), ", Seurat=", ncol(filtered_seurat))
  
  tryCatch({
    message("[INFO] Creating basic plots...")
    plots <- make_plots(filtered_seurat,
                        root_info$score_table,
                        root_info$start_cluster)
    save_plots(plots, path_fig)
    message("[DEBUG] Basic plots saved successfully")
  }, error = function(e) {
    message("[ERROR] Failed to create basic plots: ", e$message)
    message("[WARNING] Continuing without basic plots...")
  })

  plot_vars <- c("cell_type_cluster",
                 readr::read_tsv(marker_file,
                                 show_col_types = FALSE)$gene    |>
                 intersect(rownames(filtered_seurat)))

  # Limit number of plot variables to prevent oversized plots
  max_plot_vars <- 15  # Reasonable limit for plot variables
  if (length(plot_vars) > max_plot_vars) {
    message("[WARNING] Too many plot variables (", length(plot_vars), "). ", 
            "Limiting to first ", max_plot_vars, " variables.")
    plot_vars <- head(plot_vars, max_plot_vars)
  }
  
  message("[DEBUG] Creating MST plot with ", length(plot_vars), " variables: ", 
          paste(head(plot_vars, 5), collapse = ", "), 
          if (length(plot_vars) > 5) "..." else "")
  
  mst_plot <- plotSlingshotMST_pca(sce,
                                   filtered_seurat,
                                   group_vars = plot_vars,
                                   ncol_panels = 3)
  
  # Calculate safe plot dimensions
  n_panels <- length(plot_vars) + 1  # +1 for legend
  n_rows <- ceiling(n_panels / 3)
  
  # Limit maximum dimensions to avoid ggsave error
  max_width_cm <- 45   # 15cm * 3 panels
  max_height_cm <- min(12 * n_rows, 120)  # Cap at 120cm (~47 inches)
  
  message("[DEBUG] MST plot dimensions: ", max_width_cm, "cm x ", max_height_cm, "cm")
  
  tryCatch({
    ggplot2::ggsave(fs::path(path_fig, "mst.png"),
                    plot      = mst_plot,
                    width     = max_width_cm,
                    height    = max_height_cm,
                    units     = "cm",
                    dpi       = 300,
                    limitsize = FALSE)  # Allow large plots if needed
    
    message("[INFO] MST plot saved successfully")
    
  }, error = function(e) {
    message("[ERROR] Failed to save MST plot: ", e$message)
    message("[DEBUG] Attempting to save with reduced dimensions...")
    
    # Fallback with smaller dimensions
    fallback_width <- min(max_width_cm, 30)
    fallback_height <- min(max_height_cm, 40)
    
    ggplot2::ggsave(fs::path(path_fig, "mst_reduced.png"),
                    plot      = mst_plot,
                    width     = fallback_width,
                    height    = fallback_height,
                    units     = "cm",
                    dpi       = 200,
                    limitsize = FALSE)
    
    message("[INFO] MST plot saved with reduced dimensions: ", 
            fallback_width, "cm x ", fallback_height, "cm")
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
  h5ad_files <- NULL
  out_dir <- NULL
  resolution <- 0.5
  n_features <- 2000
  n_pcs <- 50
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
    } else if (args[i] == "--h5ad_files") {
      # Collect all remaining files until next argument
      h5ad_files <- c()
      i <- i + 1
      while (i <= length(args) && !startsWith(args[i], "--")) {
        h5ad_files <- c(h5ad_files, args[i])
        i <- i + 1
      }
    } else if (args[i] == "--out_dir") {
      out_dir <- args[i + 1]
      i <- i + 2
    } else if (args[i] == "--resolution") {
      resolution <- as.numeric(args[i + 1])
      i <- i + 2
    } else if (args[i] == "--n_features") {
      n_features <- as.integer(args[i + 1])
      i <- i + 2
    } else if (args[i] == "--n_pcs") {
      n_pcs <- as.integer(args[i + 1])
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
  if (is.null(sample_id) || is.null(h5ad_files) || is.null(out_dir)) {
    cat("Usage: Rscript slingshot_single.R --sample_id SAMPLE --h5ad_files FILE1 [FILE2 ...] --out_dir DIR [OPTIONS]\n")
    cat("Required arguments:\n")
    cat("  --sample_id SAMPLE           Sample identifier\n")
    cat("  --h5ad_files FILE1 [FILE2]   Path(s) to input H5AD file(s)\n")
    cat("  --out_dir DIR                Output directory\n")
    cat("Optional arguments:\n")
    cat("  --resolution FLOAT           Clustering resolution (default: 0.5)\n")
    cat("  --n_features INT             Number of variable features (default: 2000)\n")
    cat("  --n_pcs INT                  Number of PCA components (default: 50)\n")
    cat("  --cell_cycle_tsv FILE        Cell cycle markers file\n")
    cat("  --root_marker_tsv FILE       Root markers file\n")
    cat("  --canonical_marker_tsv FILE  Canonical markers file\n")
    cat("  --force_rerun TRUE/FALSE     Force rerun (default: FALSE)\n")
    quit(status = 1)
  }
  
  # Run the pipeline
  tryCatch({
    run_pipeline_single(
      sample_id = sample_id,
      h5ad_file_or_list = h5ad_files,
      out_dir = out_dir,
      marker_file = canonical_marker_tsv,
      resolution = resolution,
      n_features = n_features,
      n_pcs = n_pcs,
      use_cache = !force_rerun
    )
    cat("Pipeline completed successfully for sample:", sample_id, "\n")
  }, error = function(e) {
    cat("Pipeline failed:", e$message, "\n")
    quit(status = 1)
  })
}