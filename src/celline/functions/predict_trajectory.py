import argparse
import datetime
import logging
import os
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING, List, Optional, Union

import pandas as pd
import scanpy as sc
import scvi
import toml
from rich.console import Console

from celline.config import Setting
from celline.functions._base import CellineFunction
from celline.sample import SampleResolver

if TYPE_CHECKING:
    from celline import Project

console = Console()


class PredictTrajectory(CellineFunction):
    """Trajectory inference using slingshot in both integration and single-sample modes.

    Integration mode uses scVI latent space for multi-sample trajectory analysis.
    Single mode uses PCA-based analysis for individual samples.
    """

    def __init__(
        self,
        integrate_mode: bool = False,
        samples: list[str] | None = None,
        projects: list[str] | None = None,
        resolution: float = 0.5,
        n_pcs: int = 50,
        n_features: int = 2000,
        latent_dims: str = "1:10",
        force_rerun: bool = False,
        verbose: bool = True,
        output_dir: str | None = None,
        markers_file: str | None = None,
        no_rds: bool = False,
    ) -> None:
        """Initialize the PredictTrajectory class.

        Parameters
        ----------
        integrate_mode : bool, default=False
            Whether to use integration mode (scVI latent space) or single mode (PCA).
        samples : Optional[List[str]], default=None
            List of specific sample IDs to analyze. If None, uses all available samples.
        projects : Optional[List[str]], default=None
            List of specific project IDs to analyze. If None, uses all available samples.
        resolution : float, default=0.5
            Clustering resolution for trajectory inference.
        n_pcs : int, default=50
            Number of PCA components for single mode.
        n_features : int, default=2000
            Number of variable features for single mode.
        latent_dims : str, default="1:10"
            Latent dimensions to use for integration mode (R-style range).
        force_rerun : bool, default=False
            Whether to force rerun even if cached results exist.
        verbose : bool, default=True
            Whether to show detailed progress.
        output_dir : Optional[str], default=None
            Custom output directory. If None, uses default structure.
        markers_file : Optional[str], default=None
            Path to canonical markers TSV file for trajectory analysis.
            Required when using CLI. If None, uses package default markers.
        no_rds : bool, default=False
            Skip saving RDS files (sce.rds, seurat.rds) for faster processing.

        """
        self.integrate_mode = integrate_mode
        self.samples = samples
        self.projects = projects
        self.resolution = resolution
        self.n_pcs = n_pcs
        self.n_features = n_features
        self.latent_dims = latent_dims
        self.force_rerun = force_rerun
        self.verbose = verbose
        self.no_rds = no_rds

        # Setup output directory (will be created in call method when project is available)
        self.custom_output_dir = output_dir
        self.output_dir = None  # Will be set in call method
        self.markers_file = markers_file  # Will be validated in call method

        # R script and marker file paths will be set in call() method when project is available
        self.r_script_integrated = None
        self.r_script_single = None
        # Note: self.markers_file is already set above, don't overwrite it
        self.root_markers_file = None
        self.cell_cycle_markers_file = None

        # File validation will be done in call() method

    def _get_rscript_path(self) -> str:
        """Get the correct Rscript path from configuration."""
        if Setting.r_path:
            # If r_path is set, construct Rscript path
            r_path = Path(Setting.r_path)
            if r_path.name == 'R':
                # If r_path points to R executable, replace with Rscript
                rscript_path = str(r_path.parent / 'Rscript')
            elif r_path.is_dir():
                # If r_path is a directory, look for Rscript in it
                rscript_path = str(r_path / 'Rscript')
            else:
                # Assume r_path is a directory path without trailing separator
                rscript_path = str(Path(Setting.r_path) / 'Rscript')
        else:
            # Fallback to system Rscript
            rscript_path = 'Rscript'

        return rscript_path

    def _check_rscript_availability(self) -> None:
        """Check if Rscript is available and raise an error if not."""
        rscript_path = self._get_rscript_path()

        try:
            # Test if Rscript is available
            result = subprocess.run([rscript_path, "--version"],
                                  capture_output=True, text=True, check=True)
            if self.verbose:
                console.print(f"[green]✓ Rscript found: {rscript_path}[/green]")
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            error_msg = f"Rscript not found at: {rscript_path}"
            if Setting.r_path:
                error_msg += f"\nPlease check your R installation path in setting.toml: r_path = '{Setting.r_path}'"
            else:
                error_msg += "\nPlease set the R path in setting.toml or ensure Rscript is in your PATH"
            console.print(f"[red]❌ {error_msg}[/red]")
            raise FileNotFoundError(error_msg) from e

    def register(self) -> str:
        return "predict_trajectory"

    def _validate_required_files(self) -> None:
        """Validate that required R scripts and marker files exist."""
        required_files = [
            self.r_script_integrated,
            self.r_script_single,
            self.markers_file,
            self.root_markers_file,
            self.cell_cycle_markers_file,
        ]

        for file_path in required_files:
            if not file_path.exists():
                raise FileNotFoundError(f"Required file not found: {file_path}")

    def _get_target_samples(self) -> list[str]:
        """Determine which samples to process based on arguments."""
        available_samples = list(SampleResolver.samples.keys())

        if self.samples:
            # Flatten and parse sample arguments
            target_samples = []
            for sample_arg in self.samples:
                if "," in sample_arg:
                    # Handle comma-separated samples: "sample1,sample2"
                    target_samples.extend([s.strip() for s in sample_arg.split(",")])
                else:
                    # Handle individual samples: sample1 sample2
                    target_samples.append(sample_arg.strip())

            # Remove empty strings and duplicates
            target_samples = list(set([s for s in target_samples if s]))

            # Validate that specified samples exist
            missing_samples = set(target_samples) - set(available_samples)
            if missing_samples:
                raise ValueError(f"Specified samples not found: {missing_samples}")

        elif self.projects:
            # Flatten and parse project arguments
            project_ids = []
            for project_arg in self.projects:
                if "," in project_arg:
                    # Handle comma-separated projects: "GSE123456,GSE789012"
                    project_ids.extend([p.strip() for p in project_arg.split(",")])
                else:
                    # Handle individual projects: GSE123456 GSE789012
                    project_ids.append(project_arg.strip())

            # Remove empty strings and duplicates
            project_ids = list(set([p for p in project_ids if p]))

            # Use samples from specified projects
            target_samples = []
            for project_id in project_ids:
                # Find samples belonging to this project
                project_samples = [sample_id for sample_id in available_samples if sample_id.startswith(project_id)]
                target_samples.extend(project_samples)

            # Remove duplicates
            target_samples = list(set(target_samples))

            if not target_samples:
                raise ValueError(f"No samples found for specified projects: {project_ids}")
        else:
            # Use all available samples
            target_samples = available_samples

        if not target_samples:
            raise ValueError("No samples available for trajectory analysis")

        if self.verbose:
            console.print(f"[green]Target samples for trajectory analysis: {len(target_samples)} samples[/green]")
            for sample in sorted(target_samples):
                console.print(f"  • {sample}")

        return target_samples

    def _setup_paths(self, project: "Project") -> None:
        """Setup R script and marker file paths using project information."""
        # project.EXEC_PATH points to site-packages, we need to add 'celline'
        celline_root = Path(project.EXEC_PATH) / "celline"

        self.r_script_integrated = celline_root / "template" / "hook" / "R" / "predict_trajectory" / "slingshot.R"
        self.r_script_single = celline_root / "template" / "hook" / "R" / "predict_trajectory" / "slingshot_single.R"

        # Define marker file paths - use user-specified file if provided, otherwise use celline library paths
        if self.markers_file:
            # User-specified canonical markers file - convert to absolute path
            user_markers_file = Path(self.markers_file).resolve()
            console.print(f"[green]Using user-specified markers file: {user_markers_file}[/green]")
            self.markers_file = user_markers_file
            # Use default celline library paths for other marker files
            self.root_markers_file = celline_root / "data" / "markers" / "__root_markers.tsv"
            self.cell_cycle_markers_file = celline_root / "data" / "markers" / "__cell_cycle_markers.tsv"
        else:
            # Default celline library paths for all markers
            console.print("[yellow]Using default celline markers files[/yellow]")
            self.markers_file = celline_root / "data" / "markers" / "__markers.tsv"
            self.root_markers_file = celline_root / "data" / "markers" / "__root_markers.tsv"
            self.cell_cycle_markers_file = celline_root / "data" / "markers" / "__cell_cycle_markers.tsv"

        # Validate required files exist
        self._validate_required_files()

    def _validate_integration_mode(self, project: "Project") -> None:
        """Validate that integration mode requirements are met and load model info."""
        if not self.integrate_mode:
            return

        # Check for scVI integration results
        integration_dir = Path(project.PROJ_PATH) / "integration" / "scvi"
        integrate_toml = integration_dir / "integrate.toml"

        if not integration_dir.exists():
            raise FileNotFoundError(f"Integration directory not found: {integration_dir}. Please run 'celline run integrate --method scvi' first.")

        if not integrate_toml.exists():
            raise FileNotFoundError(f"Integration configuration not found: {integrate_toml}. Please run 'celline run integrate --method scvi' first.")

        # Load and validate integration configuration
        try:
            config = toml.load(integrate_toml)
            if self.verbose:
                console.print(f"[blue]Loading integration config from: {integrate_toml}[/blue]")

            # Find the appropriate integration section based on target samples
            target_samples = self._get_target_samples()

            # Try to find a matching section
            integration_section = None
            for section_key, section_data in config.items():
                if section_key == "title":
                    continue
                if isinstance(section_data, dict) and "samples" in section_data:
                    # Check if this section matches our target samples
                    section_samples = set(section_data["samples"])
                    if section_samples == set(target_samples):
                        integration_section = section_data
                        break

            if not integration_section:
                # Try to find any section that contains our samples
                for section_key, section_data in config.items():
                    if section_key == "title":
                        continue
                    if isinstance(section_data, dict) and "samples" in section_data:
                        section_samples = set(section_data["samples"])
                        if set(target_samples).issubset(section_samples):
                            integration_section = section_data
                            break

            if not integration_section:
                raise ValueError(f"No integration section found for samples: {target_samples}")

            # Get model path from output_dir
            output_dir = integration_section.get("output_dir")
            if not output_dir:
                raise ValueError("output_dir not found in integration section")

            model_path = Path(output_dir) / "models" / "scvi_model"
            if not model_path.exists():
                # Try alternative model path
                model_path = Path(output_dir) / "model"
                if not model_path.exists():
                    raise FileNotFoundError(f"scVI model directory not found in: {output_dir}")

            # Verify it's a valid scVI model directory
            model_file = model_path / "model.pt"
            if not model_file.exists():
                raise FileNotFoundError(f"scVI model file not found: {model_file}")

            # Store model information for later use
            self.scvi_model_path = str(model_path)
            self.integration_config = integration_section

            if self.verbose:
                console.print(f"[green]✓ scVI model found: {model_path}[/green]")
                console.print("[green]✓ Integration mode validation passed[/green]")

        except Exception as e:
            raise ValueError(f"Failed to validate integration setup: {e}")

    def _preprocess_data_with_scvi(self, input_path: Path, project: "Project") -> Path:
        """Preprocess data with proper cell filtering, cell type merging, and scVI normalized expression.

        Parameters
        ----------
        input_path : Path
            Path to the input H5AD file
        project : Project
            Celline project object

        Returns
        -------
        Path
            Path to the preprocessed H5AD file with scVI normalized expression

        """
        if self.verbose:
            console.print("[cyan]🔬 Preprocessing data with scVI normalized expression...[/cyan]")

        # Load the data
        adata = sc.read_h5ad(input_path)
        if self.verbose:
            console.print(f"[blue]Loaded data: {adata.n_obs} cells, {adata.n_vars} genes[/blue]")

        # Step 1: Filter cells using cell_info.tsv if available
        if self.integrate_mode:
            # For integration mode, look for cell_info.tsv in each sample directory
            # Find project_ids by scanning data directory
            data_dir = Path(project.PROJ_PATH) / "data"
            project_ids = [d.name for d in data_dir.iterdir() if d.is_dir()]

            sample_dirs = []
            for sample_id in self._get_target_samples():
                # Look for sample_id in all project directories
                for project_id in project_ids:
                    sample_dir = data_dir / project_id / sample_id
                    if sample_dir.exists():
                        sample_dirs.append((sample_id, sample_dir))
                        break  # Found in this project, no need to check others

            if sample_dirs:
                if self.verbose:
                    console.print(f"[blue]Found {len(sample_dirs)} sample directories for cell filtering[/blue]")

                # Collect all cell info from all samples
                all_cell_info = []
                for sample_id, sample_dir in sample_dirs:
                    cell_info_path = sample_dir / "cell_info.tsv"
                    if cell_info_path.exists():
                        cell_info = pd.read_csv(cell_info_path, sep="\t")
                        cell_info["sample_id"] = sample_id
                        all_cell_info.append(cell_info)
                        if self.verbose:
                            console.print(f"[green]Loaded cell_info for {sample_id}: {len(cell_info)} cells[/green]")
                    elif self.verbose:
                        console.print(f"[yellow]No cell_info.tsv found for {sample_id}[/yellow]")

                if all_cell_info:
                    combined_cell_info = pd.concat(all_cell_info, ignore_index=True)

                    # Filter to include=True cells only
                    if "include" in combined_cell_info.columns:
                        included_cells = combined_cell_info[combined_cell_info["include"] == True]["cell"].tolist()

                        # Filter adata to include only these cells
                        cell_mask = adata.obs.index.isin(included_cells)
                        adata = adata[cell_mask, :].copy()

                        if self.verbose:
                            console.print(f"[green]✓ Filtered to {adata.n_obs} cells with include=True[/green]")
                    elif self.verbose:
                        console.print("[yellow]No 'include' column found in cell_info.tsv[/yellow]")

        # Step 2: Merge cell type information from celltype_predicted.tsv
        if self.integrate_mode:
            # For integration mode, collect celltype predictions from all samples
            # Use the same approach as Step 1 to find sample directories
            data_dir = Path(project.PROJ_PATH) / "data"
            project_ids = [d.name for d in data_dir.iterdir() if d.is_dir()]

            all_celltype_info = []
            for sample_id in self._get_target_samples():
                # Look for sample_id in all project directories
                for project_id in project_ids:
                    sample_dir = data_dir / project_id / sample_id
                    celltype_path = sample_dir / "celltype_predicted.tsv"
                    if celltype_path.exists():
                        celltype_info = pd.read_csv(celltype_path, sep="\t")
                        celltype_info["sample_id"] = sample_id
                        all_celltype_info.append(celltype_info)
                        if self.verbose:
                            console.print(f"[green]Loaded celltype predictions for {sample_id}: {len(celltype_info)} cells[/green]")
                        break  # Found in this project, no need to check others

            if all_celltype_info:
                combined_celltype_info = pd.concat(all_celltype_info, ignore_index=True)

                # Merge with adata.obs
                if "cell" in combined_celltype_info.columns:
                    # Set cell as index for merging
                    celltype_df = combined_celltype_info.set_index("cell")

                    # Merge celltype information into adata.obs
                    common_cells = adata.obs.index.intersection(celltype_df.index)
                    if len(common_cells) > 0:
                        for col in celltype_df.columns:
                            if col != "sample_id":  # Avoid duplicate sample_id if already present
                                adata.obs[col] = celltype_df.loc[common_cells, col].reindex(adata.obs.index)

                        if self.verbose:
                            console.print(f"[green]✓ Merged celltype info for {len(common_cells)} cells[/green]")
                            # Show which celltype columns were added
                            celltype_cols = [col for col in celltype_df.columns if col != "sample_id"]
                            console.print(f"[blue]Added celltype columns: {celltype_cols}[/blue]")
                    elif self.verbose:
                        console.print("[yellow]No matching cells found between data and celltype predictions[/yellow]")

        # Step 3: Load scVI model and embed normalized expression
        if self.integrate_mode and hasattr(self, "scvi_model_path"):
            try:
                if self.verbose:
                    console.print(f"[cyan]Loading scVI model from: {self.scvi_model_path}[/cyan]")

                # Load the scVI model
                model = scvi.model.SCVI.load(self.scvi_model_path, adata)

                if self.verbose:
                    console.print("[green]✓ scVI model loaded successfully[/green]")

                # Get normalized expression from scVI model
                if self.verbose:
                    console.print("[cyan]Computing normalized expression with scVI...[/cyan]")

                normalized_expression = model.get_normalized_expression(
                    library_size=10e4,  # Standard library size
                    return_numpy=True,
                )

                # Replace .X with normalized expression
                adata.X = normalized_expression

                if self.verbose:
                    console.print("[green]✓ Embedded scVI normalized expression into .X slot[/green]")
                    console.print(f"[blue]Expression shape: {normalized_expression.shape}[/blue]")

            except Exception as e:
                if self.verbose:
                    console.print(f"[yellow]Warning: Failed to load scVI model: {e}[/yellow]")
                    console.print("[yellow]Using original expression data[/yellow]")

        # Step 4: Save preprocessed data
        preprocessed_path = input_path.parent / f"preprocessed_{input_path.name}"

        if self.verbose:
            console.print(f"[cyan]Saving preprocessed data to: {preprocessed_path}[/cyan]")

        adata.write_h5ad(preprocessed_path)

        if self.verbose:
            console.print(f"[green]✅ Preprocessed data saved: {adata.n_obs} cells, {adata.n_vars} genes[/green]")

        return preprocessed_path

    def _load_integration_metadata(self) -> dict:
        """Load metadata from integration configuration."""
        if not hasattr(self, "integration_config"):
            raise ValueError("Integration mode not properly validated")

        config = self.integration_config

        # Extract relevant information for trajectory analysis
        metadata = {
            "model_path": self.scvi_model_path,
            "integration_method": config.get("integration_method", "scvi"),
            "n_latent": config.get("n_latent", 10),
            "batch_key": config.get("batch_key", "sample"),
            "samples_integrated": config.get("samples", []),
        }

        if self.verbose:
            console.print("[blue]Integration metadata loaded:[/blue]")
            console.print(f"  • Model: {metadata['model_path']}")
            console.print(f"  • Latent dimensions: {metadata['n_latent']}")
            console.print(f"  • Batch key: {metadata['batch_key']}")
            console.print(f"  • Integrated samples: {len(metadata['samples_integrated'])}")

        return metadata

    def _get_input_data_paths(self, target_samples: list[str], project: "Project") -> list[Path] | Path:
        """Get input data paths based on mode and samples."""
        if self.integrate_mode:
            # For integration mode, use the integrated data
            integration_dir = Path(project.PROJ_PATH) / "integration" / "scvi"

            # Look for the integrated H5AD file
            integrated_files = list(integration_dir.glob("**/integrated_*.h5ad"))
            if not integrated_files:
                raise FileNotFoundError(f"No integrated H5AD files found in {integration_dir}. Please run integration first.")

            # Test each file for readability and use the first working one
            import subprocess

            integrated_file = None
            for candidate_file in sorted(integrated_files, key=lambda x: x.stat().st_mtime, reverse=True):
                try:
                    # Test if file is readable with rhdf5
                    rscript_path = self._get_rscript_path()
                    test_cmd = [rscript_path, "-e", f"library(rhdf5); h5ls('{candidate_file}')"]
                    result = subprocess.run(test_cmd, capture_output=True, text=True, check=True)
                    integrated_file = candidate_file
                    if self.verbose:
                        console.print(f"[green]Found readable integrated data: {integrated_file}[/green]")
                    break
                except subprocess.CalledProcessError:
                    if self.verbose:
                        console.print(f"[yellow]Skipping corrupted file: {candidate_file}[/yellow]")
                    continue

            if integrated_file is None:
                raise FileNotFoundError(f"No readable integrated H5AD files found in {integration_dir}. All files appear to be corrupted.")

            return integrated_file
        # For single mode, use annotated data for each sample
        data_dir = Path(project.PROJ_PATH) / "single" / "data" / "annotated"
        sample_paths = []

        for sample_id in target_samples:
            sample_file = data_dir / f"{sample_id}.h5ad"
            if not sample_file.exists():
                console.print(f"[yellow]Warning: Sample file not found: {sample_file}[/yellow]")
                continue
            sample_paths.append(sample_file)

        if not sample_paths:
            raise FileNotFoundError(f"No valid sample files found in {data_dir}. Please run preprocessing first.")

        if self.verbose:
            console.print(f"[blue]Using {len(sample_paths)} single-sample files[/blue]")

        return sample_paths

    def _run_trajectory_analysis(self, input_paths: list[Path] | Path, target_samples: list[str], project: "Project") -> None:
        """Run R-based trajectory analysis."""
        if self.integrate_mode:
            self._run_integrated_trajectory(input_paths, target_samples, project)
        else:
            self._run_single_trajectory(input_paths, target_samples, project)

    def _run_r_with_realtime_output(self, cmd: list[str], cwd: str, env: dict) -> None:
        """Run R command with real-time output instead of buffered output.

        Parameters
        ----------
        cmd : List[str]
            Command to execute
        cwd : str
            Working directory
        env : dict
            Environment variables

        """
        if self.verbose:
            console.print(f"[dim]Executing: {' '.join(cmd)}[/dim]")

        # Use Popen for real-time output
        process = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Combine stderr with stdout
            universal_newlines=True,
            bufsize=1,  # Line buffered
        )

        # Read output line by line and print in real-time
        for line in iter(process.stdout.readline, ""):
            if line:
                # Remove trailing newline and print with R prefix
                line_clean = line.rstrip()
                if line_clean:  # Only print non-empty lines
                    console.print(f"[dim][R] {line_clean}[/dim]")

        # Wait for process to complete
        process.wait()

        # Check return code
        if process.returncode != 0:
            raise subprocess.CalledProcessError(process.returncode, cmd)

    def _run_integrated_trajectory(self, integrated_file: Path, target_samples: list[str], project: "Project") -> None:
        """Run trajectory analysis in integration mode."""
        if self.verbose:
            console.print("[cyan]🧬 Running integrated trajectory analysis...[/cyan]")

        # Step 0: Preprocess data with scVI normalized expression and cell type merging
        try:
            preprocessed_file = self._preprocess_data_with_scvi(integrated_file, project)
        except Exception as e:
            console.print(f"[yellow]Warning: Data preprocessing failed: {e}[/yellow]")
            console.print("[yellow]Using original integrated file[/yellow]")
            preprocessed_file = integrated_file

        # Create sample ID string for R
        sample_ids = ",".join(target_samples)

        # Prepare R command arguments using preprocessed data
        r_args = [
            "--sample_id",
            sample_ids,
            "--h5ad_file",
            str(preprocessed_file),
            "--out_dir",
            str(self.output_dir),
            "--resolution",
            str(self.resolution),
            "--latent_dims",
            self.latent_dims,
            "--cell_cycle_tsv",
            str(self.cell_cycle_markers_file),
            "--root_marker_tsv",
            str(self.root_markers_file),
            "--canonical_marker_tsv",
            str(self.markers_file),
        ]

        if self.force_rerun:
            r_args.extend(["--force_rerun", "TRUE"])

        if self.no_rds:
            r_args.extend(["--no_rds", "TRUE"])

        # Execute R script with real-time output
        try:
            rscript_path = self._get_rscript_path()
            cmd = [rscript_path, str(self.r_script_integrated)] + r_args

            # Set environment variables for R script
            env = os.environ.copy()
            celline_root = Path(project.EXEC_PATH) / "celline"
            env["CELLINE_ROOT"] = str(celline_root)

            # Use real-time output instead of buffered output
            self._run_r_with_realtime_output(cmd, str(self.output_dir), env)

        except subprocess.CalledProcessError as e:
            console.print(f"[red]R script failed with exit code {e.returncode}[/red]")
            raise RuntimeError(f"Trajectory analysis failed: {e}")

    def _preprocess_single_sample_data(self, sample_path: Path, sample_id: str, project: "Project") -> Path:
        """Preprocess single sample data with cell filtering and cell type merging.

        Parameters
        ----------
        sample_path : Path
            Path to the sample H5AD file
        sample_id : str
            Sample identifier
        project : Project
            Celline project object

        Returns
        -------
        Path
            Path to the preprocessed H5AD file

        """
        if self.verbose:
            console.print(f"[cyan]🔬 Preprocessing single sample data for {sample_id}...[/cyan]")

        # Load the data
        adata = sc.read_h5ad(sample_path)
        if self.verbose:
            console.print(f"[blue]Loaded data: {adata.n_obs} cells, {adata.n_vars} genes[/blue]")

        # Step 1: Filter cells using cell_info.tsv if available
        # Find project_ids by scanning data directory
        data_dir = Path(project.PROJ_PATH) / "data"
        project_ids = [d.name for d in data_dir.iterdir() if d.is_dir()]

        # Look for sample_id in all project directories
        sample_dir = None
        for project_id in project_ids:
            candidate_dir = data_dir / project_id / sample_id
            if candidate_dir.exists():
                sample_dir = candidate_dir
                break

        if sample_dir is None:
            if self.verbose:
                console.print(f"[yellow]No sample directory found for {sample_id}[/yellow]")
            # Create a minimal preprocessed file
            preprocessed_path = sample_path.parent / f"preprocessed_{sample_path.name}"
            adata.write_h5ad(preprocessed_path)
            return preprocessed_path

        cell_info_path = sample_dir / "cell_info.tsv"

        if cell_info_path.exists():
            cell_info = pd.read_csv(cell_info_path, sep="\t")
            if self.verbose:
                console.print(f"[green]Loaded cell_info for {sample_id}: {len(cell_info)} cells[/green]")

            # Filter to include=True cells only
            if "include" in cell_info.columns:
                included_cells = cell_info[cell_info["include"] == True]["cell"].tolist()

                # Filter adata to include only these cells
                cell_mask = adata.obs.index.isin(included_cells)
                adata = adata[cell_mask, :].copy()

                if self.verbose:
                    console.print(f"[green]✓ Filtered to {adata.n_obs} cells with include=True[/green]")
            elif self.verbose:
                console.print("[yellow]No 'include' column found in cell_info.tsv[/yellow]")
        elif self.verbose:
            console.print(f"[yellow]No cell_info.tsv found for {sample_id}[/yellow]")

        # Step 2: Merge cell type information from celltype_predicted.tsv
        celltype_path = sample_dir / "celltype_predicted.tsv"
        if celltype_path.exists():
            celltype_info = pd.read_csv(celltype_path, sep="\t")
            if self.verbose:
                console.print(f"[green]Loaded celltype predictions for {sample_id}: {len(celltype_info)} cells[/green]")

            # Merge with adata.obs
            if "cell" in celltype_info.columns:
                # Set cell as index for merging
                celltype_df = celltype_info.set_index("cell")

                # Merge celltype information into adata.obs
                common_cells = adata.obs.index.intersection(celltype_df.index)
                if len(common_cells) > 0:
                    for col in celltype_df.columns:
                        adata.obs[col] = celltype_df.loc[common_cells, col].reindex(adata.obs.index)

                    if self.verbose:
                        console.print(f"[green]✓ Merged celltype info for {len(common_cells)} cells[/green]")
                        # Show which celltype columns were added
                        celltype_cols = list(celltype_df.columns)
                        console.print(f"[blue]Added celltype columns: {celltype_cols}[/blue]")
                elif self.verbose:
                    console.print("[yellow]No matching cells found between data and celltype predictions[/yellow]")
        elif self.verbose:
            console.print(f"[yellow]No celltype_predicted.tsv found for {sample_id}[/yellow]")

        # Step 3: Save preprocessed data
        preprocessed_path = sample_path.parent / f"preprocessed_{sample_path.name}"

        if self.verbose:
            console.print(f"[cyan]Saving preprocessed data to: {preprocessed_path}[/cyan]")

        adata.write_h5ad(preprocessed_path)

        if self.verbose:
            console.print(f"[green]✅ Preprocessed data saved: {adata.n_obs} cells, {adata.n_vars} genes[/green]")

        return preprocessed_path

    def _run_single_trajectory(self, sample_paths: list[Path], target_samples: list[str], project: "Project") -> None:
        """Run trajectory analysis in single mode."""
        if self.verbose:
            console.print("[cyan]🧬 Running single-sample trajectory analysis...[/cyan]")

        for i, (sample_path, sample_id) in enumerate(zip(sample_paths, target_samples, strict=False)):
            if self.verbose:
                console.print(f"[blue]Processing sample {i + 1}/{len(sample_paths)}: {sample_id}[/blue]")

            # Step 0: Preprocess data with cell filtering and cell type merging
            try:
                preprocessed_file = self._preprocess_single_sample_data(sample_path, sample_id, project)
            except Exception as e:
                console.print(f"[yellow]Warning: Data preprocessing failed for {sample_id}: {e}[/yellow]")
                console.print("[yellow]Using original sample file[/yellow]")
                preprocessed_file = sample_path

            # Create sample-specific output directory
            sample_output_dir = self.output_dir / sample_id
            sample_output_dir.mkdir(parents=True, exist_ok=True)

            # Prepare R command arguments using preprocessed data
            r_args = [
                "--sample_id",
                sample_id,
                "--h5ad_files",
                str(preprocessed_file),
                "--out_dir",
                str(sample_output_dir),
                "--resolution",
                str(self.resolution),
                "--n_pcs",
                str(self.n_pcs),
                "--n_features",
                str(self.n_features),
                "--cell_cycle_tsv",
                str(self.cell_cycle_markers_file),
                "--root_marker_tsv",
                str(self.root_markers_file),
                "--canonical_marker_tsv",
                str(self.markers_file),
            ]

            if self.force_rerun:
                r_args.extend(["--force_rerun", "TRUE"])

            if self.no_rds:
                r_args.extend(["--no_rds", "TRUE"])

            # Execute R script with real-time output
            try:
                rscript_path = self._get_rscript_path()
                cmd = [rscript_path, str(self.r_script_single)] + r_args

                # Set environment variables for R script
                env = os.environ.copy()
                celline_root = Path(project.EXEC_PATH) / "celline"
                env["CELLINE_ROOT"] = str(celline_root)

                # Use real-time output instead of buffered output
                self._run_r_with_realtime_output(cmd, str(sample_output_dir), env)

                console.print(f"[green]✅ Sample {sample_id} trajectory analysis completed[/green]")

            except subprocess.CalledProcessError as e:
                console.print(f"[red]R script failed for sample {sample_id} with exit code {e.returncode}[/red]")
                # Continue with other samples instead of failing completely
                console.print(f"[yellow]Skipping sample {sample_id} due to error[/yellow]")
                continue

    def call(self, project: "Project") -> "Project":
        """Execute trajectory analysis.

        Parameters
        ----------
        project : Project
            Celline project object.

        Returns
        -------
        Project
            Updated project object.

        """
        try:
            console.print("[bold blue]🔄 Starting Trajectory Analysis[/bold blue]")

            # Setup paths using project information
            self._setup_paths(project)

            # Check Rscript availability before proceeding
            self._check_rscript_availability()

            # Step 1: Determine target samples first (needed for directory naming)
            target_samples = self._get_target_samples()

            # Setup output directory using project root and sample names for better caching
            # Handle case where custom_output_dir attribute might not exist (CLI compatibility)
            custom_output_dir = getattr(self, "custom_output_dir", None)
            if custom_output_dir is None:
                # Create directory name based on sample IDs for better caching
                sample_dir_name = "_".join(sorted(target_samples))  # Use underscore separator
                # Limit directory name length to avoid filesystem issues
                if len(sample_dir_name) > 100:
                    sample_dir_name = f"{len(target_samples)}samples_{hash(sample_dir_name) % 10000:04d}"

                if self.integrate_mode:
                    self.output_dir = Path(project.PROJ_PATH) / "trajectory" / "integrated" / sample_dir_name
                else:
                    self.output_dir = Path(project.PROJ_PATH) / "trajectory" / "single" / sample_dir_name
            else:
                self.output_dir = Path(custom_output_dir)

            # Ensure output directory exists
            self.output_dir.mkdir(parents=True, exist_ok=True)

            # Step 2: Validate integration mode if requested
            if self.integrate_mode:
                self._validate_integration_mode(project)

            # Step 3: Get input data paths
            input_paths = self._get_input_data_paths(target_samples, project)

            # Step 4: Run trajectory analysis
            self._run_trajectory_analysis(input_paths, target_samples, project)

            # Step 5: Report completion
            console.print("[green]✅ Trajectory analysis completed successfully![/green]")
            console.print(f"[green]Results saved to: {self.output_dir}[/green]")

            # Log completion
            logging.info(f"Trajectory analysis completed for {len(target_samples)} samples")
            logging.info(f"Mode: {'Integration' if self.integrate_mode else 'Single'}")
            logging.info(f"Output directory: {self.output_dir}")

        except Exception as e:
            console.print(f"[red]❌ Trajectory analysis failed: {e}[/red]")
            logging.exception(f"Trajectory analysis failed: {e}")
            raise

        return project

    def cli(self, project: "Project", args: argparse.Namespace | None = None) -> "Project":
        """CLI entry point for predict_trajectory function.
        Properly initializes the instance with CLI arguments.
        """
        if args is not None:
            # Initialize instance with CLI arguments
            instance = self.from_cli_args(args)
            return instance.call(project)
        # Fallback: call with default parameters
        instance = PredictTrajectory()
        return instance.call(project)

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "PredictTrajectory":
        """Create PredictTrajectory instance from parsed CLI arguments."""
        # Handle hyphen to underscore conversion for argparse
        # argparse converts --arg-name to arg_name, but some may use - instead of _
        n_pcs = getattr(args, "n_pcs", None) or getattr(args, "n-pcs", None)
        n_features = getattr(args, "n_features", None) or getattr(args, "n-features", None)
        latent_dims = getattr(args, "latent_dims", None) or getattr(args, "latent-dims", None)
        force_rerun = getattr(args, "force_rerun", False) or getattr(args, "force-rerun", False)
        output_dir = getattr(args, "output_dir", None) or getattr(args, "output-dir", None)
        markers_file = getattr(args, "markers", None)
        no_rds = getattr(args, "no_rds", False) or getattr(args, "no-rds", False)

        return cls(
            integrate_mode=getattr(args, "integrate", False),
            samples=getattr(args, "samples", None),
            projects=getattr(args, "projects", None),
            resolution=getattr(args, "resolution", 0.5),
            n_pcs=n_pcs if n_pcs is not None else 50,
            n_features=n_features if n_features is not None else 2000,
            latent_dims=latent_dims if latent_dims is not None else "1:10",
            force_rerun=force_rerun,
            output_dir=output_dir,
            verbose=getattr(args, "verbose", True),
            markers_file=markers_file,
            no_rds=no_rds,
        )

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        """Add command-line arguments for trajectory analysis."""
        parser.add_argument("--markers", type=str, required=True, help="Path to canonical markers TSV file (gene lists for trajectory analysis)")
        parser.add_argument("--integrate", action="store_true", help="Use integration mode (scVI latent space) instead of single mode (PCA)")
        parser.add_argument("--samples", nargs="*", help="List of specific sample IDs to analyze (e.g., --samples sample1 sample2 or --samples sample1,sample2)")
        parser.add_argument("--projects", nargs="*", help="List of specific project IDs to analyze (e.g., --projects GSE123456 GSE789012 or --projects GSE123456,GSE789012)")
        parser.add_argument("--resolution", type=float, default=0.5, help="Clustering resolution for trajectory inference (default: 0.5)")
        parser.add_argument("--n-pcs", type=int, default=50, help="Number of PCA components for single mode (default: 50)")
        parser.add_argument("--n-features", type=int, default=2000, help="Number of variable features for single mode (default: 2000)")
        parser.add_argument("--latent-dims", type=str, default="1:10", help="Latent dimensions for integration mode (R-style range, default: '1:10')")
        parser.add_argument("--force-rerun", action="store_true", help="Force rerun even if cached results exist")
        parser.add_argument("--no-rds", action="store_true", help="Skip saving RDS files (sce.rds, seurat.rds) for faster processing")
        parser.add_argument("--output-dir", type=str, help="Custom output directory (default: auto-generated)")
        parser.add_argument("--verbose", action="store_true", default=True, help="Show detailed progress (default: True)")

    def get_description(self) -> str:
        """Return function description for help."""
        return "Trajectory inference using slingshot in integration or single-sample modes"

    def get_usage_examples(self) -> list[str]:
        """Return usage examples."""
        return [
            "celline run predict_trajectory",
            "celline run predict_trajectory --integrate",
            "celline run predict_trajectory --samples sample1 sample2",
            "celline run predict_trajectory --integrate --projects GSE123456",
            "celline run predict_trajectory --resolution 0.3 --n-pcs 30",
        ]


# For backward compatibility and direct usage
# PredictTrajectory = PredictTrajectory
