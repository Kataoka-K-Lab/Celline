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

if TYPE_CHECKING:
    pass

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
    plt.style.use('default')
    sns.set_palette("husl")
    
    # Create figure with subplots
    fig, axes = plt.subplots(2, 3, figsize=(18, 12))
    fig.suptitle(f'QC Metrics for Sample: {sample_id}', fontsize=16, fontweight='bold')
    
    # 1. Number of genes per cell
    ax = axes[0, 0]
    n_genes = adata.obs['n_genes_by_counts']
    ax.hist(n_genes, bins=50, alpha=0.7, color='skyblue', edgecolor='black')
    ax.axvline(thresholds['lower_genes'], color='red', linestyle='--', linewidth=2, label=f'Lower: {thresholds["lower_genes"]:.0f}')
    ax.axvline(thresholds['upper_genes'], color='red', linestyle='--', linewidth=2, label=f'Upper: {thresholds["upper_genes"]:.0f}')
    ax.axvline(np.median(n_genes), color='orange', linestyle='-', linewidth=2, label=f'Median: {np.median(n_genes):.0f}')
    ax.set_xlabel('Number of genes per cell')
    ax.set_ylabel('Frequency')
    ax.set_title('Gene Complexity Distribution')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # 2. Total counts per cell
    ax = axes[0, 1]
    total_counts = adata.obs['total_counts']
    ax.hist(total_counts, bins=50, alpha=0.7, color='lightgreen', edgecolor='black')
    ax.axvline(thresholds['upper_counts'], color='red', linestyle='--', linewidth=2, label=f'Upper: {thresholds["upper_counts"]:.0f}')
    ax.axvline(np.median(total_counts), color='orange', linestyle='-', linewidth=2, label=f'Median: {np.median(total_counts):.0f}')
    ax.set_xlabel('Total counts per cell')
    ax.set_ylabel('Frequency')
    ax.set_title('Total Counts Distribution')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # 3. Mitochondrial percentage
    ax = axes[0, 2]
    mt_pct = adata.obs['pct_counts_mt']
    ax.hist(mt_pct, bins=50, alpha=0.7, color='salmon', edgecolor='black')
    ax.axvline(thresholds['mt_pct_threshold'], color='red', linestyle='--', linewidth=2, label=f'Threshold: {thresholds["mt_pct_threshold"]:.1f}%')
    ax.axvline(np.median(mt_pct), color='orange', linestyle='-', linewidth=2, label=f'Median: {np.median(mt_pct):.1f}%')
    ax.set_xlabel('Mitochondrial gene percentage (%)')
    ax.set_ylabel('Frequency')
    ax.set_title('Mitochondrial Gene Expression')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # 4. Doublet scores
    ax = axes[1, 0]
    doublet_scores = adata.obs['doublet_score']
    ax.hist(doublet_scores, bins=50, alpha=0.7, color='mediumpurple', edgecolor='black')
    ax.axvline(np.median(doublet_scores), color='orange', linestyle='-', linewidth=2, label=f'Median: {np.median(doublet_scores):.3f}')
    if 'scrublet_threshold' in thresholds:
        ax.axvline(thresholds['scrublet_threshold'], color='red', linestyle='--', linewidth=2, label=f'Threshold: {thresholds["scrublet_threshold"]:.3f}')
    ax.set_xlabel('Doublet Score')
    ax.set_ylabel('Frequency')
    ax.set_title('Scrublet Doublet Scores')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # 5. Scatter plot: Total counts vs Genes
    ax = axes[1, 1]
    passed_filter = ~adata.obs.get('filter_all', False) if 'filter_all' in adata.obs else np.ones(len(adata.obs), dtype=bool)
    
    # Plot filtered cells in red, passed cells in blue
    ax.scatter(total_counts[~passed_filter], n_genes[~passed_filter], 
              alpha=0.6, s=1, color='red', label='Filtered')
    ax.scatter(total_counts[passed_filter], n_genes[passed_filter], 
              alpha=0.6, s=1, color='blue', label='Passed')
    
    ax.set_xlabel('Total counts per cell')
    ax.set_ylabel('Number of genes per cell')
    ax.set_title('Total Counts vs Gene Complexity')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    # 6. Scatter plot: MT% vs Total counts
    ax = axes[1, 2]
    ax.scatter(total_counts[~passed_filter], mt_pct[~passed_filter], 
              alpha=0.6, s=1, color='red', label='Filtered')
    ax.scatter(total_counts[passed_filter], mt_pct[passed_filter], 
              alpha=0.6, s=1, color='blue', label='Passed')
    
    ax.set_xlabel('Total counts per cell')
    ax.set_ylabel('Mitochondrial gene percentage (%)')
    ax.set_title('Total Counts vs Mitochondrial Expression')
    ax.legend()
    ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    
    # Save the plot
    plot_file = os.path.join(plots_dir, f'{sample_id}_qc_overview.png')
    plt.savefig(plot_file, dpi=300, bbox_inches='tight')
    plt.close()
    
    # Generate summary statistics plot
    _generate_qc_summary_plot(adata, sample_id, plots_dir, thresholds)
    
    return plot_file


