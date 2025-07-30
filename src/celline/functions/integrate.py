import argparse
import datetime
import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Final, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import scanpy as sc
import seaborn as sns
from rich.console import Console

from celline.config import Config
from celline.DB.dev.model import SampleSchema
from celline.functions._base import CellineFunction
from celline.sample import SampleInfo, SampleResolver

if TYPE_CHECKING:
    from celline import Project

console = Console()


class Integrate(CellineFunction):
    """Integration function with support for multiple methods (scVI, Harmony)."""
    
    def __init__(
        self,
        filter_func: Optional[Callable[[SampleSchema], bool]] = None,
        outfile_name: Optional[str] = None,
        integration_method: str = "harmony",
        n_pcs: int = 50,
        batch_key: str = "sample",
        scvi_epochs: int = 200,
        scvi_early_stopping: bool = True,
        harmony_vars_use: Optional[list[str]] = None,
        force_rerun: bool = False,
        verbose: bool = True,
    ) -> None:
        """
        Initialize the Integration class.

        Parameters:
        -----------
        filter_func : Optional[Callable[[SampleSchema], bool]], default=None
            Function to filter samples to include in integration.
        outfile_name : Optional[str], default=None
            Output file name. If None, uses timestamp.
        integration_method : str, default="harmony"
            Integration method to use ("scvi" or "harmony").
        n_pcs : int, default=50
            Number of principal components to use.
        batch_key : str, default="sample"
            Column name in obs containing batch information.
        scvi_epochs : int, default=200
            Number of training epochs for scVI.
        scvi_early_stopping : bool, default=True
            Whether to use early stopping in scVI training.
        harmony_vars_use : Optional[list[str]], default=None
            Variables to use for Harmony correction. If None, uses batch_key.
        force_rerun : bool, default=False
            Whether to force rerun even if cached results exist.
        verbose : bool, default=True
            Whether to show detailed progress.
        """
        self.filter_func = filter_func
        self.integration_method = integration_method.lower()
        self.n_pcs = n_pcs
        self.batch_key = batch_key
        self.scvi_epochs = scvi_epochs
        self.scvi_early_stopping = scvi_early_stopping
        self.harmony_vars_use = harmony_vars_use if harmony_vars_use else [batch_key]
        self.force_rerun = force_rerun
        self.verbose = verbose
        
        # Setup output path
        if outfile_name is None:
            timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            self.outfile_name = f"integrated_{self.integration_method}_{timestamp}"
        else:
            self.outfile_name = outfile_name
            
        self.output_dir = Path(Config.PROJ_ROOT) / "integration"
        # Note: output_path is now managed in _save_results with structured directories
        
        # Validate integration method
        if self.integration_method not in ["scvi", "harmony"]:
            raise ValueError(f"Integration method must be 'scvi' or 'harmony', got '{self.integration_method}'")

    def register(self) -> str:
        return "integrate"

    def call(self, project: "Project"):
        """
        Main integration pipeline.
        
        Parameters:
        -----------
        project : Project
            Celline project object.
            
        Returns:
        --------
        Project
            Input project object.
        """
        console.print(f"[cyan]Starting integration with {self.integration_method.upper()} method...[/cyan]")
        
        # Create output directories
        self.output_dir.mkdir(parents=True, exist_ok=True)
        (self.output_dir / "logs").mkdir(exist_ok=True)
        
        # Setup logging
        log_file = self.output_dir / "logs" / f"{self.outfile_name}.log"
        logging.basicConfig(
            level=logging.INFO if self.verbose else logging.WARNING,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler() if self.verbose else logging.NullHandler()
            ]
        )
        logger = logging.getLogger(__name__)
        
        try:
            # Check for cached results
            structured_data_dir = self.output_dir / self.outfile_name / "data"
            cached_file = structured_data_dir / f"{self.outfile_name}.h5ad"
            if not self.force_rerun and cached_file.exists():
                console.print(f"[green]✓ Found cached integration results at {cached_file}[/green]")
                console.print("[yellow]Use --force-rerun to recreate integration[/yellow]")
                return project
            
            # Collect target samples
            target_samples = self._collect_target_samples()
            if not target_samples:
                console.print("[red]❌ No valid samples found for integration[/red]")
                return project
                
            console.print(f"[green]Found {len(target_samples)} samples for integration[/green]")
            
            # Load and combine data
            adata_combined = self._load_and_combine_samples(target_samples, logger)
            
            # Perform integration
            if self.integration_method == "scvi":
                adata_integrated = self._integrate_scvi(adata_combined, logger)
            elif self.integration_method == "harmony":
                adata_integrated = self._integrate_harmony(adata_combined, logger)
            
            # Save results
            self._save_results(adata_integrated, logger)
            
            console.print(f"[green]✅ Integration completed successfully![/green]")
            console.print(f"[green]Results saved to: {self.output_dir / self.outfile_name}[/green]")
            
        except Exception as e:
            console.print(f"[red]❌ Integration failed: {e}[/red]")
            logger.error(f"Integration failed: {e}", exc_info=True)
            raise
            
        return project

    def _collect_target_samples(self) -> list[SampleInfo]:
        """Collect target samples based on filter function."""
        target_samples: list[SampleInfo] = []
        
        for info in SampleResolver.samples.values():
            if info.path.is_counted:
                if self.filter_func is None:
                    add = True
                else:
                    add = self.filter_func(info.schema)
                if add:
                    target_samples.append(info)
            else:
                console.print(
                    f"[yellow]⚠ Warning: Sample {info.schema.key} is not counted or preprocessed yet[/yellow]"
                )
        
        return target_samples

    def _load_and_combine_samples(self, target_samples: list[SampleInfo], logger: logging.Logger) -> sc.AnnData:
        """Load individual samples and combine them."""
        logger.info(f"Loading {len(target_samples)} samples...")
        console.print("[dim]Loading and combining samples...[/dim]")
        
        adata_list = []
        
        for i, sample_info in enumerate(target_samples, 1):
            console.print(f"[dim]Loading sample {i}/{len(target_samples)}: {sample_info.schema.key}[/dim]")
            
            # Load count matrix
            count_matrix_path = f"{sample_info.path.resources_sample_counted}/outs/filtered_feature_bc_matrix.h5"
            
            if not os.path.exists(count_matrix_path):
                logger.warning(f"Count matrix not found for {sample_info.schema.key}: {count_matrix_path}")
                continue
                
            adata = sc.read_10x_h5(count_matrix_path, var_names='gene_symbols', make_unique=True)
            
            # Add sample metadata
            adata.obs['sample'] = sample_info.schema.key
            adata.obs['project'] = sample_info.schema.parent or "Unknown"
            adata.obs['cell'] = [f"{sample_info.schema.key}_{i}" for i in range(len(adata.obs))]
            adata.obs_names = adata.obs['cell']
            
            # Load additional metadata if available
            self._load_additional_metadata(adata, sample_info, logger)
            
            adata_list.append(adata)
            logger.info(f"Loaded {sample_info.schema.key}: {adata.n_obs} cells × {adata.n_vars} genes")
        
        if not adata_list:
            raise ValueError("No valid samples could be loaded")
        
        # Combine all samples
        console.print("[dim]Concatenating samples...[/dim]")
        adata_combined = sc.concat(adata_list, join='outer')
        
        # Make variable names unique
        adata_combined.var_names_unique()
        
        logger.info(f"Combined data: {adata_combined.n_obs} cells × {adata_combined.n_vars} genes")
        console.print(f"[green]Combined data: {adata_combined.n_obs} cells × {adata_combined.n_vars} genes[/green]")
        
        return adata_combined

    def _load_additional_metadata(self, adata: sc.AnnData, sample_info: SampleInfo, logger: logging.Logger):
        """Load additional metadata files (cell type predictions, QC metrics, etc.)."""
        data_sample_dir = sample_info.path.data_sample
        
        # Load cell type predictions
        celltype_path = f"{data_sample_dir}/celltype_predicted.tsv"
        if os.path.exists(celltype_path):
            try:
                celltype_df = pd.read_csv(celltype_path, sep='\t')
                if 'cell' in celltype_df.columns:
                    celltype_dict = dict(zip(celltype_df['cell'], celltype_df.get('scpred_prediction', 'Unknown')))
                    adata.obs['cell_type'] = adata.obs['cell'].map(celltype_dict).fillna('Unknown')
                    logger.debug(f"Loaded cell type predictions for {sample_info.schema.key}")
            except Exception as e:
                logger.warning(f"Could not load cell type predictions for {sample_info.schema.key}: {e}")
        
        # Load QC metrics
        qc_path = f"{data_sample_dir}/qc_matrix.tsv"
        if os.path.exists(qc_path):
            try:
                qc_df = pd.read_csv(qc_path, sep='\t')
                # Map QC metrics by barcode or cell name
                for col in qc_df.columns:
                    if col not in ['cell', 'barcodes']:
                        if 'cell' in qc_df.columns:
                            qc_dict = dict(zip(qc_df['cell'], qc_df[col]))
                            adata.obs[col] = adata.obs['cell'].map(qc_dict)
                logger.debug(f"Loaded QC metrics for {sample_info.schema.key}")
            except Exception as e:
                logger.warning(f"Could not load QC metrics for {sample_info.schema.key}: {e}")

    def _integrate_scvi(self, adata: sc.AnnData, logger: logging.Logger) -> sc.AnnData:
        """Integrate data using scVI method."""
        try:
            import scvi
            import torch
        except ImportError:
            raise ImportError("scvi-tools package is required for scVI integration. Install with: pip install scvi-tools")
        
        logger.info("Starting scVI integration...")
        console.print("[dim]Performing scVI integration...[/dim]")
        
        # Setup scVI model
        logger.info("Setting up scVI model...")
        scvi.model.SCVI.setup_anndata(adata, batch_key=self.batch_key)
        
        # Create and train model
        model = scvi.model.SCVI(adata)
        logger.info(f"Training scVI model for {self.scvi_epochs} epochs...")
        console.print(f"[dim]Training scVI model ({self.scvi_epochs} epochs)...[/dim]")
        
        model.train(
            max_epochs=self.scvi_epochs,
            early_stopping=self.scvi_early_stopping,
            accelerator="cpu"
        )
        
        # Get latent representation
        logger.info("Extracting latent representation...")
        adata.obsm["X_scvi"] = model.get_latent_representation()
        
        # Compute neighbors and UMAP
        sc.pp.neighbors(adata, use_rep="X_scvi", n_pcs=self.n_pcs)
        sc.tl.umap(adata)
        sc.tl.leiden(adata, resolution=1.0, key_added='leiden_scvi')
        
        logger.info("scVI integration completed")
        console.print("[green]✓ scVI integration completed[/green]")
        
        return adata

    def _integrate_harmony(self, adata: sc.AnnData, logger: logging.Logger) -> sc.AnnData:
        """Integrate data using Harmony method."""
        try:
            import harmonypy as hm
        except ImportError:
            raise ImportError("harmonypy package is required for Harmony integration. Install with: pip install harmonypy")
        
        logger.info("Starting Harmony integration...")
        console.print("[dim]Performing Harmony integration...[/dim]")
        
        # Basic preprocessing
        logger.info("Performing basic preprocessing...")
        sc.pp.normalize_total(adata, target_sum=1e4)
        sc.pp.log1p(adata)
        sc.pp.highly_variable_genes(adata, n_top_genes=2000, batch_key=self.batch_key)
        adata.raw = adata
        adata = adata[:, adata.var.highly_variable]
        sc.pp.scale(adata, max_value=10)
        
        # PCA
        logger.info(f"Computing PCA with {self.n_pcs} components...")
        sc.tl.pca(adata, svd_solver='arpack', n_comps=self.n_pcs)
        
        # Prepare data for Harmony
        data_mat = adata.obsm['X_pca'].T  # Harmony expects genes x cells
        meta_data = adata.obs[self.harmony_vars_use].copy()
        
        # Run Harmony
        logger.info(f"Running Harmony with vars_use: {self.harmony_vars_use}")
        console.print(f"[dim]Running Harmony correction...[/dim]")
        
        ho = hm.run_harmony(data_mat, meta_data, self.harmony_vars_use)
        
        # Store corrected embedding
        adata.obsm['X_harmony'] = ho.Z_corr.T
        
        # Compute neighbors and UMAP using corrected embedding
        sc.pp.neighbors(adata, use_rep='X_harmony', n_pcs=self.n_pcs)
        sc.tl.umap(adata)
        sc.tl.leiden(adata, resolution=1.0, key_added='leiden_harmony')
        
        logger.info("Harmony integration completed")
        console.print("[green]✓ Harmony integration completed[/green]")
        
        return adata

    def _save_results(self, adata: sc.AnnData, logger: logging.Logger):
        """Save integrated results and generate plots."""
        main_output_dir = self.output_dir / self.outfile_name
        logger.info(f"Saving integrated data to {main_output_dir}")
        console.print(f"[dim]Saving results to {main_output_dir}...[/dim]")
        
        # Create structured output directories
        data_dir = self.output_dir / self.outfile_name / "data"
        figures_dir = self.output_dir / self.outfile_name / "figures"
        data_dir.mkdir(parents=True, exist_ok=True)
        figures_dir.mkdir(parents=True, exist_ok=True)
        
        # Save the main integrated data
        main_output_path = data_dir / f"{self.outfile_name}.h5ad"
        adata.write_h5ad(main_output_path)
        logger.info(f"Integrated data saved to {main_output_path}")
        
        # Generate and save plots
        console.print("[dim]Generating integration plots...[/dim]")
        self._generate_integration_plots(adata, figures_dir, logger)
        
        # Save summary statistics
        summary_path = data_dir / f"{self.outfile_name}_summary.txt"
        with open(summary_path, 'w') as f:
            f.write(f"Integration Summary\n")
            f.write(f"==================\n")
            f.write(f"Method: {self.integration_method.upper()}\n")
            f.write(f"Total cells: {adata.n_obs}\n")
            f.write(f"Total genes: {adata.n_vars}\n")
            f.write(f"Samples: {len(adata.obs[self.batch_key].unique())}\n")
            f.write(f"Projects: {len(adata.obs['project'].unique())}\n")
            f.write(f"Batch key: {self.batch_key}\n")
            f.write(f"Number of PCs: {self.n_pcs}\n")
            if self.integration_method == "scvi":
                f.write(f"scVI epochs: {self.scvi_epochs}\n")
                f.write(f"Early stopping: {self.scvi_early_stopping}\n")
            elif self.integration_method == "harmony":
                f.write(f"Harmony vars: {', '.join(self.harmony_vars_use)}\n")
        
        logger.info(f"Summary saved to {summary_path}")
        console.print(f"[green]✓ Results saved to: {self.output_dir / self.outfile_name}[/green]")

    def _generate_integration_plots(self, adata: sc.AnnData, figures_dir: Path, logger: logging.Logger):
        """Generate comprehensive integration plots."""
        logger.info("Generating integration plots...")
        
        # Set up matplotlib parameters
        plt.style.use('default')
        sns.set_palette("husl")
        sc.settings.figdir = str(figures_dir)
        sc.settings.set_figure_params(dpi=300, facecolor='white', format='png')
        
        try:
            # Determine integration key for plots
            integration_key = "X_scvi" if self.integration_method == "scvi" else "X_harmony"
            leiden_key = f"leiden_{self.integration_method}"
            
            # 1. UMAP colored by clusters
            if leiden_key in adata.obs.columns:
                logger.debug("Generating cluster UMAP...")
                sc.pl.umap(
                    adata, 
                    color=leiden_key, 
                    legend_loc='on data',
                    legend_fontsize=8,
                    frameon=False,
                    save=f'_clusters_{self.integration_method}.png',
                    show=False
                )
            
            # 2. UMAP colored by sample (batch effect visualization)
            logger.debug("Generating sample UMAP...")
            sc.pl.umap(
                adata, 
                color=self.batch_key, 
                legend_loc='right margin',
                frameon=False,
                save=f'_samples_{self.integration_method}.png',
                show=False
            )
            
            # 3. UMAP colored by project
            if 'project' in adata.obs.columns and len(adata.obs['project'].unique()) > 1:
                logger.debug("Generating project UMAP...")
                sc.pl.umap(
                    adata, 
                    color='project', 
                    legend_loc='right margin',
                    frameon=False,
                    save=f'_projects_{self.integration_method}.png',
                    show=False
                )
            
            # 4. UMAP colored by cell type (if available)
            if 'cell_type' in adata.obs.columns:
                logger.debug("Generating cell type UMAP...")
                sc.pl.umap(
                    adata, 
                    color='cell_type', 
                    legend_loc='right margin',
                    frameon=False,
                    save=f'_celltypes_{self.integration_method}.png',
                    show=False
                )
            
            # 5. QC metrics on UMAP
            qc_metrics = ['total_counts', 'n_genes_by_counts', 'pct_counts_mt']
            available_qc = [metric for metric in qc_metrics if metric in adata.obs.columns]
            
            if available_qc:
                logger.debug("Generating QC metrics UMAP...")
                sc.pl.umap(
                    adata, 
                    color=available_qc, 
                    ncols=2,
                    frameon=False,
                    save=f'_qc_metrics_{self.integration_method}.png',
                    show=False
                )
            
            # 6. Integration quality plots
            self._generate_integration_quality_plots(adata, figures_dir, logger)
            
            # 7. Cluster composition plots
            if leiden_key in adata.obs.columns:
                self._generate_cluster_composition_plots(adata, figures_dir, leiden_key, logger)
            
            logger.info(f"Integration plots saved to {figures_dir}")
            console.print(f"[green]✓ Integration plots generated[/green]")
            
        except Exception as e:
            logger.warning(f"Could not generate some plots: {e}")
            console.print(f"[yellow]⚠ Warning: Some plots could not be generated: {e}[/yellow]")

    def _generate_integration_quality_plots(self, adata: sc.AnnData, figures_dir: Path, logger: logging.Logger):
        """Generate plots to assess integration quality."""
        try:
            # Compare pre- and post-integration UMAPs
            fig, axes = plt.subplots(1, 2, figsize=(15, 6))
            fig.suptitle(f'Integration Quality Assessment - {self.integration_method.upper()}', fontsize=16)
            
            # Pre-integration (PCA-based UMAP if available)
            if 'X_pca' in adata.obsm:
                # Compute UMAP on PCA for comparison
                sc.pp.neighbors(adata, use_rep='X_pca', key_added='pca_neighbors')
                sc.tl.umap(adata, neighbors_key='pca_neighbors', copy=False)
                temp_umap = adata.obsm['X_umap'].copy()
                
                ax = axes[0]
                scatter = ax.scatter(
                    temp_umap[:, 0], temp_umap[:, 1], 
                    c=adata.obs[self.batch_key].astype('category').cat.codes,
                    s=1, alpha=0.6, cmap='tab10'
                )
                ax.set_title('Before Integration (PCA-based)')
                ax.set_xlabel('UMAP 1')
                ax.set_ylabel('UMAP 2')
                ax.grid(True, alpha=0.3)
            
            # Post-integration
            integration_key = "X_scvi" if self.integration_method == "scvi" else "X_harmony"
            if integration_key in adata.obsm:
                # Recompute UMAP on integrated data
                sc.pp.neighbors(adata, use_rep=integration_key)
                sc.tl.umap(adata)
                
                ax = axes[1]
                scatter = ax.scatter(
                    adata.obsm['X_umap'][:, 0], adata.obsm['X_umap'][:, 1], 
                    c=adata.obs[self.batch_key].astype('category').cat.codes,
                    s=1, alpha=0.6, cmap='tab10'
                )
                ax.set_title(f'After Integration ({self.integration_method.upper()})')
                ax.set_xlabel('UMAP 1')
                ax.set_ylabel('UMAP 2')
                ax.grid(True, alpha=0.3)
            
            plt.tight_layout()
            plt.savefig(figures_dir / f'integration_quality_{self.integration_method}.png', 
                       dpi=300, bbox_inches='tight')
            plt.close()
            
        except Exception as e:
            logger.warning(f"Could not generate integration quality plots: {e}")

    def _generate_cluster_composition_plots(self, adata: sc.AnnData, figures_dir: Path, leiden_key: str, logger: logging.Logger):
        """Generate cluster composition analysis plots."""
        try:
            # Cluster composition by sample
            cluster_sample_counts = adata.obs.groupby([leiden_key, self.batch_key]).size().unstack(fill_value=0)
            
            # Proportional stacked bar plot
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
            fig.suptitle(f'Cluster Composition Analysis - {self.integration_method.upper()}', fontsize=14)
            
            # Absolute counts
            cluster_sample_counts.plot(kind='bar', stacked=True, ax=ax1, 
                                     colormap='tab20', width=0.8)
            ax1.set_title('Cluster Composition (Absolute Counts)')
            ax1.set_xlabel('Cluster')
            ax1.set_ylabel('Number of Cells')
            ax1.legend(title='Sample', bbox_to_anchor=(1.05, 1), loc='upper left')
            ax1.tick_params(axis='x', rotation=45)
            
            # Proportional
            cluster_sample_props = cluster_sample_counts.div(cluster_sample_counts.sum(axis=1), axis=0)
            cluster_sample_props.plot(kind='bar', stacked=True, ax=ax2, 
                                    colormap='tab20', width=0.8)
            ax2.set_title('Cluster Composition (Proportions)')
            ax2.set_xlabel('Cluster')
            ax2.set_ylabel('Proportion of Cells')
            ax2.legend(title='Sample', bbox_to_anchor=(1.05, 1), loc='upper left')
            ax2.tick_params(axis='x', rotation=45)
            
            plt.tight_layout()
            plt.savefig(figures_dir / f'cluster_composition_{self.integration_method}.png', 
                       dpi=300, bbox_inches='tight')
            plt.close()
            
            # Sample composition by cluster (heatmap)
            fig, ax = plt.subplots(figsize=(12, 8))
            sns.heatmap(cluster_sample_props.T, annot=True, fmt='.2f', cmap='Blues', 
                       ax=ax, cbar_kws={'label': 'Proportion'})
            ax.set_title(f'Sample Distribution Across Clusters - {self.integration_method.upper()}')
            ax.set_xlabel('Cluster')
            ax.set_ylabel('Sample')
            
            plt.tight_layout()
            plt.savefig(figures_dir / f'sample_distribution_{self.integration_method}.png', 
                       dpi=300, bbox_inches='tight')
            plt.close()
            
        except Exception as e:
            logger.warning(f"Could not generate cluster composition plots: {e}")

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        """Add CLI arguments for the Integration function."""
        parser.add_argument(
            '--method', '-m',
            choices=['scvi', 'harmony'],
            default='harmony',
            help='Integration method to use (default: harmony)'
        )
        parser.add_argument(
            '--output-name', '-o',
            type=str,
            help='Output file name (without extension)'
        )
        parser.add_argument(
            '--n-pcs',
            type=int,
            default=50,
            help='Number of principal components to use (default: 50)'
        )
        parser.add_argument(
            '--batch-key',
            type=str,
            default='sample',
            help='Column name in obs containing batch information (default: sample)'
        )
        parser.add_argument(
            '--scvi-epochs',
            type=int,
            default=200,
            help='Number of training epochs for scVI (default: 200)'
        )
        parser.add_argument(
            '--no-early-stopping',
            action='store_true',
            help='Disable early stopping in scVI training'
        )
        parser.add_argument(
            '--harmony-vars',
            nargs='+',
            help='Variables to use for Harmony correction (default: uses batch-key)'
        )
        parser.add_argument(
            '--force-rerun',
            action='store_true',
            help='Force rerun even if cached results exist'
        )
        parser.add_argument(
            '--quiet',
            action='store_true',
            help='Reduce verbosity'
        )

    def cli(self, project, args: Optional[argparse.Namespace] = None):
        """CLI entry point for Integration function."""
        # Extract arguments with defaults
        integration_method = "harmony"
        output_name = None
        n_pcs = 50
        batch_key = "sample"
        scvi_epochs = 200
        scvi_early_stopping = True
        harmony_vars_use = None
        force_rerun = False
        verbose = True
        
        if args:
            if hasattr(args, 'method'):
                integration_method = args.method
            if hasattr(args, 'output_name'):
                output_name = args.output_name
            if hasattr(args, 'n_pcs'):
                n_pcs = args.n_pcs
            if hasattr(args, 'batch_key'):
                batch_key = args.batch_key
            if hasattr(args, 'scvi_epochs'):
                scvi_epochs = args.scvi_epochs
            if hasattr(args, 'no_early_stopping'):
                scvi_early_stopping = not args.no_early_stopping
            if hasattr(args, 'harmony_vars'):
                harmony_vars_use = args.harmony_vars
            if hasattr(args, 'force_rerun'):
                force_rerun = args.force_rerun
            if hasattr(args, 'quiet'):
                verbose = not args.quiet
        
        console.print(f"[cyan]Starting integration with {integration_method.upper()}...[/cyan]")
        console.print(f"Batch key: {batch_key}")
        console.print(f"Number of PCs: {n_pcs}")
        if integration_method == "scvi":
            console.print(f"scVI epochs: {scvi_epochs}")
            console.print(f"Early stopping: {scvi_early_stopping}")
        elif integration_method == "harmony":
            vars_display = harmony_vars_use if harmony_vars_use else [batch_key]
            console.print(f"Harmony variables: {', '.join(vars_display)}")
        
        integrate_instance = Integrate(
            integration_method=integration_method,
            outfile_name=output_name,
            n_pcs=n_pcs,
            batch_key=batch_key,
            scvi_epochs=scvi_epochs,
            scvi_early_stopping=scvi_early_stopping,
            harmony_vars_use=harmony_vars_use,
            force_rerun=force_rerun,
            verbose=verbose
        )
        return integrate_instance.call(project)

    def get_description(self) -> str:
        return """Integrate single-cell data using scVI or Harmony methods.
        
This function performs batch correction and data integration using either:
- scVI: Deep generative model for probabilistic integration
- Harmony: Fast linear method for batch correction using fuzzy clustering

Both methods support multi-sample integration and produce UMAP embeddings for visualization."""

    def get_usage_examples(self) -> list[str]:
        return [
            "celline run integrate",
            "celline run integrate --method scvi --scvi-epochs 300",
            "celline run integrate --method harmony --harmony-vars sample project",
            "celline run integrate --output-name my_integration --n-pcs 30",
            "celline run integrate --force-rerun --quiet"
        ]
