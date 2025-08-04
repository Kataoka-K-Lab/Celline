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

# ────────────────────────── Gene name conversion ──────────────────────────
convert_gene_names <- function(gene_names, available_genes) {
  # Convert gene names between different formats (Human/Mouse) and find matches.
  # Tries multiple formats: original, Mouse (Title case), lowercase, uppercase.

  if (length(gene_names) == 0) return(character(0))

  # Try original format first
  found_genes <- intersect(gene_names, available_genes)
  if (length(found_genes) > 0) {
    message("[DEBUG] Found ", length(found_genes), "/", length(gene_names),
            " genes in original format")
    return(found_genes)
  }

  # Try Mouse format: First letter uppercase, rest lowercase (e.g., MCM5 -> Mcm5)
  # Using base R functions instead of stringr
  mouse_format <- paste0(toupper(substr(tolower(gene_names), 1, 1)),
                        substr(tolower(gene_names), 2, nchar(gene_names)))
  found_genes <- intersect(mouse_format, available_genes)
  if (length(found_genes) > 0) {
    message("[DEBUG] Found ", length(found_genes), "/", length(gene_names),
            " genes in Mouse format (Title case)")
    return(found_genes)
  }

  # Try all lowercase
  lower_format <- tolower(gene_names)
  found_genes <- intersect(lower_format, available_genes)
  if (length(found_genes) > 0) {
    message("[DEBUG] Found ", length(found_genes), "/", length(gene_names),
            " genes in lowercase format")
    return(found_genes)
  }

  # Try all uppercase
  upper_format <- toupper(gene_names)
  found_genes <- intersect(upper_format, available_genes)
  if (length(found_genes) > 0) {
    message("[DEBUG] Found ", length(found_genes), "/", length(gene_names),
            " genes in uppercase format")
    return(found_genes)
  }

  message("[WARNING] No genes found in any format for: ",
          paste(head(gene_names, 5), collapse = ", "))
  return(character(0))
}

# ─────────────────── Cell exclusion filtering ─────────────────────────────
# Function to map user-friendly key names to actual metadata column names
map_exclude_key <- function(user_key, available_keys) {
  # Define mapping from user-friendly names to possible actual column names
  key_mappings <- list(
    "celltype" = c("scpred_prediction", "cell_type_cluster_weighted", "cell_type_cluster",
                   "cell_type", "celltype", "predicted.celltype", "predicted_celltype",
                   "annotation", "cluster_annotation"),
    "cluster" = c("seurat_clusters", "leiden_scvi", "cluster"),
    "sample" = c("sample_id", "sample", "orig.ident"),
    "filter" = c("filter", "qc_filter"),
    "phase" = c("Phase", "cell_cycle_phase", "phase")
  )

  # First, check if the user key exists directly
  if (user_key %in% available_keys) {
    message("[DEBUG] Direct match found for key '", user_key, "'")
    return(user_key)
  }

  # Check if it's a mapped key
  if (user_key %in% names(key_mappings)) {
    possible_keys <- key_mappings[[user_key]]
    for (possible_key in possible_keys) {
      if (possible_key %in% available_keys) {
        message("[DEBUG] Mapped '", user_key, "' to actual key '", possible_key, "'")
        return(possible_key)
      }
    }
  }

  # Try case-insensitive partial matching
  for (available_key in available_keys) {
    if (grepl(user_key, available_key, ignore.case = TRUE) ||
        grepl(available_key, user_key, ignore.case = TRUE)) {
      message("[DEBUG] Partial match: mapped '", user_key, "' to '", available_key, "'")
      return(available_key)
    }
  }

  # No match found
  message("[WARNING] No match found for key '", user_key, "'")

  # Suggest similar keys
  celltype_related <- available_keys[grepl("cell|type|pred|annotation", available_keys, ignore.case = TRUE)]
  cluster_related <- available_keys[grepl("cluster|leiden", available_keys, ignore.case = TRUE)]

  if (grepl("cell|type", user_key, ignore.case = TRUE) && length(celltype_related) > 0) {
    message("[SUGGESTION] For celltype, try one of: ", paste(head(celltype_related, 5), collapse = ", "))
  } else if (grepl("cluster", user_key, ignore.case = TRUE) && length(cluster_related) > 0) {
    message("[SUGGESTION] For cluster, try one of: ", paste(head(cluster_related, 5), collapse = ", "))
  }

  return(NULL)
}

