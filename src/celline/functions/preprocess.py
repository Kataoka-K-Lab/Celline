import argparse
import os
from typing import TYPE_CHECKING, Dict, Final, Optional

import matplotlib.pyplot as plt
import numpy as np
import polars as pl
import scanpy as sc
import scrublet as scr
import seaborn as sns
import toml
from rich.console import Console
from scipy.stats import median_abs_deviation

from celline.config import Config
from celline.DB.dev.handler import HandleResolver
from celline.DB.dev.model import SampleSchema
from celline.functions._base import CellineFunction
from celline.utils.path import Path

console = Console()


def _dynamic_cutoff(vec, n_mad: float = 3, side: str = "both"):
    """動的しきい値をMAD法で計算"""
    med = np.median(vec)
    mad = median_abs_deviation(vec)
    if side in ("both", "lower"):
        lower = med - n_mad * mad
    if side in ("both", "upper"):
        upper = med + n_mad * mad
    return lower if side == "lower" else upper if side == "upper" else (lower, upper)


def _generate_qc_plots(adata, sample_id: str, output_dir: str, thresholds: dict):
    """Generate QC plots for the sample"""
    # Create output directory for plots following Celline path structure
    plots_dir = os.path.join(output_dir, "figures", "qc")
    os.makedirs(plots_dir, exist_ok=True)

    # Set up matplotlib parameters
    plt.style.use("default")
    sns.set_palette("husl")

    # Create figure with subplots
    fig, axes = plt.subplots(2, 3, figsize=(18, 12))
    fig.suptitle(f"QC Metrics for Sample: {sample_id}", fontsize=16, fontweight="bold")

    # 1. Number of genes per cell
    ax = axes[0, 0]
    n_genes = adata.obs["n_genes_by_counts"]
    ax.hist(n_genes, bins=50, alpha=0.7, color="skyblue", edgecolor="black")
    ax.axvline(thresholds["lower_genes"], color="red", linestyle="--", linewidth=2, label=f"Lower: {thresholds['lower_genes']:.0f}")
    ax.axvline(thresholds["upper_genes"], color="red", linestyle="--", linewidth=2, label=f"Upper: {thresholds['upper_genes']:.0f}")
    ax.axvline(np.median(n_genes), color="orange", linestyle="-", linewidth=2, label=f"Median: {np.median(n_genes):.0f}")
    ax.set_xlabel("Number of genes per cell")
    ax.set_ylabel("Frequency")
    ax.set_title("Gene Complexity Distribution")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # 2. Total counts per cell
    ax = axes[0, 1]
    total_counts = adata.obs["total_counts"]
    ax.hist(total_counts, bins=50, alpha=0.7, color="lightgreen", edgecolor="black")
    ax.axvline(thresholds["upper_counts"], color="red", linestyle="--", linewidth=2, label=f"Upper: {thresholds['upper_counts']:.0f}")
    ax.axvline(np.median(total_counts), color="orange", linestyle="-", linewidth=2, label=f"Median: {np.median(total_counts):.0f}")
    ax.set_xlabel("Total counts per cell")
    ax.set_ylabel("Frequency")
    ax.set_title("Total Counts Distribution")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # 3. Mitochondrial percentage
    ax = axes[0, 2]
    mt_pct = adata.obs["pct_counts_mt"]
    ax.hist(mt_pct, bins=50, alpha=0.7, color="salmon", edgecolor="black")
    ax.axvline(thresholds["mt_pct_threshold"], color="red", linestyle="--", linewidth=2, label=f"Threshold: {thresholds['mt_pct_threshold']:.1f}%")
    ax.axvline(np.median(mt_pct), color="orange", linestyle="-", linewidth=2, label=f"Median: {np.median(mt_pct):.1f}%")
    ax.set_xlabel("Mitochondrial gene percentage (%)")
    ax.set_ylabel("Frequency")
    ax.set_title("Mitochondrial Gene Expression")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # 4. Doublet scores
    ax = axes[1, 0]
    doublet_scores = adata.obs["doublet_score"]
    ax.hist(doublet_scores, bins=50, alpha=0.7, color="mediumpurple", edgecolor="black")
    ax.axvline(np.median(doublet_scores), color="orange", linestyle="-", linewidth=2, label=f"Median: {np.median(doublet_scores):.3f}")
    if "scrublet_threshold" in thresholds and thresholds["scrublet_threshold"] is not None:
        ax.axvline(thresholds["scrublet_threshold"], color="red", linestyle="--", linewidth=2, label=f"Threshold: {thresholds['scrublet_threshold']:.3f}")
    ax.set_xlabel("Doublet Score")
    ax.set_ylabel("Frequency")
    ax.set_title("Scrublet Doublet Scores")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # 5. Scatter plot: Total counts vs Genes
    ax = axes[1, 1]
    passed_filter = ~adata.obs.get("filter_all", False) if "filter_all" in adata.obs else np.ones(len(adata.obs), dtype=bool)

    # Plot filtered cells in red, passed cells in blue
    ax.scatter(total_counts[~passed_filter], n_genes[~passed_filter], alpha=0.6, s=1, color="red", label="Filtered")
    ax.scatter(total_counts[passed_filter], n_genes[passed_filter], alpha=0.6, s=1, color="blue", label="Passed")

    ax.set_xlabel("Total counts per cell")
    ax.set_ylabel("Number of genes per cell")
    ax.set_title("Total Counts vs Gene Complexity")
    ax.legend()
    ax.grid(True, alpha=0.3)

    # 6. Scatter plot: MT% vs Total counts
    ax = axes[1, 2]
    ax.scatter(total_counts[~passed_filter], mt_pct[~passed_filter], alpha=0.6, s=1, color="red", label="Filtered")
    ax.scatter(total_counts[passed_filter], mt_pct[passed_filter], alpha=0.6, s=1, color="blue", label="Passed")

    ax.set_xlabel("Total counts per cell")
    ax.set_ylabel("Mitochondrial gene percentage (%)")
    ax.set_title("Total Counts vs Mitochondrial Expression")
    ax.legend()
    ax.grid(True, alpha=0.3)

    plt.tight_layout()

    # Save the plot
    plot_file = os.path.join(plots_dir, f"{sample_id}_qc_overview.png")
    plt.savefig(plot_file, dpi=300, bbox_inches="tight")
    plt.close()

    # Generate summary statistics plot
    _generate_qc_summary_plot(adata, sample_id, plots_dir, thresholds)

    return plot_file