def _generate_qc_summary_plot(adata, sample_id: str, plots_dir: str, thresholds: dict):
    """Generate QC summary bar plot"""
    # Calculate filtering statistics
    total_cells = len(adata.obs)
    
    # Create filter columns if they don't exist
    gene_filter = ((adata.obs['n_genes_by_counts'] < thresholds['lower_genes']) | 
                   (adata.obs['n_genes_by_counts'] > thresholds['upper_genes']))
    counts_filter = adata.obs['total_counts'] > thresholds['upper_counts']
    mt_filter = adata.obs['pct_counts_mt'] > thresholds['mt_pct_threshold']
    doublet_filter = adata.obs['predicted_doublets']
    
    # Count filtered cells for each criterion
    stats = {
        'Gene Complexity': gene_filter.sum(),
        'Total Counts': counts_filter.sum(),
        'MT Percentage': mt_filter.sum(),
        'Doublets': doublet_filter.sum(),
        'Total Filtered': (gene_filter | counts_filter | mt_filter | doublet_filter).sum()
    }
    
    remaining_cells = total_cells - stats['Total Filtered']
    stats['Remaining'] = remaining_cells
    
    # Create summary plot
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))
    fig.suptitle(f'QC Summary for Sample: {sample_id}', fontsize=14, fontweight='bold')
    
    # Bar plot of filtered cells
    filter_categories = list(stats.keys())[:-1]  # Exclude 'Remaining'
    filter_counts = [stats[cat] for cat in filter_categories]
    filter_percentages = [100 * count / total_cells for count in filter_counts]
    
    bars1 = ax1.bar(filter_categories, filter_counts, color=['red', 'orange', 'purple', 'brown', 'darkred'])
    ax1.set_ylabel('Number of cells')
    ax1.set_title('Cells Filtered by Each Criterion')
    ax1.tick_params(axis='x', rotation=45)
    
    # Add percentage labels on bars
    for bar, pct in zip(bars1, filter_percentages):
        height = bar.get_height()
        ax1.text(bar.get_x() + bar.get_width()/2., height + total_cells*0.01,
                f'{pct:.1f}%', ha='center', va='bottom', fontweight='bold')
    
    # Pie chart of overall filtering
    pie_data = [stats['Remaining'], stats['Total Filtered']]
    pie_labels = [f'Passed\n({stats["Remaining"]} cells)', f'Filtered\n({stats["Total Filtered"]} cells)']
    colors = ['lightblue', 'lightcoral']
    
    wedges, texts, autotexts = ax2.pie(pie_data, labels=pie_labels, colors=colors, autopct='%1.1f%%',
                                       startangle=90, textprops={'fontweight': 'bold'})
    ax2.set_title('Overall Filtering Results')
    
    plt.tight_layout()
    
    # Save the summary plot
    summary_file = os.path.join(plots_dir, f'{sample_id}_qc_summary.png')
    plt.savefig(summary_file, dpi=300, bbox_inches='tight')
    plt.close()
    
    return summary_file