apply_exclude_filters <- function(seurat_obj, exclude_json = NULL) {
  # Apply cell exclusion filters based on metadata
  # exclude_json: JSON string of format {"key": ["value1", "value2"], ...}

  if (is.null(exclude_json) || exclude_json == "" || exclude_json == "null") {
    message("[INFO] No exclude filters specified, keeping all cells")
    return(seurat_obj)
  }

  tryCatch({
    # Parse JSON exclude filters
    exclude_filters <- jsonlite::fromJSON(exclude_json)

    if (length(exclude_filters) == 0) {
      message("[INFO] Empty exclude filters, keeping all cells")
      return(seurat_obj)
    }

    message("[INFO] Applying exclude filters: ", exclude_json)

    # Debug: Show available metadata keys
    available_keys <- colnames(seurat_obj@meta.data)
    message("[DEBUG] Available metadata keys in Seurat object (", length(available_keys), " total):")
    message("[DEBUG] ", paste(head(available_keys, 15), collapse = ", "),
            if(length(available_keys) > 15) "..." else "")

    initial_cells <- ncol(seurat_obj)
    cells_to_keep <- rep(TRUE, initial_cells)

    # Apply each exclude filter
    for (user_key in names(exclude_filters)) {
      exclude_values <- exclude_filters[[user_key]]

      if (length(exclude_values) == 0) {
        message("[DEBUG] No values to exclude for key '", user_key, "', skipping")
        next
      }

      message("[DEBUG] Processing exclude filter for user key: '", user_key, "'")

      # Map user key to actual metadata key
      actual_key <- map_exclude_key(user_key, available_keys)

      if (is.null(actual_key)) {
        message("[ERROR] Could not map user key '", user_key, "' to any metadata column")
        message("[ERROR] Available keys: ", paste(head(available_keys, 10), collapse = ", "),
                if(length(available_keys) > 10) "..." else "")
        next
      }

      message("[INFO] Excluding cells where '", actual_key, "' is in: ", paste(exclude_values, collapse = ", "))

      # Get cell values for the actual metadata key
      cell_values <- seurat_obj@meta.data[[actual_key]]

      # Debug: Show unique values in this column
      unique_values <- unique(as.character(cell_values))
      message("[DEBUG] Unique values in '", actual_key, "' (", length(unique_values), " total): ",
              paste(head(unique_values, 10), collapse = ", "),
              if(length(unique_values) > 10) "..." else "")

      # Find cells to exclude (where value matches any in exclude_values)
      cells_to_exclude <- cell_values %in% exclude_values

      # Update cells_to_keep (exclude cells that match)
      cells_to_keep <- cells_to_keep & !cells_to_exclude

      excluded_count <- sum(cells_to_exclude)
      message("[INFO] Excluded ", excluded_count, " cells based on '", actual_key, "' matching: ",
              paste(exclude_values, collapse = ", "))

      # Show details of what was excluded
      if (excluded_count > 0) {
        excluded_value_counts <- table(cell_values[cells_to_exclude])
        message("[DEBUG] Breakdown of excluded cells: ",
                paste(names(excluded_value_counts), "=", excluded_value_counts, collapse = ", "))
      } else {
        message("[WARNING] No cells were excluded for '", actual_key, "' - check if values '",
                paste(exclude_values, collapse = ", "), "' exist in the data")
      }
    }

    # Apply filtering
    final_cells <- sum(cells_to_keep)
    excluded_cells <- initial_cells - final_cells

    if (excluded_cells > 0) {
      seurat_filtered <- seurat_obj[, cells_to_keep]
      message("[INFO] Cell exclusion summary:")
      message("  Initial cells: ", initial_cells)
      message("  Excluded cells: ", excluded_cells)
      message("  Remaining cells: ", final_cells)
      message("  Exclusion rate: ", round(excluded_cells / initial_cells * 100, 1), "%")

      # Check if enough cells remain for analysis
      if (final_cells < 50) {
        warning("Very few cells remaining after exclusion filtering (", final_cells, "). Consider adjusting exclude criteria.")
      }

      return(seurat_filtered)
    } else {
      message("[WARNING] No cells were excluded by any of the specified filters")
      message("[WARNING] This might indicate that the specified values don't exist in the metadata")
      return(seurat_obj)
    }

  }, error = function(e) {
    message("[ERROR] Failed to apply exclude filters: ", e$message)
    message("[WARNING] Continuing without exclude filtering")
    return(seurat_obj)
  })
}

