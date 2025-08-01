import argparse
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path as PathLib
from typing import TYPE_CHECKING, Dict, Final, List, NamedTuple, Optional

import numpy as np
import pandas as pd
import polars as pl
import rich
import scanpy as sc
import scipy.sparse as sp
from rich.console import Console
from rich.table import Table
from scipy.stats import zscore

from celline.config import Config, Setting
from celline.functions._base import CellineFunction
from celline.middleware import ThreadObservable
from celline.sample import SampleResolver
from celline.server import ServerSystem
from celline.template import TemplateManager

if TYPE_CHECKING:
    from celline import Project

console = Console()


@dataclass
class CellTypeModel:
    species: str
    suffix: str | None


# =============================================================================
# Annotation functions (restored from working version)
# =============================================================================
def _prepare_marker_dict(
    marker_df: pl.DataFrame,
) -> dict[str, dict[str, list[tuple[str, float]]]]:
    """Convert marker DataFrame to direction and weight-preserving dictionary"""
    df = (
        marker_df.with_columns(
            pl.col("direction").fill_null("+"),
            pl.col("weight").cast(pl.Float64).fill_null(1.0),
        )
        .group_by(["cell_type", "direction"])
        .agg([pl.col("gene"), pl.col("weight")])
    )

    marker_dict: dict[str, dict[str, list[tuple[str, float]]]] = {}
    for row in df.iter_rows(named=True):
        ct, direction = row["cell_type"], row["direction"]
        genes, weights = row["gene"], row["weight"]

        if ct not in marker_dict:
            marker_dict[ct] = {"pos": [], "neg": []}
        key = "pos" if direction == "+" else "neg"
        marker_dict[ct][key] = list(zip(genes, weights, strict=False))
    return marker_dict


def _weighted_gene_score(
    adata: sc.AnnData,
    marker_dict: dict[str, dict[str, list[tuple[str, float]]]],
    layer: str | None = None,
    z_before: bool = True,
) -> None:
    """Calculate weighted gene scores for each cell type and add to adata.obs"""
    X = adata.layers[layer] if layer else adata.X
    X = X.toarray() if sp.issparse(X) else X  # type: ignore

    if z_before:
        X = zscore(X, axis=0, ddof=1, nan_policy="omit")
        X = np.nan_to_num(X, 0.0)

    gene2idx = {g: i for i, g in enumerate(adata.var_names)}

    for ct, gdict in marker_dict.items():
        pos = [(gene2idx[g], w) for g, w in gdict["pos"] if g in gene2idx]
        neg = [(gene2idx[g], w) for g, w in gdict["neg"] if g in gene2idx]
        if not pos and not neg:
            continue

        pos_score = X[:, [i for i, _ in pos]].dot(np.array([w for _, w in pos])) if pos else 0
        neg_score = X[:, [i for i, _ in neg]].dot(np.array([w for _, w in neg])) if neg else 0
        score = (pos_score - neg_score) / np.sqrt(len(pos) + len(neg))
        adata.obs[f"{ct}_wscore"] = score


def _assign_cluster_types_weighted(
    adata: sc.AnnData,
    weighted_cols: list[str],
    abs_threshold: float = 0.08,
) -> dict[str, str]:
    """Assign cell types to Leiden clusters based on average weighted scores"""
    cluster_scores = pd.DataFrame()
    for cluster in adata.obs["leiden"].unique():
        mean_scores = adata.obs.loc[
            adata.obs["leiden"] == cluster,
            weighted_cols,
        ].mean()
        cluster_scores = pd.concat([cluster_scores, mean_scores.to_frame(cluster).T])

    cluster_scores.index.name = "leiden"

    cluster_types: dict[str, str] = {}
    for cluster_id, row in cluster_scores.iterrows():
        max_score = row.max()
        if max_score < abs_threshold:
            cluster_types[cluster_id] = "Unknown"
        else:
            cluster_types[cluster_id] = row.idxmax().replace("_wscore", "")
    return cluster_types


