"""
Custom data handler for user-defined samples.
Handles samples that cannot be resolved by standard handlers (GEO, SRA, etc.)
"""

from __future__ import annotations
from typing import Optional, Dict, Any
import os
import shutil
from pathlib import Path as PathLib

import questionary
from questionary import Style
from rich.console import Console
from rich.prompt import Prompt, Confirm
from rich.panel import Panel
from rich.table import Table

from celline.DB.dev.handler import BaseHandler
from celline.DB.dev.model import BaseModel, BaseSchema, SampleSchema, RunSchema
from celline.utils.path import Path
from celline.log.logger import get_logger

console = Console()
logger = get_logger(__name__)

# Custom style for questionary
custom_style = Style([
    ('qmark', 'fg:#673ab7 bold'),
    ('question', 'bold'),
    ('answer', 'fg:#2196f3 bold'),
    ('pointer', 'fg:#673ab7 bold'),
    ('highlighted', 'fg:#673ab7 bold'),
    ('selected', 'fg:#2196f3'),
    ('separator', 'fg:#cc5454'),
    ('instruction', ''),
    ('text', ''),
])


# Define schemas without @dataclass decorator to avoid module loading issues
# These will inherit dataclass from BaseSchema/SampleSchema/RunSchema
class CustomProjectSchema(BaseSchema):
    """Schema for custom projects."""
    summary: Optional[str] = None

    def __init__(self, key, parent=None, children=None, title=None, summary=None):
        self.key = key
        self.parent = parent
        self.children = children
        self.title = title
        self.summary = summary


class CustomSampleSchema(SampleSchema):
    """Schema for custom samples."""

    def __init__(self, key, parent=None, children=None, title=None,
                 summary="", species="Unknown", raw_link=""):
        self.key = key
        self.parent = parent
        self.children = children
        self.title = title
        self.summary = summary
        self.species = species
        self.raw_link = raw_link


class CustomRunSchema(RunSchema):
    """Schema for custom runs."""

    def __init__(self, key, parent=None, children=None, title=None,
                 strategy="", raw_link=""):
        self.key = key
        self.parent = parent
        self.children = children
        self.title = title
        self.strategy = strategy
        self.raw_link = raw_link


class CustomProject(BaseModel[CustomProjectSchema]):
    """Model for custom projects."""

    def set_class_name(self) -> str:
        return "CustomProject"

    def def_schema(self) -> type[CustomProjectSchema]:
        return CustomProjectSchema

    def search(self, acceptable_id: str, force_search=False) -> CustomProjectSchema:
        """Custom projects are added interactively, not searched."""
        cache = self.get_cache(acceptable_id, force_search)
        if cache is not None:
            return cache
        raise NotImplementedError("Custom projects must be added interactively")


class CustomSample(BaseModel[CustomSampleSchema]):
    """Model for custom samples."""

    def set_class_name(self) -> str:
        return "CustomSample"

    def def_schema(self) -> type[CustomSampleSchema]:
        return CustomSampleSchema

    def search(self, acceptable_id: str, force_search=False) -> CustomSampleSchema:
        """Custom samples are added interactively, not searched."""
        cache = self.get_cache(acceptable_id, force_search)
        if cache is not None:
            return cache
        raise NotImplementedError("Custom samples must be added interactively")


class CustomRun(BaseModel[CustomRunSchema]):
    """Model for custom runs."""

    def set_class_name(self) -> str:
        return "CustomRun"

    def def_schema(self) -> type[CustomRunSchema]:
        return CustomRunSchema

    def search(self, acceptable_id: str, force_search=False) -> CustomRunSchema:
        """Custom runs are added interactively, not searched."""
        cache = self.get_cache(acceptable_id, force_search)
        if cache is not None:
            return cache
        raise NotImplementedError("Custom runs must be added interactively")


