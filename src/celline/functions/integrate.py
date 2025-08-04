import argparse
import datetime
import logging
import os
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Final, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import polars as pl
import scanpy as sc
import seaborn as sns
import toml
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
        filter_func: Callable[[SampleSchema], bool] | None = None,
        outfile_name: str | None = None,
        integration_method: str = "harmony",
        n_pcs: int = 50,
        batch_key: str = "sample",
        scvi_epochs: int = 200,
        scvi_early_stopping: bool = True,
        harmony_vars_use: list[str] | None = None,
        force_rerun: bool = False,
        verbose: bool = True,
        sample_list: list[str] | None = None,
    ) -> None:
        """Initialize the Integration class.

        Parameters
        ----------
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
        sample_list : Optional[list[str]], default=None
            List of specific sample IDs to integrate. If None, uses all available samples.

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
        self.sample_list = sample_list

        # Setup output path
        if outfile_name is None:
            timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            self.outfile_name = f"integrated_{self.integration_method}_{timestamp}"
        else:
            self.outfile_name = outfile_name

        # Create method-specific output directory
        self.output_dir = Path(Config.PROJ_ROOT) / "integration" / self.integration_method
        # Note: output_path is now managed in _save_results with structured directories

        # Validate integration method
        if self.integration_method not in ["scvi", "harmony"]:
            raise ValueError(f"Integration method must be 'scvi' or 'harmony', got '{self.integration_method}'")

    def register(self) -> str:
        return "integrate"

    def _get_cache_path(self) -> Path:
        """Get path to the integration cache TOML file."""
        return self.output_dir / "integrate.toml"

    def _generate_sample_key(self, sample_list: list[str]) -> str:
        """Generate a unique key for a sample combination."""
        return "_".join(sorted(sample_list))

    def _load_cache(self) -> dict:
        """Load existing integration cache."""
        cache_path = self._get_cache_path()
        if cache_path.exists():
            try:
                return toml.load(cache_path)
            except Exception as e:
                console.print(f"[yellow]⚠ Warning: Could not load cache file: {e}[/yellow]")
                return {}
        return {}

    def _save_cache(self, cache_data: dict):
        """Save integration cache to TOML file."""
        cache_path = self._get_cache_path()
        try:
            with open(cache_path, "w") as f:
                toml.dump(cache_data, f)
        except Exception as e:
            console.print(f"[yellow]⚠ Warning: Could not save cache file: {e}[/yellow]")

    def _check_cached_integration(self, sample_ids: list[str]) -> str | None:
        """Check if this sample combination has been integrated before."""
        cache = self._load_cache()
        sample_key = self._generate_sample_key(sample_ids)

        if sample_key in cache:
            cached_entry = cache[sample_key]
            cached_dir = Path(cached_entry.get("output_dir", ""))

            # Verify that the cached directory and model still exist
            if cached_dir.exists():
                if self.integration_method == "scvi":
                    model_path = cached_dir / "models" / "scvi_model"
                    if model_path.exists():
                        console.print(f"[green]✓ Found cached integration for samples: {', '.join(sample_ids)}[/green]")
                        console.print(f"[green]Using cached results from: {cached_dir}[/green]")
                        return str(cached_dir)
                else:
                    # For harmony, just check if h5ad file exists
                    h5ad_path = cached_dir / "data" / f"{cached_dir.name}.h5ad"
                    if h5ad_path.exists():
                        console.print(f"[green]✓ Found cached integration for samples: {', '.join(sample_ids)}[/green]")
                        console.print(f"[green]Using cached results from: {cached_dir}[/green]")
                        return str(cached_dir)

        return None

    def _add_to_cache(self, sample_ids: list[str], output_dir: str):
        """Add a new integration to the cache."""
        cache = self._load_cache()
        sample_key = self._generate_sample_key(sample_ids)

        cache[sample_key] = {
            "samples": sample_ids,
            "output_dir": output_dir,
            "integration_method": self.integration_method,
            "timestamp": datetime.datetime.now().isoformat(),
            "n_samples": len(sample_ids),
        }

        self._save_cache(cache)
        console.print(f"[dim]Added integration to cache: {sample_key}[/dim]")

    def _apply_celltype_mapping_to_integrated_data(self, adata: sc.AnnData, target_samples: list[SampleInfo], logger: logging.Logger):
        """Apply celltype mapping to already integrated data."""
        try:
            # Initialize cell_type column with 'Unknown'
            adata.obs["cell_type"] = "Unknown"

            # Process each sample
            for sample_info in target_samples:
                sample_key = sample_info.schema.key
                data_sample_dir = sample_info.path.data_sample
                celltype_path = f"{data_sample_dir}/celltype_predicted.tsv"

                if not os.path.exists(celltype_path):
                    logger.warning(f"celltype_predicted.tsv not found for {sample_key}")
                    continue

                try:
                    # Load celltype predictions
                    celltype_df = pd.read_csv(celltype_path, sep="\t")
                    if "cell" not in celltype_df.columns:
                        logger.warning(f"No 'cell' column in celltype_predicted.tsv for {sample_key}")
                        continue

                    # Get celltype column (scpred_prediction or cell_type_cluster_weighted)
                    celltype_col = "cell_type_cluster_weighted" if "cell_type_cluster_weighted" in celltype_df.columns else "scpred_prediction"

                    # Get cells for this sample from integrated data
                    sample_mask = adata.obs["sample"] == sample_key
                    sample_cells = adata.obs.index[sample_mask]

                    if len(sample_cells) == 0:
                        logger.warning(f"No cells found for sample {sample_key} in integrated data")
                        continue

                    # Try direct mapping first
                    celltype_dict = dict(zip(celltype_df["cell"], celltype_df[celltype_col], strict=False))
                    mapped_types = pd.Series(sample_cells).map(celltype_dict)
                    direct_mapped_count = mapped_types.notna().sum()

                    if direct_mapped_count > len(sample_cells) * 0.5:
                        # Direct mapping worked well
                        adata.obs.loc[sample_cells, "cell_type"] = mapped_types.fillna("Unknown").values
                        logger.info(f"Direct mapping successful for {sample_key}: {direct_mapped_count}/{len(sample_cells)} cells")
                    else:
                        # Use position-based mapping
                        logger.info(f"Using position-based mapping for {sample_key} ({direct_mapped_count}/{len(sample_cells)} direct matches)")

                        # Sort both datasets
                        celltype_df = celltype_df.sort_values("cell")
                        sample_cells_sorted = sorted(sample_cells)

                        # Map by position (assume celltype data is a subset in order)
                        for i, celltype_value in enumerate(celltype_df[celltype_col]):
                            if i < len(sample_cells_sorted):
                                cell_name = sample_cells_sorted[i]
                                adata.obs.loc[cell_name, "cell_type"] = celltype_value

                        position_mapped_count = (adata.obs.loc[sample_cells, "cell_type"] != "Unknown").sum()
                        logger.info(f"Position-based mapping for {sample_key}: {position_mapped_count}/{len(sample_cells)} cells")

                except Exception as e:
                    logger.warning(f"Failed to apply celltype mapping for {sample_key}: {e}")

            # Report overall mapping success
            total_mapped = (adata.obs["cell_type"] != "Unknown").sum()
            total_cells = len(adata.obs)
            logger.info(f"Overall celltype mapping: {total_mapped}/{total_cells} cells ({total_mapped / total_cells * 100:.1f}%)")

        except Exception as e:
            logger.error(f"Failed to apply celltype mapping to integrated data: {e}")
            # Ensure cell_type column exists even if mapping fails
            if "cell_type" not in adata.obs.columns:
                adata.obs["cell_type"] = "Unknown"

    def _load_cached_and_plot(self, cached_dir: str, target_samples: list[SampleInfo], logger: logging.Logger, project: "Project"):
        """Load cached integration results and regenerate plots only."""
        try:
            cached_path = Path(cached_dir)
            data_dir = cached_path / "data"
            h5ad_file = data_dir / f"{cached_path.name}.h5ad"

            if not h5ad_file.exists():
                console.print(f"[red]❌ Cached h5ad file not found at {h5ad_file}[/red]")
                console.print("[yellow]Falling back to full integration...[/yellow]")
                return None

            # Load cached AnnData
            console.print(f"[dim]Loading cached data from {h5ad_file}...[/dim]")
            adata_integrated = sc.read_h5ad(h5ad_file)

            # Apply celltype mapping to cached data if not already present
            if "cell_type" not in adata_integrated.obs.columns:
                console.print("[dim]Adding celltype information to cached data...[/dim]")
                self._apply_celltype_mapping_to_integrated_data(adata_integrated, target_samples, logger)

            # Regenerate figures
            figures_dir = cached_path / "figures"
            figures_dir.mkdir(exist_ok=True)

            console.print("[dim]Regenerating integration plots...[/dim]")
            self._generate_integration_plots(adata_integrated, figures_dir, logger)

            console.print("[green]✅ Cached integration loaded successfully![/green]")
            console.print(f"[green]Plots regenerated at: {figures_dir}[/green]")

            return project

        except Exception as e:
            console.print(f"[red]❌ Failed to load cached integration: {e}[/red]")
            console.print("[yellow]Falling back to full integration...[/yellow]")
            logger.warning(f"Failed to load cached integration: {e}")
            return None

    def call(self, project: "Project"):
        """Main integration pipeline.

        Parameters
        ----------
        project : Project
            Celline project object.

        Returns
        -------
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
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[logging.FileHandler(log_file), logging.StreamHandler() if self.verbose else logging.NullHandler()],
        )
        logger = logging.getLogger(__name__)

        try:
            # Check for cached integration first (based on requested samples, not discovered samples)
            cached_dir = None
            if not self.force_rerun and self.sample_list:
                console.print(f"[dim]Checking cache for requested samples: {self.sample_list}[/dim]")
                cached_dir = self._check_cached_integration(self.sample_list)
                console.print(f"[dim]Cache check result: {cached_dir}[/dim]")

            if cached_dir:
                # For cached integration, create minimal target_samples for the cache loading
                console.print(f"[cyan]Found cached integration for requested samples: {', '.join(self.sample_list)}[/cyan]")
                # Create dummy target_samples for celltype mapping
                target_samples = []
                all_samples = SampleResolver.samples
                console.print(f"[dim]SampleResolver has {len(all_samples)} samples: {list(all_samples.keys())}[/dim]")

                for sample_id in self.sample_list:
                    # We need to create minimal SampleInfo objects or work around this
                    # For now, try to get sample info from SampleResolver if available
                    if sample_id in all_samples:
                        target_samples.append(all_samples[sample_id])
                        console.print(f"[dim]Found sample info for {sample_id}[/dim]")
                    else:
                        console.print(f"[dim]No sample info found for {sample_id} in SampleResolver[/dim]")

                console.print("[cyan]Loading cached integration and regenerating plots...[/cyan]")
                result = self._load_cached_and_plot(cached_dir, target_samples, logger, project)
                if result is not None:
                    return result
                console.print("[cyan]Cached loading failed, continuing with sample discovery...[/cyan]")

            # Collect target samples
            console.print(f"[dim]Attempting to collect target samples with sample_list: {self.sample_list}[/dim]")
            target_samples = self._collect_target_samples()
            console.print(f"[dim]Collected {len(target_samples)} target samples[/dim]")
            if not target_samples:
                console.print("[red]❌ No valid samples found for integration[/red]")
                return project

            sample_ids = [info.schema.key for info in target_samples]
            console.print(f"[green]Found {len(target_samples)} samples for integration: {', '.join(sample_ids)}[/green]")

            # Check for celltype predictions
            self._check_celltype_predictions(target_samples, logger)

            # Check for cached integration again (unless force_rerun is True) - this time based on discovered samples
            if not cached_dir and not self.force_rerun:
                cached_dir = self._check_cached_integration(sample_ids)

            if cached_dir:
                # Load cached integration and regenerate plots only
                console.print("[cyan]Loading cached integration and regenerating plots...[/cyan]")
                result = self._load_cached_and_plot(cached_dir, target_samples, logger, project)
                if result is not None:
                    return result
                # If loading cached results failed, continue with full integration
                console.print("[cyan]Falling back to full integration...[/cyan]")
            else:
                console.print("[cyan]No cached integration found, performing full integration...[/cyan]")

            # Load and combine data
            adata_combined = self._load_and_combine_samples(target_samples, logger)

            # Perform integration
            if self.integration_method == "scvi":
                adata_integrated = self._integrate_scvi(adata_combined, logger)
            elif self.integration_method == "harmony":
                adata_integrated = self._integrate_harmony(adata_combined, logger)

            # Save results
            self._save_results(adata_integrated, logger)

            # Add to cache for future reuse
            output_path = str(self.output_dir / self.outfile_name)
            self._add_to_cache(sample_ids, output_path)

            console.print("[green]✅ Integration completed successfully![/green]")
            console.print(f"[green]Results saved to: {self.output_dir / self.outfile_name}[/green]")

        except Exception as e:
            console.print(f"[red]❌ Integration failed: {e}[/red]")
            logger.error(f"Integration failed: {e}", exc_info=True)
            raise

        return project

    def _collect_target_samples(self) -> list[SampleInfo]:
        """Collect target samples based on filter function."""
        target_samples: list[SampleInfo] = []

        all_samples = SampleResolver.samples
        console.print(f"[dim]SampleResolver found {len(all_samples)} samples: {list(all_samples.keys())}[/dim]")

        for info in all_samples.values():
            console.print(f"[dim]Checking sample {info.schema.key}: is_counted={info.path.is_counted}[/dim]")
            if info.path.is_counted:
                # Apply sample list filter if specified
                if self.sample_list is not None and info.schema.key not in self.sample_list:
                    console.print(f"[dim]Sample {info.schema.key} not in requested list, skipping[/dim]")
                    continue

                if self.filter_func is None:
                    add = True
                else:
                    add = self.filter_func(info.schema)
                if add:
                    console.print(f"[dim]Adding sample {info.schema.key} to target list[/dim]")
                    target_samples.append(info)
                else:
                    console.print(f"[dim]Sample {info.schema.key} filtered out by filter_func[/dim]")
            else:
                console.print(f"[yellow]⚠ Warning: Sample {info.schema.key} is not counted or preprocessed yet[/yellow]")

        return target_samples

    def _check_celltype_predictions(self, target_samples: list[SampleInfo], logger: logging.Logger):
        """Check if celltype_predicted.tsv exists for each sample."""
        missing_celltype_samples = []

        for sample_info in target_samples:
            celltype_path = f"{sample_info.path.data_sample}/celltype_predicted.tsv"
            if not os.path.exists(celltype_path):
                missing_celltype_samples.append(sample_info.schema.key)

        if missing_celltype_samples:
            console.print(f"[yellow]⚠ Warning: celltype_predicted.tsv not found for samples: {', '.join(missing_celltype_samples)}[/yellow]")
            console.print("[yellow]Cell type integration will be limited for these samples[/yellow]")
            logger.warning(f"Missing celltype predictions for: {missing_celltype_samples}")
        else:
            console.print("[green]✓ All samples have celltype predictions available[/green]")
            logger.info("All samples have celltype predictions available")

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

            adata = sc.read_10x_h5(count_matrix_path)
            adata.var_names_make_unique()

            # Add sample metadata and fix cell indexing to start from 1
            adata.obs["sample"] = sample_info.schema.key
            adata.obs["project"] = sample_info.schema.parent or "Unknown"

            # Use polars to create proper cell indexing starting from 1
            obs_df = (
                pl.DataFrame(adata.obs)
                .with_columns(
                    pl.format(
                        "{}_{}",
                        pl.col("sample"),
                        (
                            pl.col("sample")  # Count by sample
                            .cum_count()
                            .over("sample")
                        ),  # 1-based indexing
                    ).alias("cell"),
                )
                .to_pandas()
                .set_index("cell")
            )

            adata.obs = obs_df
            adata.obs_names = adata.obs.index

            # Load additional metadata if available
            self._load_additional_metadata(adata, sample_info, logger)

            adata_list.append(adata)
            logger.info(f"Loaded {sample_info.schema.key}: {adata.n_obs} cells × {adata.n_vars} genes")

        if not adata_list:
            raise ValueError("No valid samples could be loaded")

        # Combine all samples
        console.print("[dim]Concatenating samples...[/dim]")
        adata_combined = sc.concat(adata_list, join="outer")

        # Make variable names unique
        adata_combined.var_names_make_unique()

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
                celltype_df = pd.read_csv(celltype_path, sep="\t")
                if "cell" in celltype_df.columns:
                    # Use cell_type_cluster_weighted if available, otherwise fall back to scpred_prediction
                    celltype_col = "cell_type_cluster_weighted" if "cell_type_cluster_weighted" in celltype_df.columns else "scpred_prediction"

                    # Create mapping dictionary
                    celltype_dict = dict(zip(celltype_df["cell"], celltype_df.get(celltype_col, "Unknown"), strict=False))

                    # Try direct mapping first
                    adata.obs["cell_type"] = adata.obs.index.map(celltype_dict)

                    # If direct mapping failed (many NaNs), try alternative mapping strategies
                    mapped_count = adata.obs["cell_type"].notna().sum()
                    total_count = len(adata.obs)

                    if mapped_count < total_count * 0.5:  # Less than 50% mapped
                        logger.warning(f"Direct cell mapping resulted in only {mapped_count}/{total_count} cells mapped")

                        # Alternative strategy: map by position if cell numbers are sequential
                        # Extract cell numbers from both datasets
                        sample_key = sample_info.schema.key

                        # Get cell numbers from celltype data (e.g., GSM3934448_3 -> 3)
                        celltype_df["cell_num"] = celltype_df["cell"].str.extract(f"{sample_key}_(\\d+)").astype(int)
                        celltype_df = celltype_df.sort_values("cell_num")

                        # Get cell numbers from adata (e.g., GSM3934448_1 -> 1)
                        adata_cell_nums = pd.Series(adata.obs.index).str.extract(f"{sample_key}_(\\d+)")[0].astype(int)

                        # Create position-based mapping if the celltype data appears to be a subset
                        if len(celltype_df) <= len(adata.obs):
                            # Map by relative position, accounting for potential offset
                            min_celltype_num = celltype_df["cell_num"].min()
                            max_celltype_num = celltype_df["cell_num"].max()

                            # Create mapping based on the assumption that celltype data
                            # corresponds to cells in order, possibly with an offset
                            for i, (_, row) in enumerate(celltype_df.iterrows()):
                                if i < len(adata.obs):
                                    cell_name = adata.obs.index[i]
                                    adata.obs.loc[cell_name, "cell_type"] = row[celltype_col]

                        logger.info("Applied position-based mapping for celltype predictions")

                    # Fill remaining NaNs with 'Unknown'
                    adata.obs["cell_type"] = adata.obs["cell_type"].fillna("Unknown")

                    final_mapped = adata.obs["cell_type"].ne("Unknown").sum()
                    logger.info(f"Successfully mapped cell types for {final_mapped}/{total_count} cells using column: {celltype_col}")

            except Exception as e:
                logger.warning(f"Could not load cell type predictions for {sample_info.schema.key}: {e}")

        # Load QC metrics
        qc_path = f"{data_sample_dir}/qc_matrix.tsv"
        if os.path.exists(qc_path):
            try:
                qc_df = pd.read_csv(qc_path, sep="\t")
                # Map QC metrics by barcode or cell name
                for col in qc_df.columns:
                    if col not in ["cell", "barcodes"]:
                        if "cell" in qc_df.columns:
                            qc_dict = dict(zip(qc_df["cell"], qc_df[col], strict=False))
                            adata.obs[col] = adata.obs.index.map(qc_dict)
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

        model.train(max_epochs=self.scvi_epochs, early_stopping=self.scvi_early_stopping, accelerator="cpu")

        # Get latent representation
        logger.info("Extracting latent representation...")
        adata.obsm["X_scvi"] = model.get_latent_representation()

        # Compute neighbors and UMAP (scVI latent representation doesn't need n_pcs)
        sc.pp.neighbors(adata, use_rep="X_scvi")
        sc.tl.umap(adata)
        sc.tl.leiden(adata, resolution=1.0, key_added="leiden_scvi")

        # Save scVI model
        model_save_dir = self.output_dir / self.outfile_name / "models"
        model_save_dir.mkdir(parents=True, exist_ok=True)
        model_save_path = model_save_dir / "scvi_model"
        logger.info(f"Saving scVI model to {model_save_path}")
        console.print(f"[dim]Saving scVI model to {model_save_path}...[/dim]")
        model.save(model_save_path, overwrite=True)

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
        sc.tl.pca(adata, svd_solver="arpack", n_comps=self.n_pcs)

        # Prepare data for Harmony
        data_mat = adata.obsm["X_pca"].T  # Harmony expects genes x cells
        meta_data = adata.obs[self.harmony_vars_use].copy()

        # Run Harmony
        logger.info(f"Running Harmony with vars_use: {self.harmony_vars_use}")
        console.print("[dim]Running Harmony correction...[/dim]")

        ho = hm.run_harmony(data_mat, meta_data, self.harmony_vars_use)

        # Store corrected embedding
        adata.obsm["X_harmony"] = ho.Z_corr.T

        # Compute neighbors and UMAP using corrected embedding
        sc.pp.neighbors(adata, use_rep="X_harmony", n_pcs=self.n_pcs)
        sc.tl.umap(adata)
        sc.tl.leiden(adata, resolution=1.0, key_added="leiden_harmony")

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

        # Save the main integrated data with only specified columns
        main_output_path = data_dir / f"{self.outfile_name}.h5ad"

        # Create a copy with only the required obs columns
        adata_save = adata.copy()

        # Define required columns based on integration method
        if self.integration_method == "scvi":
            required_columns = ["sample", "project", "_scvi_batch", "_scvi_labels", "leiden_scvi"]
        else:  # harmony
            required_columns = ["sample", "project", "leiden"]

        # Keep only required columns that exist in the data
        existing_columns = [col for col in required_columns if col in adata_save.obs.columns]
        if not existing_columns:
            logger.warning("None of the required columns found in data, saving with current obs")
            existing_columns = list(adata_save.obs.columns)

        # Filter obs to only include required columns
        adata_save.obs = adata_save.obs[existing_columns].copy()

        # Ensure cell names are in the index
        if "cell" in adata_save.obs.columns:
            adata_save.obs_names = adata_save.obs["cell"]
            adata_save.obs = adata_save.obs.drop("cell", axis=1)

        adata_save.write_h5ad(main_output_path)
        logger.info(f"Integrated data saved to {main_output_path} with columns: {existing_columns}")

        # Generate and save plots
        console.print("[dim]Generating integration plots...[/dim]")
        self._generate_integration_plots(adata, figures_dir, logger)

        # Save summary statistics
        summary_path = data_dir / f"{self.outfile_name}_summary.txt"
        with open(summary_path, "w") as f:
            f.write("Integration Summary\n")
            f.write("==================\n")
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
        plt.style.use("default")
        sns.set_palette("husl")
        sc.settings.figdir = str(figures_dir)

        # Set matplotlib parameters directly to avoid recursion
        import matplotlib as mpl

        mpl.rcParams["figure.dpi"] = 300
        mpl.rcParams["figure.facecolor"] = "white"
        mpl.rcParams["savefig.format"] = "png"

        try:
            # Determine integration key for plots
            integration_key = "X_scvi" if self.integration_method == "scvi" else "X_harmony"
            leiden_key = f"leiden_{self.integration_method}"

            # 1. UMAP colored by clusters
            if leiden_key in adata.obs.columns:
                logger.debug("Generating cluster UMAP...")
                sc.pl.umap(adata, color=leiden_key, legend_loc="on data", legend_fontsize=8, frameon=False, save=f"_clusters_{self.integration_method}.png", show=False)

            # 2. UMAP colored by sample (batch effect visualization)
            logger.debug("Generating sample UMAP...")
            sc.pl.umap(adata, color=self.batch_key, legend_loc="right margin", frameon=False, save=f"_samples_{self.integration_method}.png", show=False)

            # 3. UMAP colored by project
            if "project" in adata.obs.columns and len(adata.obs["project"].unique()) > 1:
                logger.debug("Generating project UMAP...")
                sc.pl.umap(adata, color="project", legend_loc="right margin", frameon=False, save=f"_projects_{self.integration_method}.png", show=False)

            # 4. UMAP colored by cell type (if available)
            if "cell_type" in adata.obs.columns:
                logger.debug("Generating cell type UMAP...")
                sc.pl.umap(adata, color="cell_type", legend_loc="right margin", frameon=False, save=f"_celltypes_{self.integration_method}.png", show=False)

            # 5. QC metrics on UMAP
            qc_metrics = ["total_counts", "n_genes_by_counts", "pct_counts_mt"]
            available_qc = [metric for metric in qc_metrics if metric in adata.obs.columns]

            if available_qc:
                logger.debug("Generating QC metrics UMAP...")
                sc.pl.umap(adata, color=available_qc, ncols=2, frameon=False, save=f"_qc_metrics_{self.integration_method}.png", show=False)

            # 6. Integration quality plots
            self._generate_integration_quality_plots(adata, figures_dir, logger)

            # 7. Cluster composition plots
            if leiden_key in adata.obs.columns:
                self._generate_cluster_composition_plots(adata, figures_dir, leiden_key, logger)

            # 8. Comprehensive summary plots
            self._generate_comprehensive_summary_plots(adata, figures_dir, logger)

            # 9. Cell type analysis plots (if cell types are available)
            if "cell_type" in adata.obs.columns and adata.obs["cell_type"].ne("Unknown").any():
                self._generate_celltype_analysis_plots(adata, figures_dir, logger)

            # 10. scib metrics evaluation (disabled for performance)
            # if (len(adata.obs[self.batch_key].unique()) > 1 and
            #     'cell_type' in adata.obs.columns and
            #     adata.obs['cell_type'].ne('Unknown').any()):
            #     self._generate_scib_metrics(adata, figures_dir, logger)

            logger.info(f"Integration plots saved to {figures_dir}")
            console.print("[green]✓ Integration plots generated[/green]")

        except Exception as e:
            logger.warning(f"Could not generate some plots: {e}")
            console.print(f"[yellow]⚠ Warning: Some plots could not be generated: {e}[/yellow]")

    def _generate_integration_quality_plots(self, adata: sc.AnnData, figures_dir: Path, logger: logging.Logger):
        """Generate plots to assess integration quality."""
        try:
            logger.info("Generating integration quality assessment plots...")

            # Create integration quality visualization
            fig, axes = plt.subplots(2, 2, figsize=(16, 12))
            fig.suptitle(f"Integration Quality Assessment - {self.integration_method.upper()}", fontsize=16)

            integration_key = "X_scvi" if self.integration_method == "scvi" else "X_harmony"

            # Plot 1: UMAP colored by sample (batch effect assessment)
            ax1 = axes[0, 0]
            sample_colors = adata.obs[self.batch_key].astype("category").cat.codes
            scatter1 = ax1.scatter(adata.obsm["X_umap"][:, 0], adata.obsm["X_umap"][:, 1], c=sample_colors, s=0.5, alpha=0.7, cmap="tab10")
            ax1.set_title("Integration Quality: Sample Mixing")
            ax1.set_xlabel("UMAP 1")
            ax1.set_ylabel("UMAP 2")
            ax1.grid(True, alpha=0.3)

            # Add sample legend
            unique_samples = adata.obs[self.batch_key].unique()
            for i, sample in enumerate(unique_samples):
                ax1.scatter([], [], c=plt.cm.tab10(i), label=sample, s=20)
            ax1.legend(bbox_to_anchor=(1.05, 1), loc="upper left", fontsize=8)

            # Plot 2: UMAP colored by clusters
            ax2 = axes[0, 1]
            leiden_key = f"leiden_{self.integration_method}"
            if leiden_key in adata.obs.columns:
                cluster_colors = adata.obs[leiden_key].astype("category").cat.codes
                scatter2 = ax2.scatter(adata.obsm["X_umap"][:, 0], adata.obsm["X_umap"][:, 1], c=cluster_colors, s=0.5, alpha=0.7, cmap="tab20")
                ax2.set_title("Cluster Structure")
            else:
                ax2.text(0.5, 0.5, "No cluster information", ha="center", va="center", transform=ax2.transAxes)
                ax2.set_title("Cluster Structure (N/A)")
            ax2.set_xlabel("UMAP 1")
            ax2.set_ylabel("UMAP 2")
            ax2.grid(True, alpha=0.3)

            # Plot 3: Embedding space comparison (integrated vs raw if available)
            ax3 = axes[1, 0]
            if integration_key in adata.obsm:
                # Show first 2 dimensions of integrated embedding
                integrated_embed = adata.obsm[integration_key][:, :2]
                scatter3 = ax3.scatter(integrated_embed[:, 0], integrated_embed[:, 1], c=sample_colors, s=0.5, alpha=0.7, cmap="tab10")
                ax3.set_title(f"{self.integration_method.upper()} Embedding Space (2D)")
                ax3.set_xlabel(f"{integration_key} 1")
                ax3.set_ylabel(f"{integration_key} 2")
            else:
                ax3.text(0.5, 0.5, "Integration embedding not available", ha="center", va="center", transform=ax3.transAxes)
                ax3.set_title("Integration Embedding (N/A)")
            ax3.grid(True, alpha=0.3)

            # Plot 4: Sample distribution statistics
            ax4 = axes[1, 1]
            sample_counts = adata.obs[self.batch_key].value_counts()
            bars = ax4.bar(range(len(sample_counts)), sample_counts.values, color=[plt.cm.tab10(i) for i in range(len(sample_counts))])
            ax4.set_title("Cell Count per Sample")
            ax4.set_xlabel("Sample")
            ax4.set_ylabel("Number of Cells")
            ax4.set_xticks(range(len(sample_counts)))
            ax4.set_xticklabels(sample_counts.index, rotation=45, ha="right")
            ax4.grid(True, alpha=0.3, axis="y")

            # Add value labels on bars
            for i, bar in enumerate(bars):
                ax4.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(sample_counts) * 0.01, f"{sample_counts.values[i]}", ha="center", va="bottom", fontsize=10)

            plt.tight_layout()
            plt.savefig(figures_dir / f"integration_quality_{self.integration_method}.png", dpi=300, bbox_inches="tight")
            plt.close()

            logger.info("Integration quality plots generated successfully")

        except Exception as e:
            logger.warning(f"Could not generate integration quality plots: {e}")
            import traceback

            logger.debug(f"Traceback: {traceback.format_exc()}")

    def _generate_cluster_composition_plots(self, adata: sc.AnnData, figures_dir: Path, leiden_key: str, logger: logging.Logger):
        """Generate cluster composition analysis plots."""
        try:
            # Cluster composition by sample
            cluster_sample_counts = adata.obs.groupby([leiden_key, self.batch_key]).size().unstack(fill_value=0)

            # Proportional stacked bar plot
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 6))
            fig.suptitle(f"Cluster Composition Analysis - {self.integration_method.upper()}", fontsize=14)

            # Absolute counts
            cluster_sample_counts.plot(kind="bar", stacked=True, ax=ax1, colormap="tab20", width=0.8)
            ax1.set_title("Cluster Composition (Absolute Counts)")
            ax1.set_xlabel("Cluster")
            ax1.set_ylabel("Number of Cells")
            ax1.legend(title="Sample", bbox_to_anchor=(1.05, 1), loc="upper left")
            ax1.tick_params(axis="x", rotation=45)

            # Proportional
            cluster_sample_props = cluster_sample_counts.div(cluster_sample_counts.sum(axis=1), axis=0)
            cluster_sample_props.plot(kind="bar", stacked=True, ax=ax2, colormap="tab20", width=0.8)
            ax2.set_title("Cluster Composition (Proportions)")
            ax2.set_xlabel("Cluster")
            ax2.set_ylabel("Proportion of Cells")
            ax2.legend(title="Sample", bbox_to_anchor=(1.05, 1), loc="upper left")
            ax2.tick_params(axis="x", rotation=45)

            plt.tight_layout()
            plt.savefig(figures_dir / f"cluster_composition_{self.integration_method}.png", dpi=300, bbox_inches="tight")
            plt.close()

            # Sample composition by cluster (heatmap)
            fig, ax = plt.subplots(figsize=(12, 8))
            sns.heatmap(cluster_sample_props.T, annot=True, fmt=".2f", cmap="Blues", ax=ax, cbar_kws={"label": "Proportion"})
            ax.set_title(f"Sample Distribution Across Clusters - {self.integration_method.upper()}")
            ax.set_xlabel("Cluster")
            ax.set_ylabel("Sample")

            plt.tight_layout()
            plt.savefig(figures_dir / f"sample_distribution_{self.integration_method}.png", dpi=300, bbox_inches="tight")
            plt.close()

        except Exception as e:
            logger.warning(f"Could not generate cluster composition plots: {e}")
            import traceback

            logger.debug(f"Traceback: {traceback.format_exc()}")

    def _generate_comprehensive_summary_plots(self, adata: sc.AnnData, figures_dir: Path, logger: logging.Logger):
        """Generate comprehensive summary and statistics plots."""
        try:
            logger.info("Generating comprehensive summary plots...")

            # Create a large summary figure
            fig = plt.figure(figsize=(20, 16))
            gs = fig.add_gridspec(4, 4, height_ratios=[1, 1, 1, 1], width_ratios=[1, 1, 1, 1])

            # Plot 1: Sample overview pie chart
            ax1 = fig.add_subplot(gs[0, 0])
            sample_counts = adata.obs[self.batch_key].value_counts()
            colors = plt.cm.Set3(np.linspace(0, 1, len(sample_counts)))
            wedges, texts, autotexts = ax1.pie(sample_counts.values, labels=sample_counts.index, autopct="%1.1f%%", colors=colors, startangle=90)
            ax1.set_title("Sample Distribution")

            # Plot 2: Cluster size distribution
            ax2 = fig.add_subplot(gs[0, 1])
            leiden_key = f"leiden_{self.integration_method}"
            if leiden_key in adata.obs.columns:
                cluster_counts = adata.obs[leiden_key].value_counts().sort_index()
                bars = ax2.bar(range(len(cluster_counts)), cluster_counts.values, color="skyblue", alpha=0.7)
                ax2.set_title("Cluster Size Distribution")
                ax2.set_xlabel("Cluster")
                ax2.set_ylabel("Number of Cells")
                ax2.tick_params(axis="x", rotation=45)

                # Add stats text
                ax2.text(
                    0.02,
                    0.98,
                    f"Total clusters: {len(cluster_counts)}\nLargest: {cluster_counts.max()}\nSmallest: {cluster_counts.min()}",
                    transform=ax2.transAxes,
                    va="top",
                    ha="left",
                    fontsize=8,
                    bbox=dict(boxstyle="round", facecolor="white", alpha=0.8),
                )
            else:
                ax2.text(0.5, 0.5, "No cluster information", ha="center", va="center", transform=ax2.transAxes)
                ax2.set_title("Cluster Distribution (N/A)")

            # Plot 3: Integration embedding variance
            ax3 = fig.add_subplot(gs[0, 2])
            integration_key = "X_scvi" if self.integration_method == "scvi" else "X_harmony"
            if integration_key in adata.obsm:
                embed_data = adata.obsm[integration_key]
                # Calculate explained variance for each dimension
                var_per_dim = np.var(embed_data, axis=0)
                var_prop = var_per_dim / np.sum(var_per_dim) * 100

                dims_to_show = min(10, len(var_prop))  # Show first 10 dimensions
                bars = ax3.bar(range(dims_to_show), var_prop[:dims_to_show], color="orange", alpha=0.7)
                ax3.set_title(f"{self.integration_method.upper()} Embedding Variance")
                ax3.set_xlabel("Dimension")
                ax3.set_ylabel("Variance Explained (%)")
                ax3.tick_params(axis="x", rotation=45)
            else:
                ax3.text(0.5, 0.5, "No embedding data", ha="center", va="center", transform=ax3.transAxes)
                ax3.set_title("Embedding Variance (N/A)")

            # Plot 4: Integration summary statistics
            ax4 = fig.add_subplot(gs[0, 3])
            ax4.axis("off")
            stats_text = f"""Integration Summary

Method: {self.integration_method.upper()}
Total Cells: {adata.n_obs:,}
Total Genes: {adata.n_vars:,}
Samples: {len(adata.obs[self.batch_key].unique())}

Sample Details:"""

            for sample, count in sample_counts.items():
                stats_text += f"\n  {sample}: {count:,} cells"

            if leiden_key in adata.obs.columns:
                stats_text += f"\n\nClusters: {len(adata.obs[leiden_key].unique())}"

            if "cell_type" in adata.obs.columns:
                known_types = adata.obs["cell_type"].ne("Unknown").sum()
                stats_text += f"\n\nCell Types Mapped: {known_types:,}/{adata.n_obs:,}"
                stats_text += f" ({known_types / adata.n_obs * 100:.1f}%)"

            ax4.text(0.05, 0.95, stats_text, transform=ax4.transAxes, va="top", ha="left", fontsize=10, family="monospace", bbox=dict(boxstyle="round", facecolor="lightgray", alpha=0.8))

            # Plot 5-8: Sample-wise UMAP subplots
            samples = adata.obs[self.batch_key].unique()
            for i, sample in enumerate(samples[:4]):  # Show first 4 samples
                row = 1 + i // 2
                col = i % 2
                ax = fig.add_subplot(gs[row, col])

                sample_mask = adata.obs[self.batch_key] == sample
                sample_data = adata[sample_mask]

                if leiden_key in adata.obs.columns:
                    cluster_colors = sample_data.obs[leiden_key].astype("category").cat.codes
                    scatter = ax.scatter(sample_data.obsm["X_umap"][:, 0], sample_data.obsm["X_umap"][:, 1], c=cluster_colors, s=0.5, alpha=0.7, cmap="tab20")
                else:
                    scatter = ax.scatter(sample_data.obsm["X_umap"][:, 0], sample_data.obsm["X_umap"][:, 1], s=0.5, alpha=0.7, color="blue")

                ax.set_title(f"{sample} ({sample_data.n_obs:,} cells)")
                ax.set_xlabel("UMAP 1")
                ax.set_ylabel("UMAP 2")
                ax.grid(True, alpha=0.3)

            # Plot 9: Batch mixing metrics visualization
            if len(samples) > 1:
                ax9 = fig.add_subplot(gs[2, 2:])

                # Calculate nearest neighbor batch mixing
                from sklearn.neighbors import NearestNeighbors

                nn = NearestNeighbors(n_neighbors=min(50, adata.n_obs // 10))
                nn.fit(adata.obsm["X_umap"])

                batch_mixing_scores = []
                for i in range(min(1000, adata.n_obs)):  # Sample subset for efficiency
                    distances, indices = nn.kneighbors(adata.obsm["X_umap"][i : i + 1])
                    neighbor_batches = adata.obs[self.batch_key].iloc[indices[0]]
                    original_batch = adata.obs[self.batch_key].iloc[i]

                    # Calculate proportion of neighbors from different batches
                    different_batch_prop = (neighbor_batches != original_batch).mean()
                    batch_mixing_scores.append(different_batch_prop)

                # Create histogram of mixing scores
                ax9.hist(batch_mixing_scores, bins=30, alpha=0.7, color="green", edgecolor="black")
                ax9.set_title("Batch Mixing Quality\n(Higher = Better Integration)")
                ax9.set_xlabel("Proportion of Neighbors from Different Batches")
                ax9.set_ylabel("Number of Cells")
                ax9.axvline(np.mean(batch_mixing_scores), color="red", linestyle="--", label=f"Mean: {np.mean(batch_mixing_scores):.3f}")
                ax9.legend()
                ax9.grid(True, alpha=0.3)

            plt.tight_layout()
            plt.savefig(figures_dir / f"integration_comprehensive_summary_{self.integration_method}.png", dpi=300, bbox_inches="tight")
            plt.close()

            logger.info("Comprehensive summary plots generated successfully")

        except Exception as e:
            logger.warning(f"Could not generate comprehensive summary plots: {e}")
            import traceback

            logger.debug(f"Traceback: {traceback.format_exc()}")

    def _generate_celltype_analysis_plots(self, adata: sc.AnnData, figures_dir: Path, logger: logging.Logger):
        """Generate cell type analysis plots."""
        try:
            logger.info("Generating cell type analysis plots...")

            # Get cell types that are not 'Unknown'
            known_celltypes = adata.obs[adata.obs["cell_type"] != "Unknown"]["cell_type"]
            if len(known_celltypes) == 0:
                logger.info("No known cell types found, skipping cell type analysis")
                return

            fig, axes = plt.subplots(2, 2, figsize=(20, 12))
            fig.suptitle("Cell Type Analysis", fontsize=16)

            # Plot 1: Cell type distribution
            ax1 = axes[0, 0]
            celltype_counts = known_celltypes.value_counts()
            colors = plt.cm.Set3(np.linspace(0, 1, len(celltype_counts)))
            bars = ax1.bar(range(len(celltype_counts)), celltype_counts.values, color=colors, alpha=0.8)
            ax1.set_title("Cell Type Distribution")
            ax1.set_xlabel("Cell Type")
            ax1.set_ylabel("Number of Cells")
            ax1.set_xticks(range(len(celltype_counts)))
            ax1.set_xticklabels(celltype_counts.index, rotation=45, ha="right")
            ax1.grid(True, alpha=0.3, axis="y")

            # Add count labels on bars
            for i, bar in enumerate(bars):
                ax1.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + max(celltype_counts) * 0.01, f"{celltype_counts.values[i]}", ha="center", va="bottom", fontsize=8)

            # Plot 2: Cell type by sample heatmap
            ax2 = axes[0, 1]
            if len(adata.obs[self.batch_key].unique()) > 1:
                celltype_sample_crosstab = pd.crosstab(adata.obs["cell_type"], adata.obs[self.batch_key])
                # Only include known cell types
                celltype_sample_crosstab = celltype_sample_crosstab.loc[celltype_sample_crosstab.index != "Unknown"]

                if len(celltype_sample_crosstab) > 0:
                    sns.heatmap(celltype_sample_crosstab, annot=True, fmt="d", cmap="Blues", ax=ax2, cbar_kws={"label": "Cell Count"})
                    ax2.set_title("Cell Types by Sample")
                    ax2.set_xlabel("Sample")
                    ax2.set_ylabel("Cell Type")
                else:
                    ax2.text(0.5, 0.5, "No cell type data", ha="center", va="center", transform=ax2.transAxes)
                    ax2.set_title("Cell Types by Sample (N/A)")
            else:
                ax2.text(0.5, 0.5, "Single sample data", ha="center", va="center", transform=ax2.transAxes)
                ax2.set_title("Cell Types by Sample (Single Sample)")

            # Plot 3: Cell type cluster enrichment
            ax3 = axes[1, 0]
            leiden_key = f"leiden_{self.integration_method}"
            if leiden_key in adata.obs.columns:
                # Calculate cell type enrichment per cluster
                cluster_celltype_crosstab = pd.crosstab(adata.obs[leiden_key], adata.obs["cell_type"])
                # Normalize by cluster size to get proportions
                cluster_celltype_props = cluster_celltype_crosstab.div(cluster_celltype_crosstab.sum(axis=1), axis=0)
                # Remove 'Unknown' column if it exists
                if "Unknown" in cluster_celltype_props.columns:
                    cluster_celltype_props = cluster_celltype_props.drop("Unknown", axis=1)

                if len(cluster_celltype_props.columns) > 0:
                    sns.heatmap(cluster_celltype_props.T, annot=True, fmt=".1f", cmap="Reds", ax=ax3, cbar_kws={"label": "Proportion"})
                    ax3.set_title("Cell Type Enrichment per Cluster")
                    ax3.set_xlabel("Cluster")
                    ax3.set_ylabel("Cell Type")
                else:
                    ax3.text(0.5, 0.5, "No enrichment data", ha="center", va="center", transform=ax3.transAxes)
                    ax3.set_title("Cell Type Enrichment (N/A)")
            else:
                ax3.text(0.5, 0.5, "No cluster data", ha="center", va="center", transform=ax3.transAxes)
                ax3.set_title("Cell Type Enrichment (N/A)")

            # Plot 4: Cell type statistics
            ax4 = axes[1, 1]
            ax4.axis("off")

            stats_text = "Cell Type Statistics\n\n"
            stats_text += f"Total cells with known types: {len(known_celltypes):,}\n"
            stats_text += f"Total cells: {adata.n_obs:,}\n"
            stats_text += f"Coverage: {len(known_celltypes) / adata.n_obs * 100:.1f}%\n\n"
            stats_text += f"Cell types identified: {len(celltype_counts)}\n\n"

            stats_text += "Top cell types:\n"
            for celltype, count in celltype_counts.head(8).items():
                percentage = count / len(known_celltypes) * 100
                stats_text += f"  {celltype}: {count:,} ({percentage:.1f}%)\n"

            ax4.text(0.05, 0.95, stats_text, transform=ax4.transAxes, va="top", ha="left", fontsize=10, family="monospace", bbox=dict(boxstyle="round", facecolor="lightblue", alpha=0.8))

            plt.tight_layout()
            plt.savefig(figures_dir / f"celltype_analysis_{self.integration_method}.png", dpi=300, bbox_inches="tight")
            plt.close()

            logger.info("Cell type analysis plots generated successfully")

        except Exception as e:
            logger.warning(f"Could not generate cell type analysis plots: {e}")
            import traceback

            logger.debug(f"Traceback: {traceback.format_exc()}")

    def _generate_scib_metrics(self, adata: sc.AnnData, figures_dir: Path, logger: logging.Logger):
        """Generate scib metrics for integration evaluation."""
        try:
            logger.info("Generating scib integration metrics...")

            # Check for scib availability
            try:
                from scib_metrics.benchmark import BatchCorrection, Benchmarker, BioConservation
            except ImportError:
                logger.warning("scib-metrics package not available. Install with: pip install scib-metrics")
                console.print("[yellow]⚠ scib-metrics package not available for metrics evaluation[/yellow]")
                return

            # Prepare data for scib evaluation
            adata_scib = adata.copy()

            # Filter out Unknown cell types for evaluation
            known_mask = adata_scib.obs["cell_type"] != "Unknown"
            adata_scib = adata_scib[known_mask].copy()

            if len(adata_scib) == 0:
                logger.warning("No cells with known cell types for scib evaluation")
                return

            logger.info(f"Evaluating integration on {adata_scib.n_obs} cells with known cell types")

            # Determine available embeddings
            available_embeddings = []
            integration_key = "X_scvi" if self.integration_method == "scvi" else "X_harmony"

            # Add unintegrated representation (PCA if available, otherwise raw X)
            if "X_pca" in adata_scib.obsm:
                available_embeddings.append("X_pca")
                # Rename for scib
                adata_scib.obsm["Unintegrated"] = adata_scib.obsm["X_pca"].copy()
            else:
                # Use raw expression as unintegrated
                adata_scib.obsm["Unintegrated"] = adata_scib.X.toarray() if hasattr(adata_scib.X, "toarray") else adata_scib.X
                available_embeddings.append("Unintegrated")

            # Add integrated representation
            if integration_key in adata_scib.obsm:
                method_name = self.integration_method.upper()
                adata_scib.obsm[method_name] = adata_scib.obsm[integration_key].copy()
                available_embeddings.append(method_name)
            else:
                logger.warning(f"Integration embedding {integration_key} not found in obsm")
                return

            logger.info(f"Available embeddings for evaluation: {available_embeddings}")

            # Create benchmarker using scib-metrics
            bm = Benchmarker(
                adata_scib,
                batch_key=self.batch_key,
                label_key="cell_type",
                bio_conservation_metrics=BioConservation(),
                batch_correction_metrics=BatchCorrection(),
                embedding_obsm_keys=available_embeddings,
                n_jobs=1,
            )

            # Run benchmarking
            logger.info("Running scib benchmarking...")
            console.print("[dim]Running scib integration benchmarking (this may take a while)...[/dim]")

            bm.benchmark()
            results_df = bm.get_results(min_max_scale=False)

            # Save results table
            results_path = figures_dir / f"scib_metrics_{self.integration_method}.csv"
            results_df.to_csv(results_path)
            logger.info(f"scib metrics saved to {results_path}")

            # Create visualization of results
            fig, axes = plt.subplots(2, 2, figsize=(16, 12))
            fig.suptitle(f"scib Integration Metrics - {self.integration_method.upper()}", fontsize=16)

            # Get metrics categories
            bio_metrics = [col for col in results_df.columns if any(bio_term in col.lower() for bio_term in ["nmi", "ari", "silhouette", "isolated", "trajectory", "hvg"])]
            batch_metrics = [col for col in results_df.columns if any(batch_term in col.lower() for batch_term in ["pcr", "batch", "kbet", "graph", "asw"])]

            # Plot 1: Biological conservation metrics
            ax1 = axes[0, 0]
            if bio_metrics and len(results_df) > 1:
                bio_data = results_df[bio_metrics].T
                sns.heatmap(bio_data, annot=True, fmt=".3f", cmap="Greens", ax=ax1, cbar_kws={"label": "Score"})
                ax1.set_title("Biological Conservation Metrics")
                ax1.set_xlabel("Method")
                ax1.set_ylabel("Metric")
            else:
                ax1.text(0.5, 0.5, "Insufficient data\\nfor bio metrics", ha="center", va="center", transform=ax1.transAxes)
                ax1.set_title("Biological Conservation Metrics (N/A)")

            # Plot 2: Batch correction metrics
            ax2 = axes[0, 1]
            if batch_metrics and len(results_df) > 1:
                batch_data = results_df[batch_metrics].T
                sns.heatmap(batch_data, annot=True, fmt=".3f", cmap="Blues", ax=ax2, cbar_kws={"label": "Score"})
                ax2.set_title("Batch Correction Metrics")
                ax2.set_xlabel("Method")
                ax2.set_ylabel("Metric")
            else:
                ax2.text(0.5, 0.5, "Insufficient data\\nfor batch metrics", ha="center", va="center", transform=ax2.transAxes)
                ax2.set_title("Batch Correction Metrics (N/A)")

            # Plot 3: Overall metrics comparison (if multiple methods)
            ax3 = axes[1, 0]
            if len(results_df) > 1:
                # Select key metrics for comparison
                key_metrics = []
                for metric in ["NMI_cluster/label", "ARI_cluster/label", "ASW_label_batch", "PCR_batch"]:
                    if metric in results_df.columns:
                        key_metrics.append(metric)

                if key_metrics:
                    key_data = results_df[key_metrics]
                    x_pos = np.arange(len(key_metrics))
                    width = 0.35

                    for i, method in enumerate(results_df.index):
                        offset = (i - len(results_df.index) / 2 + 0.5) * width / len(results_df.index)
                        bars = ax3.bar(x_pos + offset, key_data.loc[method], width / len(results_df.index), label=method, alpha=0.7)

                        # Add value labels on bars
                        for j, bar in enumerate(bars):
                            ax3.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 0.01, f"{key_data.loc[method].iloc[j]:.3f}", ha="center", va="bottom", fontsize=8)

                    ax3.set_xlabel("Metrics")
                    ax3.set_ylabel("Score")
                    ax3.set_title("Key Metrics Comparison")
                    ax3.set_xticks(x_pos)
                    ax3.set_xticklabels(key_metrics, rotation=45, ha="right")
                    ax3.legend()
                    ax3.grid(True, alpha=0.3, axis="y")
                else:
                    ax3.text(0.5, 0.5, "No key metrics found", ha="center", va="center", transform=ax3.transAxes)
                    ax3.set_title("Key Metrics (N/A)")
            else:
                ax3.text(0.5, 0.5, "Single method\\nNo comparison", ha="center", va="center", transform=ax3.transAxes)
                ax3.set_title("Metrics Comparison (N/A)")

            # Plot 4: Metrics summary table
            ax4 = axes[1, 1]
            ax4.axis("off")

            # Create summary text
            summary_text = "scib Metrics Summary\\n"
            summary_text += f"{'=' * 30}\\n\\n"
            summary_text += f"Method: {self.integration_method.upper()}\\n"
            summary_text += f"Cells evaluated: {adata_scib.n_obs:,}\\n"
            summary_text += f"Batches: {len(adata_scib.obs[self.batch_key].unique())}\\n"
            summary_text += f"Cell types: {len(adata_scib.obs['cell_type'].unique())}\\n\\n"

            # Add key metric values
            if len(results_df) > 0:
                method_name = results_df.index[0] if len(results_df) == 1 else self.integration_method.upper()
                if method_name in results_df.index:
                    summary_text += f"Key Metrics for {method_name}:\\n"
                    for metric in ["NMI_cluster/label", "ARI_cluster/label", "ASW_label_batch", "PCR_batch"]:
                        if metric in results_df.columns:
                            value = results_df.loc[method_name, metric]
                            summary_text += f"  {metric}: {value:.3f}\\n"

                    summary_text += "\\nMetric Interpretation:\\n"
                    summary_text += "• NMI/ARI: Bio conservation (higher=better)\\n"
                    summary_text += "• ASW_label_batch: Batch correction (lower=better)\\n"
                    summary_text += "• PCR_batch: Batch effect (lower=better)\\n"

            ax4.text(0.05, 0.95, summary_text, transform=ax4.transAxes, va="top", ha="left", fontsize=10, family="monospace", bbox=dict(boxstyle="round", facecolor="lightgray", alpha=0.8))

            plt.tight_layout()
            plt.savefig(figures_dir / f"scib_metrics_{self.integration_method}.png", dpi=300, bbox_inches="tight")
            plt.close()

            logger.info("scib metrics evaluation completed successfully")
            console.print(f"[green]✓ scib metrics generated and saved to {results_path}[/green]")

        except Exception as e:
            logger.warning(f"Could not generate scib metrics: {e}")
            import traceback

            logger.debug(f"Traceback: {traceback.format_exc()}")
            console.print(f"[yellow]⚠ Warning: scib metrics evaluation failed: {e}[/yellow]")

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        """Add CLI arguments for the Integration function."""
        parser.add_argument("--method", "-m", choices=["scvi", "harmony"], default="harmony", help="Integration method to use (default: harmony)")
        parser.add_argument("--output-name", "-o", type=str, help="Output file name (without extension)")
        parser.add_argument("--sample", "-s", type=str, help="Comma-separated list of specific sample IDs to integrate (e.g., GSM3934448,GSM3934449)")
        parser.add_argument("--n-pcs", type=int, default=50, help="Number of principal components to use (default: 50)")
        parser.add_argument("--batch-key", type=str, default="sample", help="Column name in obs containing batch information (default: sample)")
        parser.add_argument("--scvi-epochs", type=int, default=200, help="Number of training epochs for scVI (default: 200)")
        parser.add_argument("--no-early-stopping", action="store_true", help="Disable early stopping in scVI training")
        parser.add_argument("--harmony-vars", nargs="+", help="Variables to use for Harmony correction (default: uses batch-key)")
        parser.add_argument("--force-rerun", action="store_true", help="Force rerun even if cached results exist")
        parser.add_argument("--quiet", action="store_true", help="Reduce verbosity")

    def cli(self, project, args: argparse.Namespace | None = None):
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
        sample_list = None

        if args:
            if hasattr(args, "method"):
                integration_method = args.method
            if hasattr(args, "output_name"):
                output_name = args.output_name
            if hasattr(args, "n_pcs"):
                n_pcs = args.n_pcs
            if hasattr(args, "batch_key"):
                batch_key = args.batch_key
            if hasattr(args, "scvi_epochs"):
                scvi_epochs = args.scvi_epochs
            if hasattr(args, "no_early_stopping"):
                scvi_early_stopping = not args.no_early_stopping
            if hasattr(args, "harmony_vars"):
                harmony_vars_use = args.harmony_vars
            if hasattr(args, "force_rerun"):
                force_rerun = args.force_rerun
            if hasattr(args, "quiet"):
                verbose = not args.quiet
            if hasattr(args, "sample") and args.sample:
                sample_list = [s.strip() for s in args.sample.split(",")]

        console.print(f"[cyan]Starting integration with {integration_method.upper()}...[/cyan]")
        if sample_list:
            console.print(f"Target samples: {', '.join(sample_list)}")
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
            verbose=verbose,
            sample_list=sample_list,
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
            "celline run integrate --force-rerun --quiet",
        ]