def predict_celltype_with_annotation(sample_info, marker_path: str | None = None, abs_threshold: float = 0.08, force_rerun: bool = False):
    """Full cell type prediction with marker-based annotation and comprehensive plots"""
    sample_id = sample_info.schema.key
    path = sample_info.path

    count_file = f"{path.resources_sample_counted}/outs/filtered_feature_bc_matrix.h5"
    cell_info_file = PathLib(path.data_sample) / "cell_info.tsv"
    output_file = PathLib(path.data_sample) / "celltype_predicted.tsv"

    if not force_rerun and output_file.exists():
        return

    # Setup figure directories (improved structure)
    figures_dir = PathLib(path.data_sample) / "figures"
    celltype_dir = figures_dir / "celltype"
    umap_dir = celltype_dir / "umap"
    scores_dir = celltype_dir / "scores"

    for dir_path in [figures_dir, celltype_dir, umap_dir, scores_dir]:
        dir_path.mkdir(parents=True, exist_ok=True)

    sc.settings.figdir = str(figures_dir)

    # Set matplotlib params directly to avoid recursion issues
    import matplotlib

    matplotlib.rcParams["figure.dpi"] = 80
    matplotlib.rcParams["figure.facecolor"] = "white"

    # Data loading and preprocessing (same as successful version)
    adata = sc.read_10x_h5(count_file)
    adata.obs = pl.read_csv(str(cell_info_file), separator="\t").to_pandas().set_index("cell")
    adata = adata[adata.obs["include"]]
    adata.var_names_make_unique()

    sc.pp.highly_variable_genes(adata, flavor="seurat_v3", n_top_genes=2000, subset=True)
    sc.pp.normalize_total(adata, target_sum=1e4)
    sc.pp.log1p(adata)
    sc.pp.scale(adata, max_value=10)
    sc.tl.pca(adata, svd_solver="arpack")
    sc.pp.neighbors(adata, n_pcs=40, n_neighbors=15)
    sc.tl.umap(adata)
    sc.tl.leiden(adata, resolution=1.0)

    # Basic leiden clustering plot
    sc.pl.umap(adata, color=["leiden"], frameon=False, legend_loc="on data", save=f"{sample_id}_leiden_clusters.png", show=False)

    # Marker-based annotation if marker file provided
    if marker_path and os.path.exists(marker_path):
        try:
            # Load marker file
            if marker_path.endswith(".csv"):
                marker_df = pl.read_csv(marker_path)
            else:
                marker_df = pl.read_csv(marker_path, separator="\t")

            # Prepare marker dict and calculate scores
            marker_dict = _prepare_marker_dict(marker_df)
            _weighted_gene_score(adata, marker_dict)

            # Get weighted score columns
            weighted_cols = [col for col in adata.obs.columns if col.endswith("_wscore")]

            if weighted_cols:
                # Assign cell types to clusters
                cluster_types = _assign_cluster_types_weighted(adata, weighted_cols, abs_threshold)

                # Add cell type annotations
                adata.obs["cell_type_cluster_weighted"] = adata.obs["leiden"].map(cluster_types).fillna("Unknown")

                # Generate comprehensive plots
                _generate_comprehensive_plots(adata, sample_id, weighted_cols, umap_dir, scores_dir, celltype_dir, figures_dir)

                # Reset figdir
                sc.settings.figdir = str(figures_dir)
            else:
                print(f"Warning: No valid marker genes found for {sample_id}")
                adata.obs["cell_type_cluster_weighted"] = "Cluster_" + adata.obs["leiden"].astype(str)

        except Exception as e:
            print(f"Warning: Marker-based annotation failed for {sample_id}: {e}")
            adata.obs["cell_type_cluster_weighted"] = "Cluster_" + adata.obs["leiden"].astype(str)
    else:
        # No marker file provided, use cluster labels only
        adata.obs["cell_type_cluster_weighted"] = "Cluster_" + adata.obs["leiden"].astype(str)

    # Save results
    output_df = pd.DataFrame({"cell": adata.obs_names, "scpred_prediction": adata.obs["cell_type_cluster_weighted"]})
    output_df.to_csv(output_file, sep="\t", index=False)