class Preprocess(CellineFunction):
    TARGET_CELLTYPE: Final[Optional[list[str]]]
    def __init__(self, target_celltype: Optional[list[str]] = None, 
                 mt_pct_threshold: float = 5.0, 
                 n_mad: float = 2.5,
                 mt_prefix: str = "mt-",
                 generate_plots: bool = True):
        """
        Initialize the Preprocess class.

        This constructor sets up the Preprocess object with an optional list of target cell types
        and dynamic filtering parameters.

        Parameters:
        -----------
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

        Returns:
        --------
        None
        """
        self.TARGET_CELLTYPE = target_celltype
        self.mt_pct_threshold = mt_pct_threshold
        self.n_mad = n_mad
        self.mt_prefix = mt_prefix
        self.generate_plots = generate_plots

    def call(self, project):
        """
        Perform preprocessing on the given project's samples.

        This function reads sample information from a TOML file, processes each sample,
        performs quality control, and generates cell information for further analysis.

        Parameters:
        -----------
        project : object
            The project object containing information about the samples to be processed.

        Returns:
        --------
        project : object
            The input project object, potentially modified during processing.

        Raises:
        -------
        ReferenceError
            If a sample ID cannot be resolved.
        KeyError
            If a sample's parent information is missing.
        """
        sample_info_file = f"{Config.PROJ_ROOT}/samples.toml"
        if not os.path.isfile(sample_info_file):
            print("sample.toml could not be found. Skipping.")
            return project
        with open(sample_info_file, mode="r", encoding="utf-8") as f:
            samples: Dict[str, str] = toml.load(f)
            for sample_id in samples:
                resolver = HandleResolver.resolve(sample_id)
                if resolver is None:
                    raise ReferenceError(
                        f"Could not resolve target sample id: {sample_id}"
                    )
                sample_schema: SampleSchema = resolver.sample.search(sample_id)
                if sample_schema.parent is None:
                    raise KeyError("Could not find parent")
                path = Path(sample_schema.parent, sample_id)
                path.prepare()
                if path.is_counted and path.is_predicted_celltype:
                    adata = sc.read_10x_h5(path.resources_sample_counted)
                    obs = (
                        pl.DataFrame(adata.obs.reset_index())
                        .rename({"index": "barcode"})
                        .with_columns(pl.lit(sample_schema.parent).alias("project"))
                        .with_columns(pl.lit(sample_id).alias("sample"))
                        .with_columns((pl.concat_str(pl.col("sample"), pl.cum_count("sample"), separator="_")).alias("cell"))
                        .join(
                            pl.read_csv(
                            path.data_sample_predicted_celltype,
                            separator="\t",
                            ).rename({"scpred_prediction": "cell_type"}),
                            on="cell",
                        )
                        .with_columns(
                            (pl.col("cell_type").is_in(obs.select(pl.col("cell_type")).unique().get_column("cell_type").to_list() if self.TARGET_CELLTYPE is None else self.TARGET_CELLTYPE)).alias("include")
                        )
                    )
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
                        obs
                        .with_columns(((pl.col("n_genes_by_counts") >= lower_genes) & pl.col("include")).alias("include"))
                        .with_columns(((pl.col("n_genes_by_counts") <= upper_genes) & pl.col("include")).alias("include"))
                        .with_columns(((pl.col("total_counts") <= upper_counts) & pl.col("include")).alias("include"))
                        .with_columns(((pl.col("pct_counts_mt") <= self.mt_pct_threshold) & pl.col("include")).alias("include"))
                        .with_columns(((pl.col("predicted_doublets") == False) & pl.col("include")).alias("include"))
                        .write_csv(f"{path.data_sample}/cell_info.tsv", separator="\t")
                    )
                    
                    # Generate QC plots (if enabled)
                    if self.generate_plots:
                        console.print(f"[dim]Generating QC plots for {sample_id}...[/dim]")
                        try:
                            # Prepare threshold data for plotting
                            thresholds = {
                                'lower_genes': lower_genes,
                                'upper_genes': upper_genes,
                                'upper_counts': upper_counts,
                                'mt_pct_threshold': self.mt_pct_threshold,
                                'scrublet_threshold': getattr(scrub, 'threshold_', None)
                            }
                            
                            # Add filter information to adata for visualization
                            gene_filter = ((adata.obs['n_genes_by_counts'] < lower_genes) | 
                                         (adata.obs['n_genes_by_counts'] > upper_genes))
                            counts_filter = adata.obs['total_counts'] > upper_counts
                            mt_filter = adata.obs['pct_counts_mt'] > self.mt_pct_threshold
                            doublet_filter = adata.obs['predicted_doublets']
                            
                            # Create overall filter
                            adata.obs['filter_all'] = (gene_filter | counts_filter | mt_filter | doublet_filter)
                            
                            plot_file = _generate_qc_plots(adata, sample_id, path.data_sample, thresholds)
                            console.print(f"[green]✓ QC plots saved to: {os.path.dirname(plot_file)}[/green]")
                            
                        except Exception as e:
                            console.print(f"[yellow]⚠ Warning: Could not generate QC plots for {sample_id}: {e}[/yellow]")
                    
                    # Log filtering statistics
                    total_cells = len(obs)
                    remaining_cells = obs.filter(pl.col("include")).height
                    filtered_cells = total_cells - remaining_cells
                    console.print(f"[green]✓ Sample {sample_id}: {remaining_cells}/{total_cells} cells passed filtering ({100*remaining_cells/total_cells:.1f}%)[/green]")

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        """Add CLI arguments for the Preprocess function."""
        parser.add_argument(
            '--target-celltype', '-t',
            nargs='+',
            help='Target cell types to include in preprocessing'
        )
        parser.add_argument(
            '--mt-pct-threshold',
            type=float,
            default=5.0,
            help='Mitochondrial percentage threshold for filtering cells (default: 5.0)'
        )
        parser.add_argument(
            '--n-mad',
            type=float,
            default=2.5,
            help='Number of MADs for outlier detection in dynamic thresholding (default: 2.5)'
        )
        parser.add_argument(
            '--mt-prefix',
            type=str,
            default="mt-",
            help='Mitochondrial gene prefix (case-insensitive matching) (default: "mt-")'
        )
        parser.add_argument(
            '--no-plots',
            action='store_true',
            help='Disable QC plot generation'
        )

    def cli(self, project, args: Optional[argparse.Namespace] = None):
        """CLI entry point for Preprocess function."""
        # Extract arguments with defaults
        target_celltype = None
        mt_pct_threshold = 5.0
        n_mad = 2.5
        mt_prefix = "mt-"
        generate_plots = True
        
        if args:
            if hasattr(args, 'target_celltype'):
                target_celltype = args.target_celltype
            if hasattr(args, 'mt_pct_threshold'):
                mt_pct_threshold = args.mt_pct_threshold
            if hasattr(args, 'n_mad'):
                n_mad = args.n_mad
            if hasattr(args, 'mt_prefix'):
                mt_prefix = args.mt_prefix
            if hasattr(args, 'no_plots'):
                generate_plots = not args.no_plots
            
        console.print("[cyan]Starting preprocessing with dynamic thresholding...[/cyan]")
        if target_celltype:
            console.print(f"Target cell types: {', '.join(target_celltype)}")
        console.print(f"MT percentage threshold: {mt_pct_threshold}%")
        console.print(f"MAD multiplier: {n_mad}")
        console.print(f"MT prefix: '{mt_prefix}' (case-insensitive)")
        console.print(f"Generate QC plots: {'Yes' if generate_plots else 'No'}")
        
        preprocess_instance = Preprocess(
            target_celltype=target_celltype,
            mt_pct_threshold=mt_pct_threshold,
            n_mad=n_mad,
            mt_prefix=mt_prefix,
            generate_plots=generate_plots
        )
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
            "celline run preprocess --no-plots"
        ]