def _generate_qc_summary_plot(adata, sample_id: str, plots_dir: str, thresholds: dict):
    """Generate QC summary bar plot"""
    # Calculate filtering statistics
    total_cells = len(adata.obs)

    # Create filter columns if they don't exist
    gene_filter = (adata.obs["n_genes_by_counts"] < thresholds["lower_genes"]) | (adata.obs["n_genes_by_counts"] > thresholds["upper_genes"])
    counts_filter = adata.obs["total_counts"] > thresholds["upper_counts"]
    mt_filter = adata.obs["pct_counts_mt"] > thresholds["mt_pct_threshold"]
    doublet_filter = adata.obs["predicted_doublets"]

    # Count filtered cells for each criterion
    stats = {
        "Gene Complexity": gene_filter.sum(),
        "Total Counts": counts_filter.sum(),
        "MT Percentage": mt_filter.sum(),
        "Doublets": doublet_filter.sum(),
        "Total Filtered": (gene_filter | counts_filter | mt_filter | doublet_filter).sum(),
    }

    remaining_cells = total_cells - stats["Total Filtered"]
    stats["Remaining"] = remaining_cells

    # Create summary plot
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    fig.suptitle(f"QC Summary for Sample: {sample_id}", fontsize=14, fontweight="bold")

    # Bar plot of filtered cells
    filter_categories = list(stats.keys())[:-1]  # Exclude 'Remaining'
    filter_counts = [stats[cat] for cat in filter_categories]
    filter_percentages = [100 * count / total_cells for count in filter_counts]

    bars1 = ax1.bar(filter_categories, filter_counts, color=["red", "orange", "purple", "brown", "darkred"])
    ax1.set_ylabel("Number of cells")
    ax1.set_title("Cells Filtered by Each Criterion")
    ax1.tick_params(axis="x", rotation=45)

    # Add percentage labels on bars
    for bar, pct in zip(bars1, filter_percentages, strict=False):
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width() / 2.0, height + total_cells * 0.01, f"{pct:.1f}%", ha="center", va="bottom", fontweight="bold")

    # Pie chart of overall filtering
    pie_data = [stats["Remaining"], stats["Total Filtered"]]
    pie_labels = [f"Passed\n({stats['Remaining']} cells)", f"Filtered\n({stats['Total Filtered']} cells)"]
    colors = ["lightblue", "lightcoral"]

    wedges, texts, autotexts = ax2.pie(pie_data, labels=pie_labels, colors=colors, autopct="%1.1f%%", startangle=90, textprops={"fontweight": "bold"})
    ax2.set_title("Overall Filtering Results")

    plt.tight_layout()

    # Save the summary plot
    summary_file = os.path.join(plots_dir, f"{sample_id}_qc_summary.png")
    plt.savefig(summary_file, dpi=300, bbox_inches="tight")
    plt.close()

    return summary_file