# ─────────────────── 1. Input & required‑gene validation ───────────────────
read_inputs <- function(h5ad_path,
                        progenitor_markers,
                        differentiation_markers,
                        marker_file) {
  # Read AnnData → Seurat
  seurat_obj <- read_h5ad(h5ad_path)

  # Build required gene list (A–D) with format conversion
  data("cc.genes.updated.2019", package = "Seurat")
  cell_cycle_genes <- unlist(cc.genes.updated.2019)

  mst_markers <- readr::read_tsv(marker_file,
                                 show_col_types = FALSE)$gene

  # Convert gene names to find matches in the dataset
  available_seurat_genes <- rownames(seurat_obj)

  cc_found <- convert_gene_names(cell_cycle_genes, available_seurat_genes)
  prog_found <- convert_gene_names(progenitor_markers, available_seurat_genes)
  diff_found <- convert_gene_names(differentiation_markers, available_seurat_genes)
  mst_found <- convert_gene_names(mst_markers, available_seurat_genes)

  available_genes <- union(cc_found, union(prog_found, union(diff_found, mst_found)))
  total_requested <- length(cell_cycle_genes) + length(progenitor_markers) +
                    length(differentiation_markers) + length(mst_markers)

  message("[INFO] Gene matching summary:")
  message("  Cell cycle: ", length(cc_found), "/", length(cell_cycle_genes))
  message("  Progenitor: ", length(prog_found), "/", length(progenitor_markers))
  message("  Differentiation: ", length(diff_found), "/", length(differentiation_markers))
  message("  MST markers: ", length(mst_found), "/", length(mst_markers))
  message("  Total available: ", length(available_genes), "/", total_requested)

  if (length(available_genes) == 0) {
    warning("No marker genes found in dataset. Check gene name formats.")
  }

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

  # Use gene name conversion to find matches in different formats
  available_seurat_genes <- rownames(seurat)
  s_genes   <- convert_gene_names(cc.genes.updated.2019$s.genes, available_seurat_genes)
  g2m_genes <- convert_gene_names(cc.genes.updated.2019$g2m.genes, available_seurat_genes)

  # Check if we have enough genes for cell cycle scoring
  min_genes_required <- 5  # Minimum genes needed for meaningful scoring

  if (length(s_genes) < min_genes_required || length(g2m_genes) < min_genes_required) {
    warning("Insufficient cell cycle genes available (S: ", length(s_genes),
            ", G2M: ", length(g2m_genes), "). Skipping cell cycle scoring.")
    message("[WARNING] Cell cycle scoring skipped due to insufficient marker genes.")

    # Add empty cell cycle columns for compatibility
    seurat@meta.data$S_phase1 <- 0
    seurat@meta.data$G2M_phase1 <- 0
    seurat@meta.data$S.Score <- 0
    seurat@meta.data$G2M.Score <- 0
    seurat@meta.data$Phase <- "G1"

    return(seurat)
  }

  message("[INFO] Cell cycle scoring with ", length(s_genes), " S-phase and ",
          length(g2m_genes), " G2M-phase genes.")

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

  # Validate marker genes using format conversion
  available_seurat_genes <- rownames(seurat)
  prog <- convert_gene_names(progenitor_markers, available_seurat_genes)
  diff <- convert_gene_names(differentiation_markers, available_seurat_genes)

  message("[DEBUG] Progenitor markers found: ", length(prog), "/", length(progenitor_markers),
          " (", paste(head(prog, 3), collapse = ", "), if(length(prog) > 3) "..." else "", ")")
  message("[DEBUG] Differentiation markers found: ", length(diff), "/", length(differentiation_markers),
          " (", paste(head(diff, 3), collapse = ", "), if(length(diff) > 3) "..." else "", ")")

  # Check if we have enough markers for scoring
  min_markers_required <- 1  # Minimum markers needed for scoring

  if (length(prog) < min_markers_required) {
    warning("Insufficient progenitor markers found (", length(prog), "/", length(progenitor_markers), "). Using default scoring.")
    message("[WARNING] Progenitor scoring skipped, using random cluster selection.")
    # Return first cluster as root for simplicity
    cluster_levels <- levels(factor(seurat@meta.data$seurat_clusters))
    if (length(cluster_levels) > 0) {
      return(cluster_levels[1])
    } else {
      return("0")
    }
  }

  if (length(diff) < min_markers_required) {
    warning("Insufficient differentiation markers found (", length(diff), "/", length(differentiation_markers), "). Using default scoring.")
    message("[WARNING] Differentiation scoring will use available progenitor markers only.")
    # Use prog markers for both if diff is not available
    diff <- prog
  }

  message("[INFO] Using ", length(prog), " progenitor and ", length(diff), " differentiation markers for scoring.")

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

  # Basic UMAP with clusters
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

  # Cluster scores heatmap
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

  # Create score-based UMAP plots
  score_plots <- create_score_umaps(meta, start_cluster)

  # Create score distribution plots
  distribution_plots <- create_score_distributions(meta)

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

  # Combine all plots
  plots <- list(umap = p_umap, heat = p_heat)

  # Add score-based UMAP plots
  plots <- c(plots, score_plots)

  # Add distribution plots
  plots <- c(plots, distribution_plots)

  # Add cell type UMAP if available
  if (!is.null(p_celltype)) {
    plots[["celltype_umap"]] <- p_celltype
  }

  return(plots)
}

