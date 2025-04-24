import os
from typing import TYPE_CHECKING, NamedTuple, Optional, Union

import polars as pl
import toml
from rich.progress import track

from celline.config import Config
from celline.DB.dev.handler import HandleResolver
from celline.functions._base import CellineFunction
from celline.utils.serialization import NamedTupleAndPolarsStructure

if TYPE_CHECKING:
    from celline import Project


class Add(CellineFunction):
    """Add accession ID to your project."""

    class SampleInfo(NamedTuple):
        id: str
        title: Optional[str] = ""

    def __init__(self, sample_id: Union[list[SampleInfo], pl.DataFrame]) -> None:
        """#### Add accession ID to DB & your project.

        #### Note: Parallel calculations are not supported

        Args:
            sample_id (<List[Add.SampleInfo]> | <pl.DataFrame>): Accession ID to add.

        """
        self.add_target_id: list[Add.SampleInfo] = []
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
        elif isinstance(sample_id, list[Add.SampleInfo]):
            self.add_target_id: list[Add.SampleInfo] = sample_id
        else:
            raise ValueError("Add target id should be `list[Add.SampleInfo]` or `polars.DataFrame`")  # noqa: TRY004

    def get_samples(self) -> dict[str, str]:
        """Get sample information from samples.toml file.

        Returns:
            Dict[str, str]: Samples information.

        """
        sample_info_file = f"{Config.PROJ_ROOT}/samples.toml"
        samples: dict[str, str] = {}
        if os.path.isfile(sample_info_file):
            with open(sample_info_file, encoding="utf-8") as f:
                samples = toml.load(f)
        return samples

    def __add_gsm_accession_proj(self, sample_id: str, sample_name: str) -> None:
        """Add GSM accession ID and sample name to the samples.toml file.

        Args:
            sample_id (str): GSM accession ID.
            sample_name (str): Sample name.

        """
        sample_info_file = f"{Config.PROJ_ROOT}/samples.toml"
        samples: dict[str, str] = {}
        if os.path.isfile(sample_info_file):
            with open(sample_info_file, encoding="utf-8") as f:
                samples = toml.load(f)
        if sample_id in samples:
            return
        samples[sample_id] = sample_name
        with open(sample_info_file, mode="w", encoding="utf-8") as f:
            toml.dump(samples, f)

    def call(self, project: "Project") -> "Project":
        """Call the function to add accession IDs to the project.

        Args:
            project (<Project>): The project to add the accession IDs to.

        Returns:
            <Project>: The project with the added accession IDs.

        """
        for tid in track(self.add_target_id, description="Adding..."):
            resolver = HandleResolver.resolve(tid.id)
            if resolver is not None:
                resolver.add(tid.id)
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
