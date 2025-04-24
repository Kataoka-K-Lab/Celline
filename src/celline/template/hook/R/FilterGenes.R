pacman::p_load(
    Seurat, SeuratObject, stringr, tidyverse,
    SingleCellExperiment, modeltools, flexmix,
    splines
)
## 除去する遺伝子のパターンを記載 ####
removal_gene_pattern <- list(
    mitochondrial = "^mt-"
)
#################################
#### PARAM Settings #####
args <- commandArgs(trailingOnly = TRUE)

raw_matrix_path <- args[1]
output_path <- args[2]
log_path <- args[3]
rm(args)

#########################
## 以下に用意している関数は、miQCというライブラリをミトコンドリア以外にも対応するようにしたバージョン。このバージョンを用いて実行すること。
## 関数の用意 ################################################################
pacman::p_load(
    Seurat, SeuratObject,
    SingleCellExperiment, modeltools, flexmix
)
qc_model <- function(sce, subsets_varname, model_type = "linear") {
    metrics <- as.data.frame(SingleCellExperiment::colData(sce))
    if (model_type == "linear") {
        model <- flexmix::flexmix(
            stats::as.formula(
                paste0("subsets_", subsets_varname, "_percent ~ detected")
            ),
            data = metrics,
            k = 2
        )
    } else if (model_type == "spline") {
        model <- flexmix::flexmix(
            stats::as.formula(
                paste0("subsets_", subsets_varname, "_percent ~ bs(detected)")
            ),
            data = metrics,
            k = 2
        )
    } else if (model_type == "polynomial") {
        model <- flexmix::flexmix(
            stats::as.formula(
                paste0(
                    "subsets_", subsets_varname,
                    "_percent ~ poly(detected, degree = 2)"
                )
            ),
            data = metrics,
            k = 2
        )
    } else if (model_type == "one_dimensional") {
        model <- flexmix::flexmix(
            stats::as.formula(
                paste0("subsets_", subsets_varname, "_percent ~ 1")
            ),
            data = metrics,
            k = 2
        )
    }
    print(model@components)
    if (length(model@components) < 2) {
        warning(
            "Unable to identify two distributions. Use plotMetrics function\n
            to confirm assumptions of miQC are met."
        )
    }
    return(model)
}

qc_filtercells <- function(sce, subsets_varname, model = NULL, posterior_cutoff = 0.75, keep_all_below_boundary = TRUE, # nolint
                           enforce_left_cutoff = TRUE, verbose = TRUE) {
    metrics <- as.data.frame(SingleCellExperiment::colData(sce))
    if (is.null(model)) {
        warning(
            "call 'mixtureModel' explicitly to get stable model features"
        )
        model <- qc_model(sce)
    }
    intercept1 <- modeltools::parameters(model, component = 1)[1]
    intercept2 <- modeltools::parameters(model, component = 2)[1]
    if (intercept1 > intercept2) {
        compromised_dist <- 1
        intact_dist <- 2
    } else {
        intact_dist <- 1
        compromised_dist <- 2
    }
    post <- modeltools::posterior(model)
    metrics <-
        metrics %>%
        dplyr::mutate(
            prob_compromised = post[, compromised_dist],
            keep = prob_compromised <= posterior_cutoff # nolint
        )
    sce$prob_compromised <- metrics$prob_compromised
    if (sum(metrics$keep) == nrow(metrics)) {
        stop(
            "all cells passed posterior probability filtering. One \n
                cause of this is the model selecting two near-identical\n
                distributions. Try rerunning mixtureModel() and/or \n
                setting a different random seed."
        )
    }
    name_subset <-
        paste0(
            "subsets_", subsets_varname,
            "_percent"
        )
    if (keep_all_below_boundary == TRUE) {
        predictions <- fitted(model)[, intact_dist]
        metrics <-
            metrics %>%
            dplyr::mutate( # nolint
                intact_prediction = predictions
            ) %>%
            mutate(
                keep = ifelse(
                    !!dplyr::sym(name_subset) < intact_prediction, # nolint
                    TRUE, keep # nolint
                )
            )
    }
    if (enforce_left_cutoff == TRUE) {
        min_discard <-
            metrics %>%
            dplyr::filter(!keep) %>% # nolint
            dplyr::distinct(!!dplyr::sym(name_subset)) %>%
            dplyr::pull() %>%
            min()
        min_index <-
            metrics %>%
            dplyr::mutate(
                index = dplyr::row_number()
            ) %>%
            filter(!!dplyr::sym(name_subset) == min_discard) %>%
            dplyr::distinct(index) %>% # nolint
            dplyr::pull()
        lib_complexity <- metrics[min_index, ]$detected
        metrics <-
            metrics %>%
            dplyr::mutate(
                keep = ifelse(
                    detected <= lib_complexity & !!dplyr::sym(name_subset) >= min_discard, # nolint
                    FALSE, keep # nolint
                )
            )
        if (verbose == TRUE) {
            to_remove <- length(which(metrics$keep == FALSE))
            total <- length(metrics$keep)
            cat(
                "Removing", to_remove, "out of", total,
                "cells @", subsets_varname, "\n"
            )
        }
        sce <- sce[, metrics$keep]
        sce
    }
    metrics %>%
        tibble::rownames_to_column("cell") %>%
        dplyr::select(cell, keep) %>% # nolint
        dplyr::rename(
            !!paste0("keep_", subsets_varname) := keep
        ) %>%
        return()
}
log_out <- function(content, append = TRUE) {
    write(
        content,
        file = log_path, append = append
    )
}
############################################
log_out("\n├─ ├─ Processing...")
if (!file.exists(raw_matrix_path)) {
    log_out("├─ ├─ File does not exists.")
    q(save = "no", status = 1)
}
if (file.exists(output_path)) {
    log_out("├─ ├─ Already predicted. skip.")
    q(save = "no", status = 1)
}
log_out("├─ ├─ Reading 10x")
seurat <-
    Read10X_h5(raw_matrix_path) %>%
    CreateSeuratObject(project = "PROJ")
gc(verbose = FALSE, reset = TRUE)
all_genes <- SeuratObject::Features(seurat)
removal_genes <- lapply(removal_gene_pattern, function(pattern) {
    return(str_subset(all_genes, pattern))
})
rm(all_genes)
sce <-
    seurat %>%
    as.SingleCellExperiment()
cnt <- 0
log_out("├─ ├─ Running miQC")
for (target_gene in names(removal_genes)) {
    log_out("├─ ├─ ├─ Adding QC metric")
    target_sce <-
        sce %>%
        scuttle::addPerCellQC(
            subsets = as.list(removal_genes[target_gene])
        )
    log_out("├─ ├─ ├─ Predicting QC model")
    model <- qc_model(target_sce, target_gene)
    log_out("├─ ├─ ├─ Filtering")
    cells <- qc_filtercells(
        target_sce, target_gene, model,
        posterior_cutoff = 0.5
    )
    if (cnt == 0) {
        merged <- cells
    } else {
        merged <-
            merged %>%
            full_join(
                cells,
                by = "cell"
            )
    }
    log_out("├─ ├─ ├─ Done")
    cnt <- cnt + 1
}
merged %>%
    write_tsv(output_path)
log_out("├─ └─ Done.")
