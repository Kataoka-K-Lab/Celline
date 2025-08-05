import argparse
import hashlib
import os
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path as PathLib
from typing import TYPE_CHECKING, Dict, Final, List, NamedTuple, Optional, Tuple

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
    mode: str = "canonical"  # "canonical" or "reference"
    
    def get_cache_key(self) -> str:
        """Generate cache key for this model configuration"""
        key_parts = [self.species.replace(" ", "_"), self.mode]
        if self.suffix:
            key_parts.append(self.suffix)
        return "_".join(key_parts)
    
    def get_reference_dir(self) -> str:
        """Get reference directory path"""
        base_dir = f"{Config.PROJ_ROOT}/reference/{self.species.replace(' ', '_')}"
        if self.suffix:
            return f"{base_dir}/{self.suffix}"
        return f"{base_dir}/default"


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


class ReferenceManager:
    """Manages reference models for different species/tissues/modes"""
    
    def __init__(self):
        self.base_cache_dir = f"{Config.PROJ_ROOT}/reference"
        os.makedirs(self.base_cache_dir, exist_ok=True)
    
    def get_reference_path(self, model: CellTypeModel) -> str:
        """Get path for reference model"""
        return model.get_reference_dir()
    
    def reference_exists(self, model: CellTypeModel) -> bool:
        """Check if reference model exists"""
        ref_dir = self.get_reference_path(model)
        if model.mode == "reference":
            return (os.path.exists(f"{ref_dir}/reference.pred") and 
                   os.path.exists(f"{ref_dir}/reference.h5seurat"))
        return True  # Canonical mode doesn't need reference files
    
    def get_compatible_samples(self, model: CellTypeModel) -> List[str]:
        """Get samples compatible with this model"""
        compatible_samples = []
        for sample in SampleResolver.samples.values():
            if (sample.schema.species.replace(" ", "_") == 
                model.species.replace(" ", "_")):
                compatible_samples.append(sample.schema.key)
        return compatible_samples
    
    def create_reference_hash(self, h5matrix_path: str, celltype_path: str) -> str:
        """Create hash for reference data to detect changes"""
        hash_md5 = hashlib.md5()
        # Hash file paths and modification times
        content = f"{h5matrix_path}_{os.path.getmtime(h5matrix_path) if os.path.exists(h5matrix_path) else 0}"
        content += f"{celltype_path}_{os.path.getmtime(celltype_path) if os.path.exists(celltype_path) else 0}"
        hash_md5.update(content.encode('utf-8'))
        return hash_md5.hexdigest()[:8]


