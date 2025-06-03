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
        Represents job information for data download.
        """

        nthread: str
        cluster_server: str
        jobname: str
        logpath: str
        sample_id: str
        dist_dir: str
        fq_path: str
        transcriptome: str

    def __init__(
        self,
        nthread: int,
        then: Optional[Callable[[str], None]] = None,
        catch: Optional[Callable[[subprocess.CalledProcessError], None]] = None,
    ) -> None:
        """
        #### Count donwloaded fastqs
        """
        self.job_mode: Final[ServerSystem.JobType] = ServerSystem.job_system
        self.nthread: Final[int] = nthread
        self.then: Final[Optional[Callable[[str], None]]] = then
        self.catch: Final[
            Optional[Callable[[subprocess.CalledProcessError], None]]
        ] = catch
        self.cluster_server: Final[Optional[str]] = ServerSystem.cluster_server_name
        if self.job_mode == ServerSystem.JobType.PBS and self.cluster_server is None:
            raise SyntaxError(
                "If you use PBS job system, please define cluster_server."
            )

    def call(self, project: "Project") -> "Project":
        sample_info_file = f"{Config.PROJ_ROOT}/samples.toml"
        if not os.path.isfile(sample_info_file):
            print("sample.toml could not be found. Skipping.")
            return project
        with open(sample_info_file, mode="r", encoding="utf-8") as f:
            samples: Dict[str, str] = toml.load(f)
            all_job_files: List[str] = []
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
                transcriptome = Transcriptome().search(sample_schema.species)

                if transcriptome is None:
                    raise LookupError(
                        f"Could not find transcriptome of {sample_schema.species}. Please add or build & register transcriptomes using celline.DB.model.Transcriptome.add_path(species: str, built_path: str) or build(species: str, ...)"
                    )
                if not os.path.isdir(f"{path.resources_sample_counted}/outs"):
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
        ThreadObservable.call_shell(all_job_files).watch()
        return project

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        """Add CLI arguments for the Count function."""
        parser.add_argument(
            '--nthread', '-n',
            type=int,
            default=1,
            help='Number of threads to use for counting (default: 1)'
        )

    def cli(self, project: "Project", args: Optional[argparse.Namespace] = None) -> "Project":
        """CLI entry point for Count function."""
        nthread = 1
        if args and hasattr(args, 'nthread'):
            nthread = args.nthread
            
        console.print(f"[cyan]Starting count with {nthread} thread(s)...[/cyan]")
        
        # Create Count instance and call it
        count_instance = Count(nthread)
        return count_instance.call(project)

    def get_description(self) -> str:
        """Get description for CLI help."""
        return """Count downloaded FASTQ files using Cell Ranger.
        
This function processes downloaded raw sequencing data and generates 
feature-barcode matrices using Cell Ranger count."""

    def get_usage_examples(self) -> list[str]:
        """Get usage examples for CLI help."""
        return [
            "celline run count",
            "celline run count --nthread 8"
        ]
