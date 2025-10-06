import argparse
import datetime
import os
import subprocess
from typing import TYPE_CHECKING, Callable, Dict, Final, List, NamedTuple, Optional

import toml
from rich.console import Console

from celline.DB.dev.handler import HandleResolver
from celline.DB.dev.model import SampleSchema
from celline.DB.model import SRA_GSE, SRA_GSM, SRA_SRR, Transcriptome
from celline.config import Config
from celline.functions._base import CellineFunction
from celline.middleware import Shell, ThreadObservable
from celline.server import ServerSystem
from celline.template import TemplateManager
from celline.utils.path import Path

if TYPE_CHECKING:
    from celline import Project

console = Console()


class Count(CellineFunction):
    class JobContainer(NamedTuple):
        """
        Represents job information for counting.
        """

        nthread: str
        cluster_server: str
        jobname: str
        logpath: str
        sample_id: str
        dist_dir: str
        fq_path: str
        transcriptome: str

    class StarsoloJobContainer(NamedTuple):
        """
        Represents job information for STARsolo counting.
        """

        nthread: str
        cluster_server: str
        jobname: str
        logpath: str
        sample_id: str
        dist_dir: str
        fq_path: str
        genome_dir: str
        chemistry: str
        feature_type: str

    def __init__(
        self,
        nthread: int,
        tool: str = "cellranger",
        chemistry: str = "auto",
        feature_type: str = "Gene",
        then: Optional[Callable[[str], None]] = None,
        catch: Optional[Callable[[subprocess.CalledProcessError], None]] = None,
    ) -> None:
        """
        #### Count downloaded fastqs using Cell Ranger or STARsolo

        Args:
            nthread: Number of threads to use
            tool: Counting tool to use ('cellranger' or 'starsolo')
            chemistry: 10x chemistry version ('auto', 'v2', 'v3') - only for STARsolo
            feature_type: Feature type to count ('Gene', 'GeneFull', 'Velocyto') - only for STARsolo
            then: Callback function on success
            catch: Callback function on error
        """
        self.job_mode: Final[ServerSystem.JobType] = ServerSystem.job_system
        self.nthread: Final[int] = nthread
        self.tool: Final[str] = tool.lower()
        self.chemistry: Final[str] = chemistry
        self.feature_type: Final[str] = feature_type
        self.then: Final[Optional[Callable[[str], None]]] = then
        self.catch: Final[
            Optional[Callable[[subprocess.CalledProcessError], None]]
        ] = catch
        self.cluster_server: Final[Optional[str]] = ServerSystem.cluster_server_name

        # Validate tool
        if self.tool not in ["cellranger", "starsolo"]:
            raise ValueError(f"Invalid tool: {self.tool}. Must be 'cellranger' or 'starsolo'")

        # Validate chemistry
        if self.chemistry not in ["auto", "v2", "v3"]:
            raise ValueError(f"Invalid chemistry: {self.chemistry}. Must be 'auto', 'v2', or 'v3'")

        # Validate feature type
        if self.feature_type not in ["Gene", "GeneFull", "Velocyto"]:
            raise ValueError(f"Invalid feature_type: {self.feature_type}. Must be 'Gene', 'GeneFull', or 'Velocyto'")

        if self.job_mode == ServerSystem.JobType.PBS and self.cluster_server is None:
            raise SyntaxError(
                "If you use PBS job system, please define cluster_server."
            )

    def call(self, project: "Project") -> "Project":
        from celline.DB.dev.excel_handler import ExcelMetadataHandler

        if Config.current in Config.runnings:
            excel_path = f"{Config.runnings[Config.current].PROJ_ROOT}/metadata.xlsx"
        else:
            raise RuntimeError("Config not initialized")

        if not os.path.isfile(excel_path):
            print("metadata.xlsx could not be found. Skipping.")
            return project

        excel_handler = ExcelMetadataHandler(excel_path)
        samples_keys = excel_handler.get_all_keys("samples")
        all_job_files: List[str] = []

        console.print(f"[cyan]Using {self.tool} for counting[/cyan]")
        if self.tool == "starsolo":
            console.print(f"[cyan]Chemistry: {self.chemistry}, Feature type: {self.feature_type}[/cyan]")

        for sample_id in samples_keys:
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

            # Check if already counted
            if os.path.isdir(f"{path.resources_sample_counted}/outs"):
                console.print(f"[yellow]Skipping {sample_id}: already counted[/yellow]")
                continue

            if self.tool == "cellranger":
                # Cell Ranger counting
                transcriptome = Transcriptome().search(sample_schema.species)
                if transcriptome is None:
                    raise LookupError(
                        f"Could not find transcriptome of {sample_schema.species}. "
                        f"Please add or build & register transcriptomes using "
                        f"celline.DB.model.Transcriptome.add_path(species: str, built_path: str) or build(species: str, ...)"
                    )

                TemplateManager.replace_from_file(
                    file_name="count.sh",
                    structure=Count.JobContainer(
                        nthread=str(self.nthread),
                        cluster_server=""
                        if self.cluster_server is None
                        else self.cluster_server,
                        jobname="Count",
                        logpath=path.resources_log_file("count"),
                        sample_id=sample_id,
                        fq_path=path.resources_sample_raw_fastqs,
                        dist_dir=path.resources_sample,
                        transcriptome=transcriptome,
                    ),
                    replaced_path=f"{path.resources_sample_src}/count.sh",
                )
                all_job_files.append(f"{path.resources_sample_src}/count.sh")

            elif self.tool == "starsolo":
                # STARsolo counting
                genome_dir = Transcriptome().search_star_index(sample_schema.species)
                if genome_dir is None:
                    raise LookupError(
                        f"Could not find STAR index for {sample_schema.species}. "
                        f"Please build STAR index using: "
                        f"STAR --runMode genomeGenerate --genomeDir <dir> --genomeFastaFiles <fa> --sjdbGTFfile <gtf>"
                    )

                TemplateManager.replace_from_file(
                    file_name="starsolo.sh",
                    structure=Count.StarsoloJobContainer(
                        nthread=str(self.nthread),
                        cluster_server=""
                        if self.cluster_server is None
                        else self.cluster_server,
                        jobname="STARsolo",
                        logpath=path.resources_log_file("starsolo"),
                        sample_id=sample_id,
                        fq_path=path.resources_sample_raw_fastqs,
                        dist_dir=path.resources_sample,
                        genome_dir=genome_dir,
                        chemistry=self.chemistry,
                        feature_type=self.feature_type,
                    ),
                    replaced_path=f"{path.resources_sample_src}/starsolo.sh",
                )
                all_job_files.append(f"{path.resources_sample_src}/starsolo.sh")

        if all_job_files:
            ThreadObservable.call_shell(all_job_files).watch()
        else:
            console.print("[green]All samples already counted[/green]")

        return project

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        """Add CLI arguments for the Count function."""
        parser.add_argument(
            '--nthread', '-n',
            type=int,
            default=1,
            help='Number of threads to use for counting (default: 1)'
        )
        parser.add_argument(
            '--tool', '-t',
            type=str,
            choices=['cellranger', 'starsolo'],
            default='cellranger',
            help='Counting tool to use: cellranger or starsolo (default: cellranger)'
        )
        parser.add_argument(
            '--chemistry', '-c',
            type=str,
            choices=['auto', 'v2', 'v3'],
            default='auto',
            help='10x chemistry version for STARsolo: auto, v2, or v3 (default: auto)'
        )
        parser.add_argument(
            '--feature-type', '-f',
            type=str,
            choices=['Gene', 'GeneFull', 'Velocyto'],
            default='Gene',
            help='Feature type for STARsolo: Gene, GeneFull, or Velocyto (default: Gene)'
        )

    def cli(self, project: "Project", args: Optional[argparse.Namespace] = None) -> "Project":
        """CLI entry point for Count function."""
        nthread = 1
        tool = "cellranger"
        chemistry = "auto"
        feature_type = "Gene"

        if args:
            if hasattr(args, 'nthread'):
                nthread = args.nthread
            if hasattr(args, 'tool'):
                tool = args.tool
            if hasattr(args, 'chemistry'):
                chemistry = args.chemistry
            if hasattr(args, 'feature_type'):
                feature_type = args.feature_type

        console.print(f"[cyan]Starting count with {nthread} thread(s) using {tool}...[/cyan]")
        if tool == "starsolo":
            console.print(f"[cyan]STARsolo settings: chemistry={chemistry}, feature_type={feature_type}[/cyan]")

        # Create Count instance and call it
        count_instance = Count(
            nthread=nthread,
            tool=tool,
            chemistry=chemistry,
            feature_type=feature_type
        )
        return count_instance.call(project)

    def get_description(self) -> str:
        """Get description for CLI help."""
        return """Count downloaded FASTQ files using Cell Ranger or STARsolo.

This function processes downloaded raw sequencing data and generates
feature-barcode matrices. Supports both Cell Ranger and STARsolo for counting.

STARsolo is ~10x faster than Cell Ranger and produces compatible output."""

    def get_usage_examples(self) -> list[str]:
        """Get usage examples for CLI help."""
        return [
            "celline run count",
            "celline run count --nthread 8",
            "celline run count --tool starsolo --nthread 16",
            "celline run count --tool starsolo --chemistry v3 --feature-type GeneFull"
        ]