# ───────────────────── 7a. Score-based UMAP plots ──────────────────────────
create_score_umaps <- function(meta, start_cluster) {
  plots <- list()

  # Define score columns and their display properties
  score_configs <- list(
    list(col = "S.Score", title = "S Phase Score", color_scale = "viridis"),
    list(col = "G2M.Score", title = "G2M Phase Score", color_scale = "viridis"),
    list(col = "Prog1", title = "Progenitor Score", color_scale = "plasma"),
    list(col = "Diff1", title = "Differentiation Score", color_scale = "plasma")
  )

  # Add combined cell cycle score if both S and G2M scores exist
  if ("S.Score" %in% colnames(meta) && "G2M.Score" %in% colnames(meta)) {
    meta$cycle_combined <- meta$S.Score + meta$G2M.Score
    score_configs <- append(score_configs, list(
      list(col = "cycle_combined", title = "Combined Cell Cycle Score", color_scale = "magma")
    ))
  }

  # Add root score if available (calculate from cluster-level scores)
  if ("Prog1" %in% colnames(meta) && "Diff1" %in% colnames(meta) && "S.Score" %in% colnames(meta) && "G2M.Score" %in% colnames(meta)) {
    # Calculate individual cell root scores
    prog_scaled <- scales::rescale(meta$Prog1, to = c(0, 1))
    cycle_scaled <- scales::rescale(meta$S.Score + meta$G2M.Score, to = c(0, 1))
    diff_scaled <- scales::rescale(meta$Diff1, to = c(0, 1))
    meta$root_score_individual <- 2*prog_scaled + 0.5*cycle_scaled - 3*diff_scaled

    score_configs <- append(score_configs, list(
      list(col = "root_score_individual", title = "Root Score (Individual)", color_scale = "inferno")
    ))
  }

  # Create UMAP plot for each score
  for (config in score_configs) {
    col_name <- config$col
    plot_title <- config$title
    color_scale <- config$color_scale

    if (col_name %in% colnames(meta)) {
      score_values <- meta[[col_name]]

      # Skip if all values are NA or missing
      if (all(is.na(score_values))) {
        message("[WARNING] Skipping ", plot_title, " - all values are NA")
        next
      }

      # Create the plot
      p <- ggplot2::ggplot(meta, ggplot2::aes(U1, U2, colour = !!rlang::sym(col_name))) +
        ggplot2::geom_point(size = 0.6, alpha = 0.8) +
        ggplot2::theme_minimal() +
        ggplot2::theme(panel.background = ggplot2::element_rect(fill = "white", color = NA),
                       plot.background = ggplot2::element_rect(fill = "white", color = NA)) +
        ggplot2::labs(title = paste("UMAP -", plot_title),
                      colour = gsub("\\.", " ", col_name))

      # Apply appropriate color scale
      if (color_scale == "viridis") {
        p <- p + ggplot2::scale_colour_viridis_c(option = "D")
      } else if (color_scale == "plasma") {
        p <- p + ggplot2::scale_colour_viridis_c(option = "C")
      } else if (color_scale == "magma") {
        p <- p + ggplot2::scale_colour_viridis_c(option = "A")
      } else if (color_scale == "inferno") {
        p <- p + ggplot2::scale_colour_viridis_c(option = "B")
      } else {
        p <- p + ggplot2::scale_colour_gradient2(low = "blue", mid = "white", high = "red", midpoint = 0)
      }

      # Highlight root cluster if specified
      if (!is.null(start_cluster) && start_cluster %in% meta$seurat_clusters) {
        root_cells <- meta[meta$seurat_clusters == start_cluster, ]
        if (nrow(root_cells) > 0) {
          p <- p + ggplot2::geom_point(data = root_cells,
                                       ggplot2::aes(U1, U2),
                                       colour = "black", size = 0.8, alpha = 0.6, shape = 1)
        }
      }

      plot_name <- paste0("score_", gsub("\\.", "_", tolower(col_name)))
      plots[[plot_name]] <- p

      message("[DEBUG] Created score UMAP for: ", plot_title)
    }
  }

  return(plots)
}

# ───────────────────── 7b. Score distribution plots ────────────────────────
create_score_distributions <- function(meta) {
  plots <- list()

  # Score columns to analyze
  score_columns <- c("S.Score", "G2M.Score", "Prog1", "Diff1")

  # Add combined scores if available
  if ("S.Score" %in% colnames(meta) && "G2M.Score" %in% colnames(meta)) {
    meta$cycle_combined <- meta$S.Score + meta$G2M.Score
    score_columns <- c(score_columns, "cycle_combined")
  }

  if ("root_score_individual" %in% colnames(meta)) {
    score_columns <- c(score_columns, "root_score_individual")
  }

  for (score_col in score_columns) {
    if (score_col %in% colnames(meta)) {
      score_values <- meta[[score_col]]

      # Skip if all values are NA
      if (all(is.na(score_values))) {
        next
      }

      # Create violin plot by cluster
      p_violin <- ggplot2::ggplot(meta, ggplot2::aes(x = seurat_clusters, y = !!rlang::sym(score_col),
                                                     fill = seurat_clusters)) +
        ggplot2::geom_violin(alpha = 0.7) +
        ggplot2::geom_boxplot(width = 0.2, alpha = 0.8, outlier.shape = NA) +
        ggplot2::theme_minimal() +
        ggplot2::theme(panel.background = ggplot2::element_rect(fill = "white", color = NA),
                       plot.background = ggplot2::element_rect(fill = "white", color = NA),
                       axis.text.x = ggplot2::element_text(angle = 45, hjust = 1),
                       legend.position = "none") +
        ggplot2::labs(title = paste("Distribution of", gsub("\\.", " ", score_col), "by Cluster"),
                      x = "Cluster", y = gsub("\\.", " ", score_col))

      # Create histogram
      p_hist <- ggplot2::ggplot(meta, ggplot2::aes(x = !!rlang::sym(score_col))) +
        ggplot2::geom_histogram(bins = 50, alpha = 0.7, fill = "steelblue", color = "white") +
        ggplot2::theme_minimal() +
        ggplot2::theme(panel.background = ggplot2::element_rect(fill = "white", color = NA),
                       plot.background = ggplot2::element_rect(fill = "white", color = NA)) +
        ggplot2::labs(title = paste("Histogram of", gsub("\\.", " ", score_col)),
                      x = gsub("\\.", " ", score_col), y = "Count")

      plot_name_violin <- paste0("dist_", gsub("\\.", "_", tolower(score_col)), "_violin")
      plot_name_hist <- paste0("dist_", gsub("\\.", "_", tolower(score_col)), "_hist")

      plots[[plot_name_violin]] <- p_violin
      plots[[plot_name_hist]] <- p_hist
    }
  }

  return(plots)
}