class BuildCellTypeReference(CellineFunction):
    """Build scPred reference model for cell type prediction"""
    
    class JobContainer(NamedTuple):
        nthread: str
        cluster_server: str
        jobname: str
        logpath: str
        h5matrix_path: str
        celltype_path: str
        dist_dir: str
        r_path: str
        exec_root: str
        mode: str
    
    def __init__(self, species: str, suffix: Optional[str], nthread: int, 
                 h5matrix_path: str, celltype_path: str, mode: str = "reference") -> None:
        # Validation
        if not celltype_path.endswith(".tsv"):
            rich.print("[bold red]Build Error[/] celltype_path should be .tsv file path.")
            self.__show_help()
            sys.exit(1)
            
        _df = pl.read_csv(celltype_path, separator="\t")
        expected_cols = ["cell", "celltype"] if mode == "reference" else ["cell", "celltype"]
        if _df.columns != expected_cols:
            rich.print(f"[bold red]Build Error[/] celltype dataframe should have columns: {expected_cols}")
            self.__show_help()
            sys.exit(1)
            
        self.model = CellTypeModel(species, suffix, mode)
        self.nthread = nthread
        self.cluster_server = ServerSystem.cluster_server_name
        self.h5matrix_path = h5matrix_path
        self.celltype_path = celltype_path
        self.reference_manager = ReferenceManager()
    
    def __show_help(self):
        df = pd.DataFrame({
            "cell": ["cell_1", "cell_2", "cell_3"],
            "celltype": ["Astrocyte", "Oligodendrocyte", "Neuron"]
        })
        table = Table(show_header=True, header_style="bold magenta")
        for column in df.columns:
            table.add_column(column)
        for _, row in df.iterrows():
            table.add_row(*row.astype(str).tolist())
        
        rich.print("""
[bold green]:robot: Reference Model Builder[/]

* [bold]h5matrix_path<str>[/]: H5 matrix path from Cell Ranger
* [bold]celltype_path<str>[/]: Cell type annotations in TSV format
""")
        console.print(table)
    
    def call(self, project: "Project"):
        dist_dir = self.reference_manager.get_reference_path(self.model)
        
        # Create hash for reference data versioning
        ref_hash = self.reference_manager.create_reference_hash(
            self.h5matrix_path, self.celltype_path)
        hash_file = f"{dist_dir}/reference.hash"
        
        # Check if rebuild is needed
        rebuild_needed = True
        if os.path.exists(hash_file):
            with open(hash_file, 'r') as f:
                existing_hash = f.read().strip()
            if existing_hash == ref_hash and self.reference_manager.reference_exists(self.model):
                rebuild_needed = False
                console.print(f"[green]Reference model is up to date: {dist_dir}[/green]")
        
        if rebuild_needed:
            # Clean and recreate directory
            if os.path.exists(dist_dir):
                shutil.rmtree(dist_dir)
            os.makedirs(dist_dir, exist_ok=True)
            
            console.print(f"[cyan]Building reference model: {self.model.get_cache_key()}[/cyan]")
            
            # Generate build script
            TemplateManager.replace_from_file(
                file_name="build_reference_scpred.sh",
                structure=self.JobContainer(
                    nthread=str(self.nthread),
                    cluster_server="" if self.cluster_server is None else self.cluster_server,
                    jobname="BuildReferenceScPred",
                    logpath=f"{dist_dir}/build.log",
                    h5matrix_path=self.h5matrix_path,
                    dist_dir=dist_dir,
                    celltype_path=self.celltype_path,
                    r_path=f"{Setting.r_path}script",
                    exec_root=Config.EXEC_ROOT,
                    mode=self.model.mode
                ),
                replaced_path=f"{dist_dir}/build.sh"
            )
            
            # Execute build
            ThreadObservable.call_shell([f"{dist_dir}/build.sh"]).watch()
            
            # Save hash
            with open(hash_file, 'w') as f:
                f.write(ref_hash)
                
            console.print(f"[green]Reference model built successfully: {dist_dir}[/green]")
        
        return project


