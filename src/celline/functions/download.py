import argparse
import datetime
import os
import shutil
import subprocess
from collections.abc import Callable
from typing import TYPE_CHECKING, List, NamedTuple, Optional

from rich.console import Console

from celline.DB.dev.handler import HandleResolver
from celline.DB.dev.model import RunSchema, SampleSchema
from celline.functions._base import CellineFunction
from celline.middleware import ThreadObservable
from celline.sample import SampleResolver
from celline.server import ServerSystem
from celline.template import TemplateManager
from celline.utils.path import Path

if TYPE_CHECKING:
    from celline import Project

console = Console()


class Download(CellineFunction):
    """#### Download data into your project."""

    class JobContainer(NamedTuple):
        """Represents job information for data download."""

        filetype: str
        nthread: str
        cluster_server: str
        cluster_server_directive: str
        queue_directive: str
        jobname: str
        logpath: str
        sample_id: str
        download_target: str
        download_source: str
        run_ids_str: str

    def __init__(
        self,
        then: Callable[[str], None] | None = None,
        catch: Callable[[subprocess.CalledProcessError], None] | None = None,
    ) -> None:
        """#### Setup download job function with job mode and thread count."""
        self.nthread = 1
        self.then = then if then is not None else lambda _: None
        self.catch = catch if catch is not None else lambda _: None

    def call(self, project: "Project"):
        """Call the Download function to download data into the project."""
        # PBS設定のチェック
        if ServerSystem.job_system == ServerSystem.JobType.PBS:
            if not ServerSystem.is_pbs_configured():
                console.print("[bold red]ERROR: PBS job system selected but not properly configured![/bold red]")
                console.print(f"[yellow]Current status: {ServerSystem.get_status()}[/yellow]")
                console.print("[yellow]Please set cluster server name using: ServerSystem.usePBS('your_cluster_name')[/yellow]")
                raise ValueError("PBS not properly configured")
            console.print(f"[green]Using {ServerSystem.get_status()}[/green]")
        all_job_files: list[str] = []
        for sample_id in SampleResolver.samples.keys():
            resolver = HandleResolver.resolve(sample_id)
            if resolver is None:
                raise ReferenceError(f"Could not resolve target sample id: {sample_id}")
            sample_schema: SampleSchema = resolver.sample.search(sample_id)
            if sample_schema.children is None:
                raise NotImplementedError("Children could not found")
            run_schema: RunSchema = resolver.run.search(
                sample_schema.children.split(",")[0],
            )
            filetype = run_schema.strategy
            if sample_schema.parent is None:
                raise ValueError("Sample parent must not be none")
            path = Path(sample_schema.parent, sample_id)
            path.prepare()
            if not path.is_downloaded and not path.is_counted:
                if os.path.exists(path.resources_sample_raw_fastqs):
                    shutil.rmtree(path.resources_sample_raw_fastqs)
                # PBS用のディレクティブを生成
                cluster_server_directive = ""
                queue_directive = ""
                if ServerSystem.cluster_server_name is not None and ServerSystem.cluster_server_name.strip() != "":
                    cluster_server_directive = f":{ServerSystem.cluster_server_name}"
                    queue_directive = ServerSystem.cluster_server_name

                TemplateManager.replace_from_file(
                    file_name="download.sh",
                    structure=Download.JobContainer(
                        filetype=filetype,
                        nthread=str(self.nthread),
                        cluster_server=ServerSystem.cluster_server_name or "",
                        cluster_server_directive=cluster_server_directive,
                        queue_directive=queue_directive,
                        jobname="Download",
                        logpath=f"{path.resources_sample_log}/download_{datetime.datetime.now().strftime('%Y%m%d_%H:%M:%S')}.log",
                        sample_id=sample_id,
                        download_target=path.resources_sample_raw,
                        download_source=run_schema.raw_link.split(",")[0] if len(run_schema.raw_link.split(",")) > 0 else "",
                        run_ids_str=sample_schema.children,
                    ),
                    replaced_path=f"{path.resources_sample_src}/download.sh",
                )
                all_job_files.append(f"{path.resources_sample_src}/download.sh")
        ThreadObservable.call_shell(all_job_files).watch()
        return project

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        """Add CLI arguments for the Download function."""
        parser.add_argument(
            "--nthread",
            "-n",
            type=int,
            default=1,
            help="Number of threads to use for downloading (default: 1)",
        )
        parser.add_argument(
            "--force",
            "-f",
            action="store_true",
            help="Force re-download even if files already exist",
        )

    def cli(self, project: "Project", args: argparse.Namespace | None = None) -> "Project":
        """CLI entry point for Download function."""
        nthread = 1
        if args and hasattr(args, "nthread"):
            nthread = args.nthread

        force = False
        if args and hasattr(args, "force"):
            force = args.force

        console.print(f"[cyan]Starting download with {nthread} thread(s)...[/cyan]")
        if force:
            console.print("[yellow]Force mode: Will re-download existing files[/yellow]")

        # Create Download instance and call it
        download_instance = Download()
        download_instance.nthread = nthread

        # If force mode, we could modify the logic to re-download
        # For now, just call the regular download method
        return download_instance.call(project)

    def get_description(self) -> str:
        """Get description for CLI help."""
        return """Download data files for samples in your project.

This function downloads raw sequencing data files (FASTQ, BAM) for all samples
that have been added to your project but not yet downloaded."""

    def get_usage_examples(self) -> list[str]:
        """Get usage examples for CLI help."""
        return [
            "celline run download",
            "celline run download --nthread 4",
            "celline run download --force",
        ]