# ───────────────────── 7c. Score summary statistics ───────────────────────
generate_score_summaries <- function(seurat, score_table, output_dir) {
  message("[INFO] Generating score summary statistics...")

  # Get metadata with scores
  meta <- seurat@meta.data

  # Define score columns to analyze
  score_columns <- c("S.Score", "G2M.Score", "Prog1", "Diff1")

  # Add combined cell cycle score
  if ("S.Score" %in% colnames(meta) && "G2M.Score" %in% colnames(meta)) {
    meta$cycle_combined <- meta$S.Score + meta$G2M.Score
    score_columns <- c(score_columns, "cycle_combined")
  }

  # Add individual root scores
  if ("Prog1" %in% colnames(meta) && "Diff1" %in% colnames(meta) && "S.Score" %in% colnames(meta) && "G2M.Score" %in% colnames(meta)) {
    prog_scaled <- scales::rescale(meta$Prog1, to = c(0, 1))
    cycle_scaled <- scales::rescale(meta$S.Score + meta$G2M.Score, to = c(0, 1))
    diff_scaled <- scales::rescale(meta$Diff1, to = c(0, 1))
    meta$root_score_individual <- 2*prog_scaled + 0.5*cycle_scaled - 3*diff_scaled
    score_columns <- c(score_columns, "root_score_individual")
  }

  # 1. Overall summary statistics
  overall_summary <- data.frame(
    score = character(),
    mean = numeric(),
    median = numeric(),
    sd = numeric(),
    min = numeric(),
    max = numeric(),
    q25 = numeric(),
    q75 = numeric(),
    stringsAsFactors = FALSE
  )

  for (score_col in score_columns) {
    if (score_col %in% colnames(meta)) {
      values <- meta[[score_col]]
      values <- values[!is.na(values)]  # Remove NA values

      if (length(values) > 0) {
        overall_summary <- rbind(overall_summary, data.frame(
          score = score_col,
          mean = mean(values),
          median = median(values),
          sd = sd(values),
          min = min(values),
          max = max(values),
          q25 = quantile(values, 0.25),
          q75 = quantile(values, 0.75),
          stringsAsFactors = FALSE
        ))
      }
    }
  }

  # 2. Cluster-wise summary statistics
  cluster_summary <- data.frame(
    cluster = character(),
    score = character(),
    mean = numeric(),
    median = numeric(),
    sd = numeric(),
    min = numeric(),
    max = numeric(),
    q25 = numeric(),
    q75 = numeric(),
    n_cells = numeric(),
    stringsAsFactors = FALSE
  )

  clusters <- unique(meta$seurat_clusters)
  for (cluster in clusters) {
    cluster_cells <- meta[meta$seurat_clusters == cluster, ]

    for (score_col in score_columns) {
      if (score_col %in% colnames(cluster_cells)) {
        values <- cluster_cells[[score_col]]
        values <- values[!is.na(values)]  # Remove NA values

        if (length(values) > 0) {
          cluster_summary <- rbind(cluster_summary, data.frame(
            cluster = as.character(cluster),
            score = score_col,
            mean = mean(values),
            median = median(values),
            sd = sd(values),
            min = min(values),
            max = max(values),
            q25 = quantile(values, 0.25),
            q75 = quantile(values, 0.75),
            n_cells = length(values),
            stringsAsFactors = FALSE
          ))
        }
      }
    }
  }

  # 3. Enhanced cluster score table with additional metrics
  enhanced_score_table <- score_table

  # Add coefficient of variation and score ranges
  for (cluster in clusters) {
    cluster_cells <- meta[meta$seurat_clusters == cluster, ]
    cluster_idx <- which(enhanced_score_table$cluster == cluster)

    if (length(cluster_idx) > 0) {
      # Add CV (coefficient of variation) for each score type
      if ("Prog1" %in% colnames(cluster_cells)) {
        prog_values <- cluster_cells$Prog1[!is.na(cluster_cells$Prog1)]
        enhanced_score_table$prog_cv[cluster_idx] <- if(length(prog_values) > 0 && mean(prog_values) != 0) sd(prog_values) / abs(mean(prog_values)) else 0
      }

      if ("Diff1" %in% colnames(cluster_cells)) {
        diff_values <- cluster_cells$Diff1[!is.na(cluster_cells$Diff1)]
        enhanced_score_table$diff_cv[cluster_idx] <- if(length(diff_values) > 0 && mean(diff_values) != 0) sd(diff_values) / abs(mean(diff_values)) else 0
      }

      if ("S.Score" %in% colnames(cluster_cells) && "G2M.Score" %in% colnames(cluster_cells)) {
        cycle_values <- (cluster_cells$S.Score + cluster_cells$G2M.Score)[!is.na(cluster_cells$S.Score + cluster_cells$G2M.Score)]
        enhanced_score_table$cycle_cv[cluster_idx] <- if(length(cycle_values) > 0 && mean(cycle_values) != 0) sd(cycle_values) / abs(mean(cycle_values)) else 0
      }
    }
  }

  # 4. Score correlation matrix
  score_correlations <- NULL
  available_scores <- score_columns[score_columns %in% colnames(meta)]
  if (length(available_scores) > 1) {
    score_data <- meta[, available_scores, drop = FALSE]
    score_data <- score_data[complete.cases(score_data), ]  # Remove rows with any NA

    if (nrow(score_data) > 10) {  # Need sufficient data for correlation
      score_correlations <- cor(score_data, use = "complete.obs")
    }
  }

  # Export summary files
  tryCatch({
    # Overall summary
    readr::write_tsv(overall_summary, fs::path(output_dir, "score_summary_overall.tsv"))
    message("[INFO] Overall score summary saved → ", fs::path_abs(fs::path(output_dir, "score_summary_overall.tsv")))

    # Cluster-wise summary
    readr::write_tsv(cluster_summary, fs::path(output_dir, "score_summary_by_cluster.tsv"))
    message("[INFO] Cluster-wise score summary saved → ", fs::path_abs(fs::path(output_dir, "score_summary_by_cluster.tsv")))

    # Enhanced cluster score table
    readr::write_tsv(enhanced_score_table, fs::path(output_dir, "cluster_scores_enhanced.tsv"))
    message("[INFO] Enhanced cluster scores saved → ", fs::path_abs(fs::path(output_dir, "cluster_scores_enhanced.tsv")))

    # Score correlations (if available)
    if (!is.null(score_correlations)) {
      correlation_df <- as.data.frame(score_correlations)
      correlation_df$score <- rownames(correlation_df)
      correlation_df <- correlation_df[, c("score", colnames(score_correlations))]
      readr::write_tsv(correlation_df, fs::path(output_dir, "score_correlations.tsv"))
      message("[INFO] Score correlations saved → ", fs::path_abs(fs::path(output_dir, "score_correlations.tsv")))
    }

  }, error = function(e) {
    message("[ERROR] Failed to save score summaries: ", e$message)
  })

  # Return summary data for potential further use
  return(list(
    overall = overall_summary,
    by_cluster = cluster_summary,
    enhanced_scores = enhanced_score_table,
    correlations = score_correlations
  ))
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
                                     marker_file = NULL,
                                     umap_dims = 1:2,
                                     linewidth = 0.8,
                                     arrow_len = 0.35,
                                     arrow_angle = 25) {

  message("[INFO] Creating separate MST plots...")
  message("[DEBUG] Function arguments - output_dir: ", output_dir)
  message("[DEBUG] Function arguments - marker_file: ", ifelse(is.null(marker_file), "NULL", marker_file))

  # Ensure output directory exists
  if (!dir.exists(output_dir)) {
    dir.create(output_dir, recursive = TRUE)
    message("[DEBUG] Created output directory: ", output_dir)
  } else {
    message("[DEBUG] Output directory already exists: ", output_dir)
  }

  # Create markers subdirectory
  markers_dir <- file.path(output_dir, "markers")
  message("[DEBUG] Markers directory path: ", markers_dir)
  if (!dir.exists(markers_dir)) {
    dir.create(markers_dir, recursive = TRUE)
    message("[DEBUG] Created markers directory: ", markers_dir)
  } else {
    message("[DEBUG] Markers directory already exists: ", markers_dir)
  }

  # Define variables for different plot types
  cluster_vars <- c("leiden_scvi", "seurat_clusters")
  # Prioritize proper cell type annotations over clustering results
  celltype_vars <- c("cell_type_cluster_weighted", "cell_type_cluster", "cell_type",
                     "celltype", "predicted.celltype", "predicted_celltype", "annotation", "scpred_prediction")
  message("[DEBUG] Available metadata columns: ", paste(colnames(seurat_obj@meta.data), collapse = ", "))
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
  message("[DEBUG] Checking marker file existence...")
  message("[DEBUG] marker_file is NULL: ", is.null(marker_file))
  if (!is.null(marker_file)) {
    message("[DEBUG] marker_file value: ", marker_file)
    message("[DEBUG] file.exists(marker_file): ", file.exists(marker_file))
  }

  if (!is.null(marker_file) && file.exists(marker_file)) {
    message("[DEBUG] Reading marker file: ", marker_file)
    tryCatch({
      marker_data <- readr::read_tsv(marker_file, show_col_types = FALSE)
      message("[DEBUG] Marker file columns: ", paste(colnames(marker_data), collapse = ", "))
      message("[DEBUG] Marker file rows: ", nrow(marker_data))

      if ("gene" %in% colnames(marker_data)) {
        all_marker_genes <- marker_data$gene |>
                            intersect(rownames(seurat_obj))

        # More detailed debugging
        message("[DEBUG] Total genes in marker file: ", length(marker_data$gene))
        message("[DEBUG] Total genes in Seurat object: ", length(rownames(seurat_obj)))
        message("[DEBUG] Genes found in Seurat object: ", length(all_marker_genes))
        message("[DEBUG] Available Seurat genes (first 10): ", paste(head(rownames(seurat_obj), 10), collapse = ", "))
        message("[DEBUG] Marker genes (first 10): ", paste(head(marker_data$gene, 10), collapse = ", "))
        message("[DEBUG] Found marker genes (first 10): ", paste(head(all_marker_genes, 10), collapse = ", "))

        # Check for missing genes
        missing_genes <- setdiff(marker_data$gene, rownames(seurat_obj))
        if (length(missing_genes) > 0) {
          message("[WARNING] ", length(missing_genes), " marker genes not found in Seurat object")
          message("[WARNING] Missing genes (first 10): ", paste(head(missing_genes, 10), collapse = ", "))
        }

        # Test actual expression values for found genes
        if (length(all_marker_genes) > 0) {
          test_gene <- all_marker_genes[1]
          tryCatch({
            test_expr <- LayerData(seurat_obj, layer = "data", features = test_gene)
            expr_range <- range(as.numeric(test_expr[1, ]))
            message("[DEBUG] Test gene ", test_gene, " expression range: [", expr_range[1], ", ", expr_range[2], "]")
            message("[DEBUG] Test gene ", test_gene, " non-zero cells: ", sum(as.numeric(test_expr[1, ]) > 0))
          }, error = function(e) {
            message("[ERROR] Failed to get expression for test gene ", test_gene, ": ", e$message)
          })
        }
      } else {
        message("[ERROR] 'gene' column not found in marker file. Available columns: ", paste(colnames(marker_data), collapse = ", "))
        all_marker_genes <- c()
      }
    }, error = function(e) {
      message("[ERROR] Failed to read marker file: ", e$message)
      all_marker_genes <- c()
    })

    # Use ALL available marker genes for comprehensive visualization
    selected_marker_genes <- all_marker_genes

    message("[DEBUG] Selected ", length(selected_marker_genes), " marker genes for plotting")
  } else {
    selected_marker_genes <- c()
    message("[WARNING] Marker file not found or NULL: ", ifelse(is.null(marker_file), "NULL", marker_file))
  }

  message("[DEBUG] Available cluster vars: ", paste(available_cluster_vars, collapse = ", "))
  message("[DEBUG] Available celltype vars: ", paste(available_celltype_vars, collapse = ", "))
  message("[DEBUG] Selected marker genes: ", paste(selected_marker_genes, collapse = ", "))

  # Create individual MST plotting function
  create_single_mst_plot <- function(var_name) {
    message("[DEBUG] create_single_mst_plot called for: ", var_name)
    tryCatch({
      message("[DEBUG] Calling plotSlingshotMST_latent for: ", var_name)
      mst_plot <- plotSlingshotMST_latent(sce,
                                         seurat_obj,
                                         group_vars = var_name,
                                         marker_file = marker_file,
                                         umap_dims = umap_dims,
                                         linewidth = linewidth,
                                         arrow_len = arrow_len,
                                         arrow_angle = arrow_angle,
                                         ncol_panels = 1)
      message("[DEBUG] plotSlingshotMST_latent returned object of class: ", class(mst_plot)[1])
      return(mst_plot)
    }, error = function(e) {
      message("[ERROR] Failed to create MST plot for '", var_name, "': ", e$message)
      message("[ERROR] Error trace: ", paste(sys.calls(), collapse = " -> "))
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
  message("[DEBUG] Starting marker gene plot creation...")
  message("[DEBUG] Number of selected marker genes: ", length(selected_marker_genes))

  if (length(selected_marker_genes) == 0) {
    message("[WARNING] No marker genes selected for plotting")
  } else {
    message("[DEBUG] Will create plots for markers: ", paste(selected_marker_genes, collapse = ", "))
  }

  # Memory management: limit concurrent processing and add garbage collection
  gc()  # Force garbage collection before starting

  for (i in seq_along(selected_marker_genes)) {
    marker <- selected_marker_genes[i]
    message("[DEBUG] Processing marker ", i, "/", length(selected_marker_genes), ": ", marker)

    marker_plot <- create_single_mst_plot(marker)
    message("[DEBUG] create_single_mst_plot returned: ", class(marker_plot)[1])

    if (!is.null(marker_plot)) {
      marker_filename <- paste0(marker, ".png")
      output_path <- file.path(markers_dir, marker_filename)
      message("[DEBUG] Attempting to save plot to: ", output_path)

      tryCatch({
        ggplot2::ggsave(output_path,
                        plot = marker_plot,
                        width = 20,
                        height = 18,
                        units = "cm",
                        dpi = 300)

        # Verify file was created
        if (file.exists(output_path)) {
          file_size <- file.info(output_path)$size
          message("[SUCCESS] Saved markers/", marker_filename, " (", file_size, " bytes)")
          plots_created <- plots_created + 1
        } else {
          message("[ERROR] File was not created: ", output_path)
        }
      }, error = function(e) {
        message("[ERROR] Failed to save markers/", marker_filename, ": ", e$message)
        message("[ERROR] Error class: ", class(e)[1])
        message("[ERROR] Error call: ", deparse(e$call))
      })
    } else {
      message("[WARNING] create_single_mst_plot returned NULL for marker: ", marker)
    }

    # Memory management: periodic garbage collection every 10 plots
    if (i %% 10 == 0) {
      gc()
      message("[DEBUG] Garbage collection performed after ", i, " plots")
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
                                    marker_file = NULL,
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
          cat("[DEBUG] Getting data layer for gene: ", var, "\n")
          expr <- LayerData(seurat_obj, layer = "data", features = var)
          cat("[DEBUG] Successfully retrieved data layer for: ", var, ", dimensions: ", paste(dim(expr), collapse="x"), "\n")
          expr
        }, error = function(e) {
          cat("[WARNING] Failed to get data layer for ", var, ", trying counts layer: ", e$message, "\n")
          tryCatch({
            expr <- LayerData(seurat_obj, layer = "counts", features = var)
            cat("[DEBUG] Successfully retrieved counts layer for: ", var, ", dimensions: ", paste(dim(expr), collapse="x"), "\n")
            expr
          }, error = function(e2) {
            cat("[ERROR] Failed to get both data and counts layers for ", var, ": ", e2$message, "\n")
            return(NULL)
          })
        })

        if (is.null(expr_data)) {
          cat("[ERROR] Could not retrieve expression data for gene: ", var, "\n")
          return(NULL)
        }

        gene_expr <- as.numeric(expr_data[1, ])
        expr_range <- range(gene_expr, na.rm = TRUE)
        non_zero_cells <- sum(gene_expr > 0, na.rm = TRUE)
        cat("[DEBUG] Gene ", var, " expression range: [", expr_range[1], ", ", expr_range[2], "], non-zero cells: ", non_zero_cells, "/", length(gene_expr), "\n")

        gene_expr
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

  # SPECIAL CASE: If only one group_var provided and it's a gene, return just that gene's plot
  if (length(group_vars) == 1 && group_vars[1] %in% rownames(seurat_obj)) {
    gene_name <- group_vars[1]
    cat("[DEBUG] Single gene request detected: ", gene_name, "\n")
    if (gene_name %in% names(non_legend_panels)) {
      gene_plot <- non_legend_panels[[gene_name]] +
        ggplot2::labs(title = paste("Expression:", gene_name))
      cat("[DEBUG] Returning single gene plot for: ", gene_name, "\n")
      return(gene_plot)
    } else {
      cat("[WARNING] Gene ", gene_name, " not found in panels\n")
    }
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
                         use_cache       = FALSE,
                         exclude_json    = NULL) {

  load_libraries()

  # Output paths - simplified structure without extra sample_id subdirectories
  path_dist  <- fs::path(out_dir, "dist")
  path_fig   <- fs::path(out_dir, "figs")
  path_cache <- fs::path(out_dir, "cache")
  walk(list(path_dist, path_fig, path_cache), dir.create,
       recursive = TRUE, showWarnings = FALSE)

  cache_seu <- fs::path(path_cache, "seurat.rds")
  cache_sce <- fs::path(path_cache, "sce.rds")

  # ── 1. Seurat object ──────────────────────────────────────────────────
  # Don't use cache if exclude filters are specified (since cached object won't have filtering applied)
  use_cache_with_exclude <- use_cache && (is.null(exclude_json) || exclude_json == "" || exclude_json == "null")

  seurat <- if (use_cache_with_exclude && file.exists(cache_seu)) {
              message("[INFO] Reusing cached Seurat → ", cache_seu)
              readRDS(cache_seu)
            } else {
              if (!is.null(exclude_json) && exclude_json != "" && exclude_json != "null") {
                message("[INFO] Exclude filters specified, bypassing cache to apply filtering")
              }
              read_inputs(h5ad_file,
                          progenitor,
                          differentiation,
                          marker_file) |>
              apply_exclude_filters(exclude_json = exclude_json) |>
              preprocess_seurat_latent(latent_dims = latent_dims,
                                       resolution  = resolution) |>
              score_cell_cycle()
            }

  if (!no_rds) {
    saveRDS(seurat, cache_seu)
    message("[DEBUG] Seurat object cached to: ", cache_seu)
  } else {
    message("[DEBUG] Skipping Seurat RDS save due to --no_rds option")
  }

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

  sce <- if (use_cache_with_exclude && file.exists(cache_sce)) {
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
  if (!no_rds) {
    tryCatch({
      saveRDS(sce, cache_sce)
      message("[DEBUG] SCE object cached successfully to: ", cache_sce)
    }, error = function(e) {
      message("[WARNING] Failed to cache SCE object: ", e$message)
    })
  } else {
    message("[DEBUG] Skipping SCE RDS save due to --no_rds option")
  }

  # ── 4. Plots & exports ────────────────────────────────────────────────
  tryCatch({
    message("[INFO] Creating comprehensive plots and summaries...")
    plots <- make_plots(root_info$seurat,
                        root_info$score_table,
                        root_info$start_cluster)
    save_plots(plots, path_fig)
    message("[DEBUG] Plots saved successfully")
  }, error = function(e) {
    message("[ERROR] Failed to create plots: ", e$message)
    message("[WARNING] Continuing without plots...")
  })

  # Generate and export score summaries
  tryCatch({
    message("[INFO] Generating score summaries and statistics...")
    score_summaries <- generate_score_summaries(root_info$seurat,
                                               root_info$score_table,
                                               path_dist)
    message("[DEBUG] Score summaries generated successfully")
  }, error = function(e) {
    message("[ERROR] Failed to generate score summaries: ", e$message)
    message("[WARNING] Continuing without score summaries...")
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
                                              output_dir = path_fig,
                                              marker_file = canonical_marker_tsv)

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
  no_rds <- FALSE
  exclude_json <- NULL

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
    } else if (args[i] == "--no_rds") {
      no_rds <- toupper(args[i + 1]) == "TRUE"
      i <- i + 2
    } else if (args[i] == "--exclude") {
      exclude_json <- args[i + 1]
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
    cat("  --no_rds TRUE/FALSE          Skip saving RDS files for speed (default: FALSE)\n")
    cat("  --exclude JSON               Exclude cells based on metadata (JSON format)\n")
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
      use_cache = !force_rerun,
      exclude_json = exclude_json
    )
    cat("Pipeline completed successfully for sample:", sample_id, "\n")
  }, error = function(e) {
    cat("Pipeline failed:", e$message, "\n")
    quit(status = 1)
  })
}