def _generate_comprehensive_plots(adata, sample_id, weighted_cols, umap_dir, scores_dir, celltype_dir, figures_dir):
    """Generate comprehensive visualization plots"""
    # 1. Cell type UMAP plots (remove 'umap' prefix)
    sc.settings.figdir = str(umap_dir)

    # Main cell type plot
    sc.pl.umap(adata, color=["cell_type_cluster_weighted"], frameon=False, legend_loc="on data", save=f"_{sample_id}_cell_types.png", show=False)

    # Individual cell type plots
    cell_types = adata.obs["cell_type_cluster_weighted"].unique()
    for cell_type in cell_types:
        if cell_type != "Unknown":
            # Create binary mask for this cell type
            adata.obs[f"is_{cell_type}"] = (adata.obs["cell_type_cluster_weighted"] == cell_type).astype(int)
            sc.pl.umap(adata, color=[f"is_{cell_type}"], frameon=False, save=f"_{sample_id}_{cell_type}.png", show=False)

    # 2. Score plots (with per-celltype scaling)
    sc.settings.figdir = str(scores_dir)
    for ct_col in weighted_cols:
        cell_type = ct_col.replace("_wscore", "")
        # Scale scores for better visualization
        score_values = adata.obs[ct_col].values
        if score_values.max() != score_values.min():
            scaled_scores = (score_values - score_values.min()) / (score_values.max() - score_values.min())
            adata.obs[f"{cell_type}_scaled_score"] = scaled_scores
            sc.pl.umap(adata, color=[f"{cell_type}_scaled_score"], frameon=False, save=f"_{sample_id}_{cell_type}_score.png", show=False)

    # 3. Cell type summary plot
    sc.settings.figdir = str(celltype_dir)
    try:
        import matplotlib.pyplot as plt

        # Create cell type composition plot
        cell_type_counts = adata.obs["cell_type_cluster_weighted"].value_counts()
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(15, 6))

        # Pie chart
        ax1.pie(cell_type_counts.values, labels=cell_type_counts.index, autopct="%1.1f%%")
        ax1.set_title("Cell Type Composition")

        # Bar chart
        cell_type_counts.plot(kind="bar", ax=ax2)
        ax2.set_title("Cell Type Counts")
        ax2.set_xlabel("Cell Type")
        ax2.set_ylabel("Number of Cells")
        ax2.tick_params(axis="x", rotation=45)

        plt.tight_layout()
        plt.savefig(celltype_dir / f"{sample_id}_cell_type_summary.png", dpi=150, bbox_inches="tight")
        plt.close()
    except Exception as e:
        print(f"Warning: Could not generate cell type summary plot: {e}")

    # 4. Dotplot by clusters and cell types
    dotplot_dir = celltype_dir / "dotplot"
    dotplot_dir.mkdir(exist_ok=True)
    sc.settings.figdir = str(dotplot_dir)

    try:
        # Get actual marker genes from the weighted score calculations
        # Extract genes that are likely important for cell type distinction

        # Use highly variable genes for dotplot (most informative)
        if hasattr(adata.var, "highly_variable") and "highly_variable" in adata.var.columns:
            available_genes = adata.var_names[adata.var.highly_variable].tolist()[:30]
        else:
            available_genes = adata.var_names[:30].tolist()

        # Add some common marker genes if they exist in the data
        common_markers = [
            "HOPX",
            "SOX2",
            "PAX6",
            "FABP7",
            "TOP2A",
            "BIRC5",
            "MKI67",
            "EOMES",
            "SLC17A6",
            "SLC17A7",
            "GAD1",
            "GAD2",
            "TUBB3",
            "RBFOX3",
            "AQP4",
            "GFAP",
            "OLIG1",
            "OLIG2",
            "PLP1",
            "MBP",
            "CLDN5",
            "KDR",
        ]
        available_markers = [gene for gene in common_markers if gene in adata.var_names]

        # Combine and deduplicate
        all_genes = list(dict.fromkeys(available_markers + available_genes))[:25]
        available_genes = all_genes if all_genes else available_genes[:20]

        # Dotplot by Leiden clusters
        if len(available_genes) > 0:
            sc.pl.dotplot(adata, available_genes, groupby="leiden", save=f"_{sample_id}_clusters_dotplot.png", show=False)

            # Dotplot by cell types
            sc.pl.dotplot(adata, available_genes, groupby="cell_type_cluster_weighted", save=f"_{sample_id}_celltypes_dotplot.png", show=False)
    except Exception as e:
        print(f"Warning: Could not generate dotplots: {e}")

    # 5. Violin plots for top marker genes
    violin_dir = celltype_dir / "violin"
    violin_dir.mkdir(exist_ok=True)
    sc.settings.figdir = str(violin_dir)

    try:
        # Get some genes for violin plots
        available_genes = adata.var_names[:10].tolist()
        if available_genes:
            sc.pl.violin(adata, available_genes, groupby="cell_type_cluster_weighted", save=f"_{sample_id}_celltypes_violin.png", show=False)
    except Exception as e:
        print(f"Warning: Could not generate violin plots: {e}")

    # 6. Heatmap of marker gene expression
    heatmap_dir = celltype_dir / "heatmap"
    heatmap_dir.mkdir(exist_ok=True)
    sc.settings.figdir = str(heatmap_dir)

    try:
        # Create heatmap of top genes by cell type
        available_genes = adata.var_names[:20].tolist()
        if available_genes:
            sc.pl.heatmap(adata, available_genes, groupby="cell_type_cluster_weighted", save=f"_{sample_id}_celltypes_heatmap.png", show=False)
    except Exception as e:
        print(f"Warning: Could not generate heatmap: {e}")

    # 7. UMAP with QC metrics
    qc_dir = celltype_dir / "qc"
    qc_dir.mkdir(exist_ok=True)
    sc.settings.figdir = str(qc_dir)

    try:
        # Plot QC metrics if available
        qc_metrics = ["total_counts", "n_genes_by_counts", "pct_counts_mt"]
        available_qc = [metric for metric in qc_metrics if metric in adata.obs.columns]

        if available_qc:
            sc.pl.umap(adata, color=available_qc, save=f"_{sample_id}_qc_metrics.png", show=False)
    except Exception as e:
        print(f"Warning: Could not generate QC plots: {e}")