def _generate_umap_plots(adata, sample_id: str, output_dir: str):
    """Generate UMAP plots for QC metrics, doublets, and clustering"""
    # Create output directory for QC plots (including UMAP plots)
    qc_dir = os.path.join(output_dir, "figures", "qc")
    os.makedirs(qc_dir, exist_ok=True)

    # Set up scanpy figure directory and parameters
    sc.settings.figdir = qc_dir

    # Set matplotlib parameters directly to avoid recursion
    import matplotlib as mpl

    mpl.rcParams["figure.dpi"] = 300
    mpl.rcParams["figure.facecolor"] = "white"
    mpl.rcParams["savefig.format"] = "png"

    try:
        # 1. Leiden clustering UMAP
        console.print("[dim]Generating Leiden clustering UMAP...[/dim]")
        sc.pl.umap(
            adata,
            color=["leiden"],
            frameon=False,
            legend_loc="on data",
            save=f"_{sample_id}_clusters.png",
            show=False,
        )

        # 2. QC overview UMAP (filter status, doublet score, mt%, total counts)
        console.print("[dim]Generating QC overview UMAPs...[/dim]")
        sc.pl.umap(
            adata,
            color=["filter_all", "doublet_score", "pct_counts_mt", "total_counts"],
            ncols=2,
            frameon=False,
            save=f"_{sample_id}_qc_overview.png",
            show=False,
        )

        # 3. Individual QC metric UMAPs
        console.print("[dim]Generating individual QC metric UMAPs...[/dim]")

        # Doublet-specific UMAP
        sc.pl.umap(
            adata,
            color=["doublet_score", "predicted_doublets"],
            ncols=2,
            frameon=False,
            save=f"_{sample_id}_doublets.png",
            show=False,
        )

        # Mitochondrial gene expression UMAP
        sc.pl.umap(
            adata,
            color=["pct_counts_mt"],
            frameon=False,
            save=f"_{sample_id}_mt_expression.png",
            show=False,
        )

        # Total counts UMAP
        sc.pl.umap(
            adata,
            color=["total_counts"],
            frameon=False,
            save=f"_{sample_id}_total_counts.png",
            show=False,
        )

        # Gene complexity UMAP
        sc.pl.umap(
            adata,
            color=["n_genes_by_counts"],
            frameon=False,
            save=f"_{sample_id}_gene_complexity.png",
            show=False,
        )

        # 4. Filter breakdown UMAP (showing individual filter types)
        console.print("[dim]Generating filter breakdown UMAPs...[/dim]")

        # Create individual filter columns for visualization
        gene_filter = (adata.obs["n_genes_by_counts"] < adata.uns.get("qc_lower_genes", 0)) | (adata.obs["n_genes_by_counts"] > adata.uns.get("qc_upper_genes", np.inf))
        counts_filter = adata.obs["total_counts"] > adata.uns.get("qc_upper_counts", np.inf)
        mt_filter = adata.obs["pct_counts_mt"] > adata.uns.get("qc_mt_threshold", 100)
        doublet_filter = adata.obs["predicted_doublets"]

        # Add temporary columns for visualization
        adata.obs["filter_gene_complexity"] = gene_filter
        adata.obs["filter_total_counts"] = counts_filter
        adata.obs["filter_mt"] = mt_filter
        adata.obs["filter_doublet"] = doublet_filter

        sc.pl.umap(
            adata,
            color=["filter_gene_complexity", "filter_total_counts", "filter_mt", "filter_doublet"],
            ncols=2,
            frameon=False,
            save=f"_{sample_id}_filter_breakdown.png",
            show=False,
        )

        # Clean up temporary columns
        adata.obs.drop(["filter_gene_complexity", "filter_total_counts", "filter_mt", "filter_doublet"], axis=1, inplace=True)

        console.print(f"[green]✓ UMAP plots saved to: {qc_dir}[/green]")

    except Exception as e:
        console.print(f"[yellow]⚠ Warning: Could not generate some UMAP plots: {e}[/yellow]")
        import traceback

        traceback.print_exc()