class PredictCelltype(CellineFunction):
    """Dual-mode cell type prediction with canonical marker-based and reference scPred modes
    
    Modes:
    - canonical: Original marker-based weighted scoring (default)
    - reference: scPred reference-based prediction using trained models
    """

    def __init__(self, marker_path: str | None = None, abs_threshold: float = 0.08, 
                 force_rerun: bool = False, mode: str = "canonical", 
                 species: str = "Homo sapiens", suffix: str | None = None) -> None:
        self.mode = mode
        self.marker_path = marker_path
        self.abs_threshold = abs_threshold
        self.force_rerun = force_rerun
        self.species = species
        self.suffix = suffix
        
        # Initialize managers for reference mode
        self.reference_manager = ReferenceManager()
        
        # Validate mode
        if self.mode not in ["canonical", "reference"]:
            raise ValueError(f"Invalid mode '{self.mode}'. Must be 'canonical' or 'reference'")
        
        # For reference mode, check if reference exists
        if self.mode == "reference":
            self.model = CellTypeModel(species, suffix, mode)
            if not self.reference_manager.reference_exists(self.model):
                console.print(f"[yellow]Warning: Reference model not found for {self.model.get_cache_key()}[/yellow]")
                console.print(f"[cyan]Please build reference first using BuildCellTypeReference[/cyan]")

    def register(self) -> str:
        return "predict_celltype"

    def call(self, project: "Project"):
        if self.mode == "canonical":
            return self._run_canonical_mode(project)
        elif self.mode == "reference":
            return self._run_reference_mode(project)
        else:
            raise ValueError(f"Unsupported mode: {self.mode}")
    
    def _run_canonical_mode(self, project: "Project"):
        """Run original marker-based prediction"""
        console.print(f"[cyan]Running canonical marker-based prediction...[/cyan]")
        
        for sample in SampleResolver.samples.values():
            if not sample.path.is_counted:
                continue
            try:
                predict_celltype_with_annotation(
                    sample, 
                    marker_path=self.marker_path, 
                    abs_threshold=self.abs_threshold, 
                    force_rerun=self.force_rerun
                )
            except Exception as e:
                print(f"Failed {sample.schema.key}: {e}")
        return project
    
    def _run_reference_mode(self, project: "Project"):
        """Run scPred reference-based prediction"""
        console.print(f"[cyan]Running reference-based scPred prediction...[/cyan]")
        
        # Check if reference model exists
        if not self.reference_manager.reference_exists(self.model):
            console.print(f"[red]Error: Reference model not found for {self.model.get_cache_key()}[/red]")
            console.print(f"[cyan]Build reference first using: celline run build_reference --species '{self.species}' --suffix {self.suffix or 'default'}[/cyan]")
            return project
        
        # Get compatible samples for this reference
        compatible_samples = self._get_compatible_samples_for_reference()
        
        if not compatible_samples:
            console.print(f"[yellow]No compatible samples found for species '{self.species}'[/yellow]")
            return project
        
        console.print(f"[green]Found {len(compatible_samples)} compatible samples[/green]")
        
        # Run scPred prediction for compatible samples
        successful_predictions = 0
        for sample_info in compatible_samples:
            try:
                if self.force_rerun or not self._has_scpred_results(sample_info):
                    if self._run_scpred_prediction(sample_info):
                        self._generate_scpred_plots(sample_info)
                        successful_predictions += 1
                else:
                    console.print(f"[dim]Skipping {sample_info.schema.key} (results exist)[/dim]")
                    successful_predictions += 1
            except Exception as e:
                console.print(f"[red]Failed {sample_info.schema.key}: {e}[/red]")
        
        console.print(f"[green]Successfully processed {successful_predictions}/{len(compatible_samples)} samples[/green]")
        return project
    
    def _get_compatible_samples_for_reference(self):
        """Get samples compatible with the current reference model"""
        compatible_samples = []
        
        for sample in SampleResolver.samples.values():
            if not sample.path.is_counted:
                continue
                
            # Check species compatibility
            sample_species = getattr(sample.schema, 'species', 'Unknown')
            if sample_species.replace(" ", "_") == self.species.replace(" ", "_"):
                compatible_samples.append(sample)
        
        return compatible_samples
    
    def _has_scpred_results(self, sample_info) -> bool:
        """Check if scPred results already exist for sample"""
        output_file = PathLib(sample_info.path.data_sample) / "celltype_predicted.tsv"
        seurat_file = PathLib(sample_info.path.data_sample) / "seurat.rds"
        
        return output_file.exists() and seurat_file.exists()
    
    def _run_scpred_prediction(self, sample_info) -> bool:
        """Run scPred prediction for a single sample using R script"""
        try:
            sample_id = sample_info.schema.key
            project_id = sample_info.schema.project_key
            
            console.print(f"[cyan]Running scPred prediction for {sample_id}...[/cyan]")
            
            # Get reference paths
            ref_dir = self.reference_manager.get_reference_path(self.model)
            reference_seurat = f"{ref_dir}/reference.h5seurat"
            reference_pred = f"{ref_dir}/reference.pred"
            
            if not os.path.exists(reference_seurat) or not os.path.exists(reference_pred):
                console.print(f"[red]Reference files not found in {ref_dir}[/red]")
                return False
            
            # Prepare paths for R script
            resources_path = str(PathLib(sample_info.path.resources_sample_counted).parent.parent.parent)
            data_path = str(PathLib(sample_info.path.data_sample).parent.parent)
            
            # Create shell script from template
            script_content = self._generate_scpred_script(
                reference_seurat=reference_seurat,
                reference_pred=reference_pred,
                project_id=project_id,
                sample_id=sample_id,
                resources_path=resources_path,
                data_path=data_path
            )
            
            # Write and execute script
            script_path = PathLib(sample_info.path.data_sample) / "run_scpred.sh"
            with open(script_path, 'w') as f:
                f.write(script_content)
            
            os.chmod(script_path, 0o755)
            
            # Execute the script
            ThreadObservable.call_shell([str(script_path)]).watch()
            
            # Check if results were created
            return self._has_scpred_results(sample_info)
            
        except Exception as e:
            console.print(f"[red]scPred prediction failed for {sample_info.schema.key}: {e}[/red]")
            return False
    
    def _generate_scpred_script(self, reference_seurat: str, reference_pred: str, 
                              project_id: str, sample_id: str, resources_path: str, 
                              data_path: str) -> str:
        """Generate shell script for scPred prediction"""
        return f"""#!/bin/bash
# scPred Prediction Script for {sample_id}
set -e

cd {Config.EXEC_ROOT}

# Run scPred prediction using existing R script
Rscript {Setting.r_path}script/run_scpred.R \\
    {reference_seurat} \\
    {reference_pred} \\
    {project_id} \\
    {sample_id} \\
    {resources_path} \\
    {data_path}

echo "scPred prediction completed for {sample_id}"
"""
    
    def _generate_scpred_plots(self, sample_info):
        """Generate comprehensive plots for scPred results"""
        try:
            sample_id = sample_info.schema.key
            
            # Check if Seurat object exists
            seurat_file = PathLib(sample_info.path.data_sample) / "seurat.rds"
            if not seurat_file.exists():
                console.print(f"[yellow]No Seurat object found for plotting: {sample_id}[/yellow]")
                return
            
            # Setup figure directories
            figures_dir = PathLib(sample_info.path.data_sample) / "figures"
            celltype_dir = figures_dir / "celltype"
            scpred_dir = celltype_dir / "scpred"
            
            for dir_path in [figures_dir, celltype_dir, scpred_dir]:
                dir_path.mkdir(parents=True, exist_ok=True)
            
            # Generate R plotting script
            plot_script_content = self._generate_scpred_plot_script(
                seurat_file=str(seurat_file),
                sample_id=sample_id,
                output_dir=str(scpred_dir)
            )
            
            # Write and execute plotting script
            plot_script_path = PathLib(sample_info.path.data_sample) / "plot_scpred.R"
            with open(plot_script_path, 'w') as f:
                f.write(plot_script_content)
            
            # Execute plotting script
            cmd = f"cd {Config.EXEC_ROOT} && Rscript {plot_script_path}"
            ThreadObservable.call_shell([cmd]).watch()
            
            console.print(f"[green]Generated scPred plots for {sample_id}[/green]")
            
        except Exception as e:
            console.print(f"[yellow]Plot generation failed for {sample_info.schema.key}: {e}[/yellow]")
    
    def _generate_scpred_plot_script(self, seurat_file: str, sample_id: str, output_dir: str) -> str:
        """Generate R script for scPred plotting"""
        return f"""# scPred Plotting Script for {sample_id}
pacman::p_load(Seurat, scPred, tidyverse, ggplot2)

# Load Seurat object with scPred results
seurat_obj <- readRDS("{seurat_file}")

# Set output directory
output_dir <- "{output_dir}"

# Plot 1: scPred UMAP with predictions
p1 <- DimPlot(seurat_obj, reduction = "scpred", group.by = "scpred_prediction", 
              label = TRUE, label.size = 3) +
      ggtitle("scPred Cell Type Predictions") +
      theme_minimal()

ggsave(file.path(output_dir, "{sample_id}_scpred_predictions.png"), 
       p1, width = 12, height = 8, dpi = 300)

# Plot 2: scPred confidence scores
if ("scpred_max" %in% colnames(seurat_obj@meta.data)) {{
    p2 <- FeaturePlot(seurat_obj, reduction = "scpred", features = "scpred_max") +
          ggtitle("scPred Confidence Scores") +
          theme_minimal()
    
    ggsave(file.path(output_dir, "{sample_id}_scpred_confidence.png"), 
           p2, width = 12, height = 8, dpi = 300)
}}

# Plot 3: Cell type composition
pred_counts <- table(seurat_obj@meta.data$scpred_prediction)
pred_df <- data.frame(
    CellType = names(pred_counts),
    Count = as.numeric(pred_counts)
)

p3 <- ggplot(pred_df, aes(x = reorder(CellType, Count), y = Count, fill = CellType)) +
      geom_bar(stat = "identity") +
      coord_flip() +
      labs(title = "Cell Type Composition (scPred)", 
           x = "Cell Type", y = "Number of Cells") +
      theme_minimal() +
      theme(legend.position = "none")

ggsave(file.path(output_dir, "{sample_id}_scpred_composition.png"), 
       p3, width = 10, height = 6, dpi = 300)

# Plot 4: Comparison with original UMAP if available
if ("umap" %in% names(seurat_obj@reductions)) {{
    p4 <- DimPlot(seurat_obj, reduction = "umap", group.by = "scpred_prediction", 
                  label = TRUE, label.size = 3) +
          ggtitle("scPred Predictions on Original UMAP") +
          theme_minimal()
    
    ggsave(file.path(output_dir, "{sample_id}_original_umap_predictions.png"), 
           p4, width = 12, height = 8, dpi = 300)
}}

cat("scPred plots generated successfully for {sample_id}\\n")
"""

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        parser.add_argument("--mode", type=str, choices=["canonical", "reference"], default="canonical", 
                          help="Prediction mode: 'canonical' (marker-based, default) or 'reference' (scPred-based)")
        parser.add_argument("--marker-path", type=str, help="Path to marker gene file (CSV/TSV) for canonical mode")
        parser.add_argument("--abs-threshold", type=float, default=0.08, help="Absolute threshold for canonical mode (default: 0.08)")
        parser.add_argument("--species", type=str, default="Homo sapiens", help="Species for reference mode (default: 'Homo sapiens')")
        parser.add_argument("--suffix", type=str, help="Reference suffix for reference mode (optional)")
        parser.add_argument("--force-rerun", action="store_true", help="Force rerun even if output exists")

    def cli(self, project, args: argparse.Namespace | None = None):
        # Default values
        mode = "canonical"
        marker_path = None
        abs_threshold = 0.08
        species = "Homo sapiens"
        suffix = None
        force_rerun = False

        if args:
            if hasattr(args, "mode"):
                mode = args.mode
            if hasattr(args, "marker_path"):
                marker_path = args.marker_path
            if hasattr(args, "abs_threshold"):
                abs_threshold = args.abs_threshold
            if hasattr(args, "species"):
                species = args.species
            if hasattr(args, "suffix"):
                suffix = args.suffix
            if hasattr(args, "force_rerun"):
                force_rerun = args.force_rerun

        console.print(f"[cyan]Starting cell type prediction in {mode} mode...[/cyan]")
        
        if mode == "canonical":
            if marker_path:
                console.print(f"Using marker file: {marker_path}")
            else:
                console.print("No marker file provided - using clustering only")
            console.print(f"Annotation threshold: {abs_threshold}")
        elif mode == "reference":
            console.print(f"Using reference model for species: {species}")
            if suffix:
                console.print(f"Reference suffix: {suffix}")

        predict_instance = PredictCelltype(
            mode=mode,
            marker_path=marker_path, 
            abs_threshold=abs_threshold, 
            species=species,
            suffix=suffix,
            force_rerun=force_rerun
        )
        return predict_instance.call(project)

    def get_description(self) -> str:
        return """Dual-mode cell type prediction with comprehensive visualization.

Modes:
1. Canonical (default): Marker-based weighted scoring
   - Load h5 + cell_info.tsv
   - QC filtering and preprocessing  
   - HVG → normalize → log1p → scale → PCA → neighbors → UMAP → Leiden
   - Marker-based cell type annotation (if marker file provided)
   - Generate comprehensive plots

2. Reference: scPred reference-based prediction
   - Use pre-trained scPred reference models
   - Project query data onto reference feature space
   - Predict cell types using trained classifiers
   - Generate reference-based visualizations

Output structure: data/{sample}/figures/celltype/{umap,scores}/"""

    def get_usage_examples(self) -> list[str]:
        return [
            # Canonical mode examples
            "celline run predict_celltype",
            "celline run predict_celltype --mode canonical --marker-path markers.csv",
            "celline run predict_celltype --marker-path markers.tsv --abs-threshold 0.1",
            
            # Reference mode examples  
            "celline run predict_celltype --mode reference --species 'Homo sapiens'",
            "celline run predict_celltype --mode reference --species 'Mus musculus' --suffix brain",
            "celline run predict_celltype --mode reference --force-rerun",
        ]