class BuildCellTypeModel(CellineFunction):
    """### Build cell type prediction model"""

    class JobContainer(NamedTuple):
        """Represents job information for data download."""

        nthread: str
        cluster_server: str
        jobname: str
        logpath: str
        h5matrix_path: str
        celltype_path: str
        dist_dir: str
        r_path: str
        exec_root: str

    def __init__(
        self,
        species: str,
        suffix: str,
        nthread: int,
        h5matrix_path: str,
        celltype_path: str,
    ) -> None:
        if not celltype_path.endswith(".tsv"):
            rich.print("[bold red]Build Error[/] celltype_path should be .tsv file path.")
            self.__show_help()
            sys.exit(1)
        _df = pl.read_csv(celltype_path, separator="\t")
        if _df.columns != ["cell", "celltype"]:
            rich.print("[bold red]Build Error[/] celltype dataframe should be composed of cell, celltype column.")
            self.__show_help()
            sys.exit(1)
        if not h5matrix_path.endswith(".h5") and not h5matrix_path.endswith(".loom") and not h5matrix_path.endswith(".h5seurat") and not h5matrix_path.endswith(".h5seuratv5"):
            rich.print("[bold red]Build Error[/] h5matrix_path should be .h5, h5seurat, h5seuratv5 or .loom file path.")
        self.model: Final[CellTypeModel] = CellTypeModel(species, suffix)
        self.nthread: Final[int] = nthread
        self.cluster_server: Final[str | None] = ServerSystem.cluster_server_name
        self.h5matrix_path: Final[str] = h5matrix_path
        self.celltype_path: Final[str] = celltype_path

    def __show_help(self):
        df = pd.DataFrame(
            {
                "cell": [
                    "10X82_2_TCTCTCACCAGTTA",
                    "10X82_2_TCTCTCACCAGTTC",
                    "10X82_2_TCTCTCACCAGTTT",
                ],
                "celltype": ["Astrocyte", "Oligodendrocyte", "Neuron"],
            },
            index=None,
        )
        table = Table(show_header=True, header_style="bold magenta")
        console = Console()
        for column in df.columns:
            table.add_column(column)
        for _, row in df.iterrows():
            table.add_row(*row.astype(str).tolist())
        rich.print(
            """
[bold green]:robot: How to use?[/]

* [bold]h5matrix_path<str>[/]: h5 matrix path. This data should be h5 matrix which be output from Cellranger.
* [bold]celltype_path<str>[/]: cell type path. This dataframe should be tsv format which have following dataframe structure.""",
        )
        console.print(table)

    def call(self, project: "Project"):
        dist_dir = f"{Config.PROJ_ROOT}/reference/{self.model.species.replace(' ', '_')}/{self.model.suffix if self.model.suffix is not None else 'default'}"
        if os.path.isdir(dist_dir) and not os.path.isfile(f"{dist_dir}/reference.pred") and not os.path.isfile(f"{dist_dir}/reference.h5seurat"):
            shutil.rmtree(dist_dir)
        os.makedirs(dist_dir, exist_ok=True)
        TemplateManager.replace_from_file(
            file_name="build_reference.sh",
            structure=BuildCellTypeModel.JobContainer(
                nthread=str(self.nthread),
                cluster_server="" if self.cluster_server is None else self.cluster_server,
                jobname="BuildCelltypeModel",
                logpath=f"{dist_dir}/build.log",
                h5matrix_path=self.h5matrix_path,
                dist_dir=dist_dir,
                celltype_path=self.celltype_path,
                r_path=f"{Setting.r_path}script",
                exec_root=Config.EXEC_ROOT,
            ),
            replaced_path=f"{dist_dir}/build.sh",
        )
        ThreadObservable.call_shell([f"{dist_dir}/build.sh"]).watch()
        return project