def _check_plots_exist(output_dir: str, sample_id: str) -> dict:
    """Check which plots exist and which are missing"""
    qc_dir = os.path.join(output_dir, "figures", "qc")

    # Define expected plot files
    expected_plots = {
        "qc_overview": os.path.join(qc_dir, f"{sample_id}_qc_overview.png"),
        "qc_summary": os.path.join(qc_dir, f"{sample_id}_qc_summary.png"),
        "umap_clusters": os.path.join(qc_dir, f"umap_{sample_id}_clusters.png"),
        "umap_qc_overview": os.path.join(qc_dir, f"umap_{sample_id}_qc_overview.png"),
        "umap_doublets": os.path.join(qc_dir, f"umap_{sample_id}_doublets.png"),
        "umap_mt_expression": os.path.join(qc_dir, f"umap_{sample_id}_mt_expression.png"),
        "umap_total_counts": os.path.join(qc_dir, f"umap_{sample_id}_total_counts.png"),
        "umap_gene_complexity": os.path.join(qc_dir, f"umap_{sample_id}_gene_complexity.png"),
        "umap_filter_breakdown": os.path.join(qc_dir, f"umap_{sample_id}_filter_breakdown.png"),
    }

    missing_plots = []
    existing_plots = []

    for plot_name, plot_path in expected_plots.items():
        if os.path.exists(plot_path):
            existing_plots.append(plot_name)
        else:
            missing_plots.append(plot_name)

    return {"missing": missing_plots, "existing": existing_plots, "has_missing": len(missing_plots) > 0}


def _load_existing_qc_data(path, sample_id: str, mt_pct_threshold: float = 5.0, n_mad: float = 2.5, mt_prefix: str = "mt-"):
    """Load existing QC data from cell_info.tsv and recalculate thresholds"""
    try:
        # Load cell_info.tsv
        cell_info_path = f"{path.data_sample}/cell_info.tsv"
        obs_df = pl.read_csv(cell_info_path, separator="\t")

        # Load count data
        count_file = f"{path.resources_sample_counted}/outs/filtered_feature_bc_matrix.h5"
        adata = sc.read_10x_h5(count_file)
        adata.var_names_make_unique()

        # Add sample metadata to match the QC processing format
        adata.obs["sample"] = sample_id

        # Ensure mitochondrial genes are marked
        adata.var["mt"] = adata.var_names.str.upper().str.startswith(mt_prefix.upper())

        # Map cell_info data to adata.obs by barcode
        if "barcode" in obs_df.columns:
            barcode_to_metrics = obs_df.to_pandas().set_index("barcode")

            # Map QC metrics to adata.obs
            for col in ["n_genes_by_counts", "total_counts", "pct_counts_mt", "doublet_score", "predicted_doublets"]:
                if col in barcode_to_metrics.columns:
                    adata.obs[col] = adata.obs.index.map(barcode_to_metrics[col])

            # Map filter information
            if "include" in barcode_to_metrics.columns:
                adata.obs["filter_all"] = ~barcode_to_metrics["include"].astype(bool)

            # Recalculate QC thresholds from existing data for plotting consistency
            if "n_genes_by_counts" in adata.obs.columns:
                gene_counts = adata.obs["n_genes_by_counts"].values
                lower_genes, upper_genes = _dynamic_cutoff(gene_counts, n_mad=n_mad)
                adata.uns["qc_lower_genes"] = lower_genes
                adata.uns["qc_upper_genes"] = upper_genes

            if "total_counts" in adata.obs.columns:
                total_counts = adata.obs["total_counts"].values
                upper_counts = _dynamic_cutoff(total_counts, n_mad=n_mad, side="upper")
                adata.uns["qc_upper_counts"] = upper_counts

            adata.uns["qc_mt_threshold"] = mt_pct_threshold

        console.print(f"[green]✓ Loaded existing QC data for {sample_id}: {adata.n_obs} cells[/green]")
        return adata

    except Exception as e:
        console.print(f"[red]✗ Error loading existing QC data for {sample_id}: {e}[/red]")
        return None