class CustomDataHandler(BaseHandler[CustomProject, CustomSample, CustomRun]):
    """Handler for custom user-defined data."""

    def __init__(self):
        super().__init__()
        self._project = CustomProject()
        self._sample = CustomSample()
        self._run = CustomRun()

    def resolver(self, acceptable_id: str) -> Optional[type]:
        """
        This handler doesn't auto-resolve.
        It's called explicitly when other handlers fail.
        """
        return None

    def add_interactive(self, custom_id: str) -> None:
        """
        Add custom data interactively.

        Args:
            custom_id: User-defined identifier

        Raises:
            KeyboardInterrupt: If user cancels the operation
        """
        logger.info(f"Starting interactive custom data addition for {custom_id}")

        console.print(Panel.fit(
            f"[bold cyan]Adding Custom Data: {custom_id}[/bold cyan]\n\n"
            "This ID could not be resolved by standard handlers (GEO, SRA, etc.).\n"
            "Let's add it as custom data.\n\n"
            "[dim]Press Ctrl+C at any time to cancel[/dim]",
            title="Custom Data Entry",
            border_style="cyan"
        ))

        try:
            # Step 1: Determine type
            data_type = self._prompt_data_type()
            if data_type is None:
                raise KeyboardInterrupt("User cancelled data type selection")

            # Step 2: Get data source
            source_type, source_path = self._prompt_data_source()
            if source_type is None or source_path is None:
                raise KeyboardInterrupt("User cancelled data source selection")

            # Step 3: Get metadata
            metadata = self._prompt_metadata(custom_id, data_type)
            if metadata is None:
                raise KeyboardInterrupt("User cancelled metadata entry")

            # Step 4: Add to database
            self._add_to_database(custom_id, data_type, source_type, source_path, metadata)

            console.print(f"\n[green]✓ Successfully added custom data: {custom_id}[/green]")

        except KeyboardInterrupt:
            console.print("\n[yellow]⚠ Custom data entry cancelled by user[/yellow]")
            logger.warning(f"Custom data entry cancelled for {custom_id}")
            raise

    def _prompt_data_type(self) -> Optional[str]:
        """Prompt user for data type (project/sample/run).

        Returns:
            str: Selected data type, or None if cancelled
        """
        console.print("\n[bold]Step 1:[/bold] What type of data is this?")

        choices = [
            questionary.Choice(
                title="Sample - An individual biological sample (most common)",
                value="sample"
            ),
            questionary.Choice(
                title="Project - A collection of samples",
                value="project"
            ),
            questionary.Choice(
                title="Run - A sequencing run",
                value="run"
            ),
        ]

        result = questionary.select(
            "Select data type:",
            choices=choices,
            style=custom_style,
            use_arrow_keys=True,
            use_shortcuts=False,
            instruction="(Use arrow keys, press Enter to select)"
        ).ask()

        return result

    def _prompt_data_source(self) -> tuple[Optional[str], Optional[str]]:
        """Prompt user for data source type and path.

        Returns:
            tuple: (source_type, source_path), or (None, None) if cancelled
        """
        console.print("\n[bold]Step 2:[/bold] What type of data do you have?")

        choices = [
            questionary.Choice(
                title="FASTQ files - Raw sequencing reads (.fastq/.fq)",
                value="fastq"
            ),
            questionary.Choice(
                title="BAM files - Aligned reads (.bam)",
                value="bam"
            ),
            questionary.Choice(
                title="Counted matrix - Cell Ranger output (filtered_feature_bc_matrix/)",
                value="counted"
            ),
        ]

        source_type = questionary.select(
            "Select data type:",
            choices=choices,
            style=custom_style,
            use_arrow_keys=True,
            use_shortcuts=False,
            instruction="(Use arrow keys, press Enter to select)"
        ).ask()

        if source_type is None:
            return None, None

        # Get path
        console.print(f"\n[bold]Step 3:[/bold] Enter the path to your {source_type} data")

        while True:
            source_path = questionary.path(
                "Data path:",
                style=custom_style,
                validate=lambda p: True if p else "Path cannot be empty"
            ).ask()

            if source_path is None:
                return None, None

            source_path = os.path.expanduser(source_path)

            if os.path.exists(source_path):
                console.print(f"[green]✓ Path validated: {source_path}[/green]")
                break
            else:
                console.print(f"[red]✗ Path does not exist: {source_path}[/red]")
                retry = questionary.confirm(
                    "Try again?",
                    default=True,
                    style=custom_style
                ).ask()

                if retry is None or not retry:
                    return None, None

        return source_type, source_path

    def _prompt_metadata(self, custom_id: str, data_type: str) -> Optional[Dict[str, Any]]:
        """Prompt user for metadata.

        Returns:
            dict: Metadata dictionary, or None if cancelled
        """
        console.print("\n[bold]Step 4:[/bold] Enter metadata (optional fields can be left blank)")

        metadata: Dict[str, Any] = {}

        try:
            # Title
            title = questionary.text(
                "Title (descriptive name):",
                default=custom_id,
                style=custom_style
            ).ask()

            if title is None:
                return None
            metadata["title"] = title

            # Species (only for samples)
            if data_type == "sample":
                species = questionary.text(
                    "Species (e.g., Homo sapiens):",
                    default="Unknown",
                    style=custom_style
                ).ask()

                if species is None:
                    return None
                metadata["species"] = species

            # Summary
            summary = questionary.text(
                "Summary (brief description):",
                default="",
                style=custom_style
            ).ask()

            if summary is None:
                return None
            metadata["summary"] = summary

            # Parent/Children
            if data_type == "sample":
                parent = questionary.text(
                    "Parent project ID (leave empty if none):",
                    default="",
                    style=custom_style
                ).ask()

                if parent is None:
                    return None
                metadata["parent"] = parent

            elif data_type == "run":
                parent = questionary.text(
                    "Parent sample ID (required for runs):",
                    default="",
                    style=custom_style
                ).ask()

                if parent is None:
                    return None
                metadata["parent"] = parent

            return metadata

        except KeyboardInterrupt:
            return None

    def _add_to_database(
        self,
        custom_id: str,
        data_type: str,
        source_type: str,
        source_path: str,
        metadata: Dict[str, Any]
    ) -> None:
        """Add custom data to database and copy files."""
        logger.info(f"Adding {custom_id} to database as {data_type}")

        # Determine parent/project ID
        if data_type == "sample":
            parent_id = metadata.get("parent", "")
            project_id = parent_id if parent_id else "CUSTOM_PROJECT"
        elif data_type == "run":
            parent_id = metadata.get("parent", "")
            if not parent_id:
                raise ValueError("Run must have a parent sample ID")
            # Get sample's project
            sample_record = self._excel_handler.get_record("samples", parent_id)
            project_id = sample_record.get("parent", "CUSTOM_PROJECT") if sample_record else "CUSTOM_PROJECT"
        else:  # project
            project_id = custom_id
            parent_id = ""

        # Create project path structure
        if data_type == "sample":
            path = Path(project_id, custom_id)
            path.prepare()

            # Copy data based on source type
            self._copy_data(source_path, source_type, path)

            # Add to database
            schema = CustomSampleSchema(
                key=custom_id,
                title=metadata.get("title", custom_id),
                summary=metadata.get("summary", ""),
                species=metadata.get("species", "Unknown"),
                raw_link=source_path,
                parent=parent_id if parent_id else None,
                children=None
            )
            self._sample.add_schema(schema)

            # Add to available_samples
            self._excel_handler.add_to_available_samples(custom_id)

            # Create default project if needed
            if not parent_id and not self._project.exists(project_id):
                self._create_default_project(project_id, custom_id)

        elif data_type == "run":
            # Runs are typically handled within samples
            console.print("[yellow]Note: Custom runs should typically be added as part of samples[/yellow]")

        elif data_type == "project":
            # Add project
            schema = CustomProjectSchema(
                key=custom_id,
                title=metadata.get("title", custom_id),
                summary=metadata.get("summary", ""),
                parent=None,
                children=None
            )
            self._project.add_schema(schema)

    def _copy_data(self, source_path: str, source_type: str, path: Path) -> None:
        """Copy data to appropriate location in project structure.

        Directory structure:
        - FASTQ: resources/{project}/{sample}/raw/fastqs/
        - BAM: resources/{project}/{sample}/raw/ (will be converted to fastqs by cellranger)
        - Counted: resources/{project}/{sample}/counted/outs/
        """
        logger.info(f"Copying {source_type} data from {source_path}")

        if source_type == "fastq":
            # Copy to raw/fastqs directory (same as standard download)
            dest_dir = path.resources_sample_raw_fastqs
            os.makedirs(dest_dir, exist_ok=True)

            # Copy all FASTQ files
            source_p = PathLib(source_path)
            if source_p.is_dir():
                # Copy all fastq files from directory
                fastq_files = list(source_p.glob("*.f*q*"))
                if not fastq_files:
                    console.print(f"[yellow]Warning: No FASTQ files found in {source_path}[/yellow]")
                for fq_file in fastq_files:
                    shutil.copy2(fq_file, dest_dir)
                    logger.info(f"Copied {fq_file.name} to {dest_dir}")
                console.print(f"[green]Copied {len(fastq_files)} FASTQ file(s) to {dest_dir}[/green]")
            else:
                # Single file
                shutil.copy2(source_path, dest_dir)
                logger.info(f"Copied {source_path} to {dest_dir}")
                console.print(f"[green]Copied FASTQ file to {dest_dir}[/green]")

        elif source_type == "bam":
            # Copy to raw directory (cellranger bamtofastq will convert to fastqs/)
            dest_dir = path.resources_sample_raw
            os.makedirs(dest_dir, exist_ok=True)

            source_p = PathLib(source_path)
            if source_p.is_dir():
                # Copy all BAM files from directory
                bam_files = list(source_p.glob("*.bam*"))
                if not bam_files:
                    console.print(f"[yellow]Warning: No BAM files found in {source_path}[/yellow]")
                for bam_file in bam_files:
                    shutil.copy2(bam_file, dest_dir)
                    logger.info(f"Copied {bam_file.name} to {dest_dir}")
                console.print(f"[green]Copied {len(bam_files)} BAM file(s) to {dest_dir}[/green]")
            else:
                # Single BAM file
                shutil.copy2(source_path, dest_dir)
                logger.info(f"Copied {source_path} to {dest_dir}")
                console.print(f"[green]Copied BAM file to {dest_dir}[/green]")

            console.print(f"[cyan]Note: Use 'cellranger bamtofastq' to convert BAM to FASTQ if needed[/cyan]")

        elif source_type == "counted":
            # Copy to counted/outs/ (Cell Ranger output directory)
            dest_dir = path.resources_sample_counted
            outs_dir = f"{dest_dir}/outs"
            os.makedirs(dest_dir, exist_ok=True)

            # Copy entire directory structure
            source_p = PathLib(source_path)
            if source_p.is_dir():
                # Check if source already has 'outs' subdirectory
                if (source_p / "outs").exists():
                    # Copy the parent directory structure
                    shutil.copytree(source_path, dest_dir, dirs_exist_ok=True)
                    logger.info(f"Copied Cell Ranger output from {source_path} to {dest_dir}")
                    console.print(f"[green]Copied Cell Ranger output to {dest_dir}[/green]")
                else:
                    # Source is the outs directory itself
                    shutil.copytree(source_path, outs_dir, dirs_exist_ok=True)
                    logger.info(f"Copied counted matrix from {source_path} to {outs_dir}")
                    console.print(f"[green]Copied counted matrix to {outs_dir}[/green]")
            else:
                console.print(f"[yellow]Warning: Expected directory for counted matrix, got file: {source_path}[/yellow]")
                logger.warning(f"Counted matrix should be a directory, got file: {source_path}")

    def _create_default_project(self, project_id: str, sample_id: str) -> None:
        """Create a default project for custom sample."""
        logger.info(f"Creating default project {project_id} for sample {sample_id}")

        schema = CustomProjectSchema(
            key=project_id,
            title=f"Custom Project for {sample_id}",
            summary="Automatically created project for custom sample",
            parent=None,
            children=sample_id
        )
        self._project.add_schema(schema)