class PredictCelltype(CellineFunction):
    """Full cell type prediction with marker-based annotation"""

    def __init__(self, marker_path: str | None = None, abs_threshold: float = 0.08, force_rerun: bool = False) -> None:
        self.marker_path = marker_path
        self.abs_threshold = abs_threshold
        self.force_rerun = force_rerun

    def register(self) -> str:
        return "predict_celltype"

    def call(self, project: "Project"):
        for sample in SampleResolver.samples().values():
            if not sample.path.is_counted:
                continue
            try:
                predict_celltype_with_annotation(sample, marker_path=self.marker_path, abs_threshold=self.abs_threshold, force_rerun=self.force_rerun)
            except Exception as e:
                print(f"Failed {sample.schema.key}: {e}")
        return project

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--marker-path", type=str, help="Path to marker gene file (CSV/TSV) for cell type annotation")
        parser.add_argument("--abs-threshold", type=float, default=0.08, help="Absolute threshold for annotation confidence (default: 0.08)")
        parser.add_argument("--force-rerun", action="store_true", help="Force rerun even if output exists")

    def cli(self, project, args: argparse.Namespace | None = None):
        marker_path = None
        abs_threshold = 0.08
        force_rerun = False

        if args:
            if hasattr(args, "marker_path"):
                marker_path = args.marker_path
            if hasattr(args, "abs_threshold"):
                abs_threshold = args.abs_threshold
            if hasattr(args, "force_rerun"):
                force_rerun = args.force_rerun

        console.print("[cyan]Starting cell type prediction...[/cyan]")
        if marker_path:
            console.print(f"Using marker file: {marker_path}")
        else:
            console.print("No marker file provided - using clustering only")
        console.print(f"Annotation threshold: {abs_threshold}")

        predict_instance = PredictCelltype(marker_path=marker_path, abs_threshold=abs_threshold, force_rerun=force_rerun)
        return predict_instance.call(project)

    def get_description(self) -> str:
        return """Cell type prediction with marker-based annotation and comprehensive visualization.

This function performs complete single-cell analysis:
- Load h5 + cell_info.tsv
- QC filtering and preprocessing
- HVG → normalize → log1p → scale → PCA → neighbors → UMAP → Leiden
- Marker-based cell type annotation (if marker file provided)
- Generate comprehensive plots:
  * Leiden cluster plots
  * Cell type UMAP plots
  * Individual cell type plots
  * Marker score plots (per-celltype scaled)

Output structure: data/{sample}/figures/celltype/{umap,scores}/"""

    def get_usage_examples(self) -> list[str]:
        return [
            "celline run predict_celltype",
            "celline run predict_celltype --force-rerun",
            "celline run predict_celltype --marker-path markers.csv",
            "celline run predict_celltype --marker-path markers.tsv --abs-threshold 0.1",
        ]