class Preprocess(CellineFunction):
    TARGET_CELLTYPE: Final[list[str] | None]

    def __init__(self, target_celltype: list[str] | None = None, mt_pct_threshold: float = 5.0, n_mad: float = 2.5, mt_prefix: str = "mt-", generate_plots: bool = True):
        """Initialize the Preprocess class.

        This constructor sets up the Preprocess object with an optional list of target cell types
        and dynamic filtering parameters.

        Parameters
        ----------
        target_celltype : Optional[list[str]], default=None
            A list of target cell types to be considered in the preprocessing.
            If None, all cell types will be considered.
        mt_pct_threshold : float, default=5.0
            Mitochondrial percentage threshold for filtering cells.
        n_mad : float, default=2.5
            Number of MADs for outlier detection in dynamic thresholding.
        mt_prefix : str, default="mt-"
            Mitochondrial gene prefix (case-insensitive matching will be applied).
        generate_plots : bool, default=True
            Whether to generate QC plots.

        Returns
        -------
        None

        """
        self.TARGET_CELLTYPE = target_celltype
        self.mt_pct_threshold = mt_pct_threshold
        self.n_mad = n_mad
        self.mt_prefix = mt_prefix
        self.generate_plots = generate_plots

    def call(self, project):
        """Perform preprocessing on the given project's samples.

        This function reads sample information from a TOML file, processes each sample,
        performs quality control, and generates cell information for further analysis.

        Parameters
        ----------
        project : object
            The project object containing information about the samples to be processed.

        Returns
        -------
        project : object
            The input project object, potentially modified during processing.

        Raises
        ------
        ReferenceError
            If a sample ID cannot be resolved.
        KeyError
            If a sample's parent information is missing.

        """
        sample_info_file = f"{Config.PROJ_ROOT}/samples.toml"
        if not os.path.isfile(sample_info_file):
            print("sample.toml could not be found. Skipping.")
            return project
        with open(sample_info_file, encoding="utf-8") as f:
            samples: dict[str, str] = toml.load(f)
            for sample_id in samples:
                resolver = HandleResolver.resolve(sample_id)
                if resolver is None:
                    raise ReferenceError(f"Could not resolve target sample id: {sample_id}")
                sample_schema: SampleSchema = resolver.sample.search(sample_id)
                if sample_schema.parent is None:
                    raise KeyError("Could not find parent")
                path = Path(sample_schema.parent, sample_id)
                path.prepare()
                if path.is_counted:
                    console.print(f"[dim]Processing sample {sample_id}...[/dim]")

                    # Check if cell_info.tsv already exists
                    cell_info_path = f"{path.data_sample}/cell_info.tsv"
                    cell_info_exists = os.path.exists(cell_info_path)

                    if cell_info_exists:
                        console.print(f"[dim]Found existing cell_info.tsv for {sample_id}[/dim]")

                        # Check if plots are missing
                        plot_status = _check_plots_exist(path.data_sample, sample_id)

                        if not plot_status["has_missing"]:
                            console.print(f"[green]✓ All plots exist for {sample_id}, skipping...[/green]")
                            continue
                        console.print(f"[dim]Missing plots for {sample_id}: {', '.join(plot_status['missing'])}[/dim]")
                        console.print("[dim]Generating missing plots...[/dim]")

                        # Load existing QC data and generate missing plots
                        adata = _load_existing_qc_data(path, sample_id, self.mt_pct_threshold, self.n_mad, self.mt_prefix)
                        if adata is None:
                            console.print(f"[red]✗ Failed to load existing QC data for {sample_id}, skipping...[/red]")
                            continue

                        # Skip to plot generation (after the main QC processing)
                        needs_full_processing = False
                    else:
                        console.print(f"[dim]No existing cell_info.tsv found for {sample_id}, performing full QC processing...[/dim]")
                        needs_full_processing = True

                    if needs_full_processing:
                        try:
                            count_file = f"{path.resources_sample_counted}/outs/filtered_feature_bc_matrix.h5"
                            adata = sc.read_10x_h5(count_file)
                            console.print(f"[dim]✓ Loaded count data: {adata.n_obs} cells, {adata.n_vars} genes[/dim]")
                        except Exception as e:
                            console.print(f"[red]✗ Error loading count data for {sample_id}: {e}[/red]")
                            continue

                        obs = (
                            pl.DataFrame(adata.obs.reset_index())
                            .rename({"index": "barcode"})
                            .with_columns(pl.lit(sample_schema.parent).alias("project"))
                            .with_columns(pl.lit(sample_id).alias("sample"))
                            .with_columns((pl.concat_str(pl.col("sample"), pl.cum_count("sample"), separator="_")).alias("cell"))
                        )

                        # Check if cell type prediction exists, if not, include all cells
                        if path.is_predicted_celltype:
                            console.print("[dim]✓ Found cell type predictions, applying cell type filtering[/dim]")
                            try:
                                obs = obs.join(
                                    pl.read_csv(
                                        path.data_sample_predicted_celltype,
                                        separator="\t",
                                    ).rename({"scpred_prediction": "cell_type"}),
                                    on="cell",
                                ).with_columns(
                                    (
                                        pl.col("cell_type").is_in(obs.select(pl.col("cell_type")).unique().get_column("cell_type").to_list() if self.TARGET_CELLTYPE is None else self.TARGET_CELLTYPE)
                                    ).alias("include"),
                                )
                            except Exception as e:
                                console.print(f"[yellow]⚠ Warning: Error reading cell type predictions for {sample_id}: {e}[/yellow]")
                                console.print("[dim]Proceeding without cell type filtering...[/dim]")
                                obs = obs.with_columns(pl.lit("Unknown").alias("cell_type")).with_columns(pl.lit(True).alias("include"))
                        else:
                            console.print(f"[yellow]⚠ Cell type predictions not found for {sample_id}[/yellow]")
                            console.print("[dim]Proceeding without cell type filtering...[/dim]")
                            obs = obs.with_columns(pl.lit("Unknown").alias("cell_type")).with_columns(pl.lit(True).alias("include"))

                        # Scrublet doublet detection
                        console.print(f"[dim]Running Scrublet doublet detection for {sample_id}...[/dim]")
                        scrub = scr.Scrublet(adata.X)
                        doublet_scores, predicted_doublets = scrub.scrub_doublets(verbose=False)
                        adata.obs["doublet_score"] = doublet_scores
                        adata.obs["predicted_doublets"] = predicted_doublets

                        # Mitochondrial gene detection (case-insensitive)
                        adata.var["mt"] = adata.var_names.str.upper().str.startswith(self.mt_prefix.upper())

                        # Calculate QC metrics
                        sc.pp.calculate_qc_metrics(
                            adata,
                            qc_vars=["mt"],
                            percent_top=None,
                            log1p=False,
                            inplace=True,
                        )

                        # Add QC metrics from adata.obs to our obs DataFrame
                        console.print("[dim]Adding QC metrics to obs DataFrame...[/dim]")
                        qc_metrics = pl.DataFrame(
                            {
                                "barcode": adata.obs.index.tolist(),
                                "n_genes_by_counts": adata.obs["n_genes_by_counts"].values,
                                "total_counts": adata.obs["total_counts"].values,
                                "pct_counts_mt": adata.obs["pct_counts_mt"].values,
                                "doublet_score": adata.obs["doublet_score"].values,
                                "predicted_doublets": adata.obs["predicted_doublets"].values,
                            },
                        )

                        # Join QC metrics with obs DataFrame
                        obs = obs.join(qc_metrics, on="barcode")

                        # Dynamic thresholding for gene complexity
                        console.print(f"[dim]Applying dynamic thresholds (MAD method, n_mad={self.n_mad})...[/dim]")
                        gene_counts = adata.obs["n_genes_by_counts"].values
                        lower_genes, upper_genes = _dynamic_cutoff(gene_counts, n_mad=self.n_mad)

                        # Dynamic thresholding for total counts (upper only)
                        total_counts = adata.obs["total_counts"].values
                        upper_counts = _dynamic_cutoff(total_counts, n_mad=self.n_mad, side="upper")

                        console.print(f"[dim]Gene complexity thresholds: {lower_genes:.1f} - {upper_genes:.1f}[/dim]")
                        console.print(f"[dim]Total counts threshold: {upper_counts:.1f}[/dim]")
                        console.print(f"[dim]MT percentage threshold: {self.mt_pct_threshold}%[/dim]")

                        # Apply filtering criteria with dynamic thresholds
                        (
                            obs.with_columns(((pl.col("n_genes_by_counts") >= lower_genes) & pl.col("include")).alias("include"))
                            .with_columns(((pl.col("n_genes_by_counts") <= upper_genes) & pl.col("include")).alias("include"))
                            .with_columns(((pl.col("total_counts") <= upper_counts) & pl.col("include")).alias("include"))
                            .with_columns(((pl.col("pct_counts_mt") <= self.mt_pct_threshold) & pl.col("include")).alias("include"))
                            .with_columns(((pl.col("predicted_doublets") == False) & pl.col("include")).alias("include"))
                            .write_csv(f"{path.data_sample}/cell_info.tsv", separator="\t")
                        )

                    # Run preprocessing pipeline for UMAP visualization
                    console.print(f"[dim]Running preprocessing pipeline for {sample_id}...[/dim]")
                    try:
                        # Create a copy for preprocessing (to keep original data intact)
                        adata_processed = adata.copy()

                        # 1) Library size normalization
                        console.print("[dim]Normalizing library sizes to 10,000...[/dim]")
                        sc.pp.normalize_total(adata_processed, target_sum=1e4)

                        # 2) Log transformation
                        console.print("[dim]Applying log1p transformation...[/dim]")
                        sc.pp.log1p(adata_processed)

                        # 3) Highly variable genes
                        console.print("[dim]Identifying highly variable genes (top 2000)...[/dim]")
                        sc.pp.highly_variable_genes(
                            adata_processed,
                            flavor="seurat_v3",
                            n_top_genes=2000,
                            subset=True,
                        )

                        # 4) Scaling
                        console.print("[dim]Scaling data (mean=0, var=1, max_value=10)...[/dim]")
                        sc.pp.scale(adata_processed, max_value=10)

                        # 5) PCA
                        console.print("[dim]Computing PCA...[/dim]")
                        sc.tl.pca(adata_processed, svd_solver="arpack")

                        # 6) Neighbors
                        console.print("[dim]Building neighbor graph (n_pcs=40, n_neighbors=15)...[/dim]")
                        sc.pp.neighbors(adata_processed, n_pcs=40, n_neighbors=15)

                        # 7) UMAP
                        console.print("[dim]Computing UMAP embedding...[/dim]")
                        sc.tl.umap(adata_processed)

                        # 8) Leiden clustering
                        console.print("[dim]Performing Leiden clustering (resolution=1.0)...[/dim]")
                        sc.tl.leiden(adata_processed, resolution=1.0)
                        n_clusters = len(adata_processed.obs["leiden"].unique())
                        console.print(f"[dim]Identified {n_clusters} clusters[/dim]")

                        # Generate plots for both full processing and existing data scenarios
                        if self.generate_plots:
                            console.print(f"[dim]Generating comprehensive QC and UMAP plots for {sample_id}...[/dim]")
                            try:
                                # Get thresholds - either from variables (full processing) or from adata.uns (existing data)
                                if needs_full_processing:
                                    # Use locally defined variables from full processing
                                    thresholds = {
                                        "lower_genes": lower_genes,
                                        "upper_genes": upper_genes,
                                        "upper_counts": upper_counts,
                                        "mt_pct_threshold": self.mt_pct_threshold,
                                        "scrublet_threshold": getattr(scrub, "threshold_", None),
                                    }
                                    # Add filter information to adata for visualization
                                    gene_filter = (adata.obs["n_genes_by_counts"] < lower_genes) | (adata.obs["n_genes_by_counts"] > upper_genes)
                                    counts_filter = adata.obs["total_counts"] > upper_counts
                                    mt_filter = adata.obs["pct_counts_mt"] > self.mt_pct_threshold
                                    doublet_filter = adata.obs["predicted_doublets"]
                                else:
                                    # Use thresholds from adata.uns (existing data)
                                    thresholds = {
                                        "lower_genes": adata.uns.get("qc_lower_genes", 0),
                                        "upper_genes": adata.uns.get("qc_upper_genes", np.inf),
                                        "upper_counts": adata.uns.get("qc_upper_counts", np.inf),
                                        "mt_pct_threshold": adata.uns.get("qc_mt_threshold", self.mt_pct_threshold),
                                        "scrublet_threshold": None,  # Not available for existing data
                                    }
                                    # Add filter information to adata for visualization
                                    gene_filter = (adata.obs["n_genes_by_counts"] < thresholds["lower_genes"]) | (adata.obs["n_genes_by_counts"] > thresholds["upper_genes"])
                                    counts_filter = adata.obs["total_counts"] > thresholds["upper_counts"]
                                    mt_filter = adata.obs["pct_counts_mt"] > thresholds["mt_pct_threshold"]
                                    doublet_filter = adata.obs["predicted_doublets"]

                                # Create overall filter
                                adata.obs["filter_all"] = gene_filter | counts_filter | mt_filter | doublet_filter
                                adata_processed.obs["filter_all"] = adata.obs["filter_all"]

                                # Store QC thresholds in processed adata for UMAP visualization
                                adata_processed.uns["qc_lower_genes"] = thresholds["lower_genes"]
                                adata_processed.uns["qc_upper_genes"] = thresholds["upper_genes"]
                                adata_processed.uns["qc_upper_counts"] = thresholds["upper_counts"]
                                adata_processed.uns["qc_mt_threshold"] = thresholds["mt_pct_threshold"]

                                # Generate traditional QC plots
                                plot_file = _generate_qc_plots(adata, sample_id, path.data_sample, thresholds)
                                console.print(f"[green]✓ QC plots saved to: {os.path.dirname(plot_file)}[/green]")

                                # Generate UMAP plots
                                _generate_umap_plots(adata_processed, sample_id, path.data_sample)
                                console.print("[green]✓ UMAP plots generated[/green]")

                            except Exception as e:
                                console.print(f"[yellow]⚠ Warning: Could not generate QC plots for {sample_id}: {e}[/yellow]")

                    except Exception as e:
                        console.print(f"[yellow]⚠ Warning: Could not complete preprocessing pipeline for {sample_id}: {e}[/yellow]")

                    # Log filtering statistics
                    total_cells = len(obs)
                    remaining_cells = obs.filter(pl.col("include")).height
                    console.print(f"[green]✓ Sample {sample_id}: {remaining_cells}/{total_cells} cells passed filtering ({100 * remaining_cells / total_cells:.1f}%)[/green]")

                else:
                    console.print(f"[red]✗ Sample {sample_id}: Count data not found. Expected file: {path.resources_sample_counted}/outs/filtered_feature_bc_matrix.h5[/red]")
                    console.print("[dim]Please run the counting pipeline (e.g., Cell Ranger) first.[/dim]")

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        """Add CLI arguments for the Preprocess function."""
        parser.add_argument("--target-celltype", "-t", nargs="+", help="Target cell types to include in preprocessing")
        parser.add_argument("--mt-pct-threshold", type=float, default=5.0, help="Mitochondrial percentage threshold for filtering cells (default: 5.0)")
        parser.add_argument("--n-mad", type=float, default=2.5, help="Number of MADs for outlier detection in dynamic thresholding (default: 2.5)")
        parser.add_argument("--mt-prefix", type=str, default="mt-", help='Mitochondrial gene prefix (case-insensitive matching) (default: "mt-")')
        parser.add_argument("--no-plots", action="store_true", help="Disable QC plot generation")

    def cli(self, project, args: argparse.Namespace | None = None):
        """CLI entry point for Preprocess function."""
        # Extract arguments with defaults
        target_celltype = None
        mt_pct_threshold = 5.0
        n_mad = 2.5
        mt_prefix = "mt-"
        generate_plots = True

        if args:
            if hasattr(args, "target_celltype"):
                target_celltype = args.target_celltype
            if hasattr(args, "mt_pct_threshold"):
                mt_pct_threshold = args.mt_pct_threshold
            if hasattr(args, "n_mad"):
                n_mad = args.n_mad
            if hasattr(args, "mt_prefix"):
                mt_prefix = args.mt_prefix
            if hasattr(args, "no_plots"):
                generate_plots = not args.no_plots

        console.print("[cyan]Starting preprocessing with dynamic thresholding...[/cyan]")
        if target_celltype:
            console.print(f"Target cell types: {', '.join(target_celltype)}")
        console.print(f"MT percentage threshold: {mt_pct_threshold}%")
        console.print(f"MAD multiplier: {n_mad}")
        console.print(f"MT prefix: '{mt_prefix}' (case-insensitive)")
        console.print(f"Generate QC plots: {'Yes' if generate_plots else 'No'}")

        preprocess_instance = Preprocess(target_celltype=target_celltype, mt_pct_threshold=mt_pct_threshold, n_mad=n_mad, mt_prefix=mt_prefix, generate_plots=generate_plots)
        return preprocess_instance.call(project)

    def get_description(self) -> str:
        return """Preprocess counted data with dynamic quality control and cell type filtering.

This function performs quality control on counted data using dynamic thresholding based on
Median Absolute Deviation (MAD), calculates QC metrics, detects doublets, and filters cells
based on configurable criteria."""

    def get_usage_examples(self) -> list[str]:
        return [
            "celline run preprocess",
            "celline run preprocess --target-celltype Neuron Astrocyte",
            "celline run preprocess --mt-pct-threshold 10 --n-mad 3.0",
            "celline run preprocess --mt-prefix MT- --n-mad 2.0",
            "celline run preprocess --no-plots",
        ]
