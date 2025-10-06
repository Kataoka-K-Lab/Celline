import argparse
import os
from typing import TYPE_CHECKING, NamedTuple, Optional, Union

import polars as pl
import toml
from rich.progress import track
from rich.console import Console

from celline.config import Config
from celline.DB.dev.handler import HandleResolver
from celline.functions._base import CellineFunction
from celline.utils.serialization import NamedTupleAndPolarsStructure
from celline.log.logger import get_logger

if TYPE_CHECKING:
    from celline import Project

console = Console()
logger = get_logger(__name__)


class Add(CellineFunction):
    """Add accession ID to your project."""

    class SampleInfo(NamedTuple):
        id: str
        title: Optional[str] = ""

    def __init__(self, sample_id: Union[list[SampleInfo], pl.DataFrame], use_ai: bool = False, ai_provider: str = "auto") -> None:
        """#### Add accession ID to DB & your project.

        #### Note: Parallel calculations are not supported

        Args:
            sample_id (<List[Add.SampleInfo]> | <pl.DataFrame>): Accession ID to add.
            use_ai (bool): Enable AI metadata extraction (default: False)
            ai_provider (str): AI provider to use ("openai", "claude", or "auto")

        """
        self.add_target_id: list[Add.SampleInfo] = []
        self.use_ai = use_ai
        self.ai_provider = ai_provider

        if isinstance(sample_id, pl.DataFrame):
            if not all(column in sample_id.columns for column in ["id", "title"]):
                raise KeyError(
                    "The given DataFrame must consist of an id column and a title column.",
                )
            sample_id = NamedTupleAndPolarsStructure[Add.SampleInfo].deserialize(
                sample_id.select(pl.col(["id", "title"])),
                Add.SampleInfo,
            )
            self.add_target_id: list[Add.SampleInfo] = sample_id
        elif isinstance(sample_id, list) and all(isinstance(item, Add.SampleInfo) for item in sample_id):
            self.add_target_id: list[Add.SampleInfo] = sample_id
        else:
            raise ValueError("Add target id should be `list[Add.SampleInfo]` or `polars.DataFrame`")  # noqa: TRY004

    def get_samples(self) -> dict[str, dict[str, str]]:
        """Get sample information from samples.toml file.

        Returns:
            Dict[str, Dict[str, str]]: Samples information.

        """
        sample_info_file = f"{Config.PROJ_ROOT}/samples.toml"
        samples: dict[str, dict[str, str]] = {}
        if os.path.isfile(sample_info_file):
            with open(sample_info_file, encoding="utf-8") as f:
                all_data = toml.load(f)
                samples = all_data.get("samples", {})
        return samples

    def call(self, project: "Project") -> "Project":
        """Call the function to add accession IDs to the project.

        Args:
            project (<Project>): The project to add the accession IDs to.

        Returns:
            <Project>: The project with the added accession IDs.

        """
        logger.info(f"Starting to add {len(self.add_target_id)} sample(s) to project")

        # Pre-check: Determine if any IDs need interactive custom data entry
        needs_interactive = []
        standard_ids = []

        for tid in self.add_target_id:
            resolver = HandleResolver.resolve(tid.id)
            if resolver is None:
                needs_interactive.append(tid)
            else:
                standard_ids.append((tid, resolver))

        # Process standard IDs with progress bar
        if standard_ids:
            for i, (tid, resolver) in enumerate(track(standard_ids, description="Adding standard samples..."), 1):
                logger.info(f"Processing sample {i}/{len(standard_ids)}: {tid.id}")
                console.print(f"[cyan]Processing {tid.id} ({i}/{len(standard_ids)})[/cyan]")

                try:
                    logger.info(f"Resolver found for {tid.id}, starting to add to database")

                    # Configure AI settings on resolver if enabled
                    if self.use_ai:
                        resolver._use_ai = True
                        resolver._ai_provider = self.ai_provider
                        if i == 1:  # Only show message once
                            console.print(f"[cyan]🤖 AI metadata extraction enabled (provider: {self.ai_provider})[/cyan]")

                    resolver.add(tid.id)
                    logger.info(f"Successfully added {tid.id} to database")
                    console.print(f"[green]✓ Successfully added {tid.id}[/green]")
                except Exception as e:
                    logger.error(f"Failed to add {tid.id}: {str(e)}")
                    console.print(f"[red]✗ Failed to add {tid.id}: {str(e)}[/red]")
                    raise

        # Process custom IDs interactively (without progress bar)
        if needs_interactive:
            console.print(f"\n[yellow]Found {len(needs_interactive)} sample(s) requiring custom data entry[/yellow]\n")

            for i, tid in enumerate(needs_interactive, 1):
                logger.warning(f"No resolver found for {tid.id}, trying custom data handler")
                console.print(f"[cyan]Custom data entry ({i}/{len(needs_interactive)})[/cyan]")

                try:
                    # Fallback to custom data handler (interactive)
                    from celline.DB.handler_custom import CustomDataHandler
                    custom_handler = CustomDataHandler()
                    custom_handler.add_interactive(tid.id)

                    logger.info(f"Successfully added custom data {tid.id}")
                    console.print(f"[green]✓ Successfully added custom data {tid.id}[/green]\n")
                except KeyboardInterrupt:
                    logger.warning(f"User cancelled custom data entry for {tid.id}")
                    console.print(f"\n[yellow]⚠ Skipping {tid.id} (cancelled by user)[/yellow]\n")
                    # Continue with next sample instead of raising
                    continue
                except Exception as e:
                    logger.error(f"Failed to add custom data {tid.id}: {str(e)}")
                    console.print(f"[red]✗ Failed to add custom data {tid.id}: {str(e)}[/red]")
                    raise
        # cnt = 0
        # for sample in tqdm.tqdm(self.add_target_id):
        #     if sample.id_name.startswith("GSE"):
        #         gse_schema = SRA_GSE().search(sample.id_name)
        #         if gse_schema.children is None:
        #             raise KeyError("Children must not be None")
        #         for gsm_id in tqdm.tqdm(gse_schema.children.split(","), leave=False):
        #             gsm_schema = SRA_GSM().search(gsm_id)
        #             given_title = self.add_target_id[cnt].title
        #             sample_name = (
        #                 gsm_schema.title
        #                 if (given_title is None or given_title == "")
        #                 else given_title
        #             )
        #             if sample_name is None:
        #                 raise KeyError("Sample name should not be none")
        #             self.__add_gsm_accession_proj(
        #                 sample_id=str(gsm_schema.key), sample_name=sample_name
        #             )
        #     elif sample.id_name.startswith("GSM"):
        #         gsm_schema = SRA_GSM().search(sample.id_name)
        #         given_title = self.add_target_id[cnt].title
        #         sample_name = (
        #             gsm_schema.title
        #             if (given_title is None or given_title == "")
        #             else given_title
        #         )
        #         if sample_name is None:
        #             raise KeyError("Sample name should not be none")
        #         self.__add_gsm_accession_proj(
        #             sample_id=str(gsm_schema.key), sample_name=sample_name
        #         )
        #     else:
        #         raise KeyError("Please set GSE or GSM")
        #     cnt += 1
        # samples = self.get_samples()
        # cnt = 1
        # for sample in samples:
        #     print(
        #         f"[bold magenta]Migrating {sample}[/bold magenta]: ({cnt}/{len(samples)})"
        #     )
        #     GEOHandler().sync()
        #     cnt += 1
        return project

    def add_cli_args(self, parser: argparse.ArgumentParser) -> None:
        """Add CLI arguments for the Add function."""
        parser.add_argument(
            'sample_ids',
            nargs='+',
            help='Sample IDs to add (e.g., GSE123456 GSM789012)'
        )
        parser.add_argument(
            '--title', '-t',
            help='Optional title for the samples'
        )
        parser.add_argument(
            '--from-file', '-f',
            help='Read sample IDs from a file (one per line or CSV/TSV format)'
        )
        parser.add_argument(
            '--ai',
            action='store_true',
            help='Enable AI metadata extraction from web pages (requires API key in .env)'
        )
        parser.add_argument(
            '--ai-provider',
            choices=['openai', 'claude', 'auto'],
            default='auto',
            help='AI provider to use for metadata extraction (default: auto)'
        )

    def cli(self, project: "Project", args: Optional[argparse.Namespace] = None) -> "Project":
        """CLI entry point for Add function."""
        if args is None:
            console.print("[red]Error: No arguments provided[/red]")
            return project

        sample_infos = []

        if args.from_file:
            # Read from file
            try:
                if args.from_file.endswith('.csv') or args.from_file.endswith('.tsv'):
                    # Read as DataFrame
                    separator = '\t' if args.from_file.endswith('.tsv') else ','
                    df = pl.read_csv(args.from_file, separator=separator)
                    
                    if not all(col in df.columns for col in ["id", "title"]):
                        console.print("[red]Error: CSV/TSV file must have 'id' and 'title' columns[/red]")
                        return project
                    
                    for row in df.iter_rows(named=True):
                        sample_infos.append(self.SampleInfo(
                            id=row["id"], 
                            title=row.get("title", "")
                        ))
                else:
                    # Read as plain text file (one ID per line)
                    with open(args.from_file, 'r') as f:
                        for line in f:
                            sample_id = line.strip()
                            if sample_id:
                                sample_infos.append(self.SampleInfo(
                                    id=sample_id, 
                                    title=args.title or ""
                                ))
            except Exception as e:
                console.print(f"[red]Error reading file {args.from_file}: {e}[/red]")
                return project
        else:
            # Use command line sample IDs
            for sample_id in args.sample_ids:
                sample_infos.append(self.SampleInfo(
                    id=sample_id,
                    title=args.title or ""
                ))

        if not sample_infos:
            console.print("[yellow]No sample IDs provided[/yellow]")
            return project

        console.print(f"[cyan]Adding {len(sample_infos)} sample(s)...[/cyan]")

        # Create Add instance with the sample infos and AI settings
        use_ai = getattr(args, 'ai', False)
        ai_provider = getattr(args, 'ai_provider', 'auto')

        add_instance = Add(sample_infos, use_ai=use_ai, ai_provider=ai_provider)
        return add_instance.call(project)

    def get_description(self) -> str:
        """Get description for CLI help."""
        return """Add accession IDs to your project.
        
This function adds sample accession IDs (like GSE, GSM, SRR) to your project
and fetches their metadata from public databases."""

    def get_usage_examples(self) -> list[str]:
        """Get usage examples for CLI help."""
        return [
            "celline run add GSE123456",
            "celline run add GSM789012 GSM789013 --title 'My samples'",
            "celline run add --from-file samples.txt",
            "celline run add --from-file samples.csv"
        ]
