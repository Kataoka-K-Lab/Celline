from typing import Type, NamedTuple, Final, Optional, List, Dict
from enum import Enum
from celline.DB.dev.model import BaseModel, Primary, RunSchema
from xml.etree import ElementTree as ET
from xml.etree.ElementTree import ElementTree, Element
import requests
import polars as pl
from dataclasses import dataclass
from rich import print


@dataclass
class SRA_SRR_Schema(RunSchema):
    pass


class SRA_SRR(BaseModel[SRA_SRR_Schema]):
    BASE_XML_PATH: Final[
        str
    ] = "https://trace.ncbi.nlm.nih.gov/Traces/sra-db-be/run_new?acc="

    def set_class_name(self) -> str:
        """Set class name"""
        return self.__class__.__name__

    def def_schema(self) -> type[SRA_SRR_Schema]:
        return SRA_SRR_Schema

    @staticmethod
    def decide_strategy(file_infos: List[Dict[str, str]]) -> str:
        """Determine analysis strategy"""
        suggested_strategy: Optional[str] = None
        for file_info in file_infos:
            if ".bam" in file_info.get("filename", ""):
                return "bam"
            if (".fastq" in file_info.get("filename", "")) or (
                ".fq" in file_info.get("filename", "")
            ):
                suggested_strategy = "fastq"
        if suggested_strategy is None:
            raise ValueError("Could not resolve the strategy from given file_infos.")
        return suggested_strategy

    def search(self, acceptable_id: str, force_search=False) -> SRA_SRR_Schema:
        """Search for SRR IDs"""
        cache = self.get_cache(acceptable_id, force_search)
        if cache is not None:
            return cache
        url = f"{SRA_SRR.BASE_XML_PATH}{acceptable_id}"
        tree = ET.fromstring(requests.get(url, timeout=100).content.decode())
        member = tree.find("RUN/Pool/Member")
        if member is None:
            tid: str = str(acceptable_id)
            print(f"[red]ERROR[/red]Could not find member. Is SRR ID correct?: {tid}")
            raise KeyError()
        files_elem = tree.find("RUN/SRAFiles")
        if files_elem is None:
            raise KeyError("Could not find files. Is SRR ID correct?")
        files = [
            file
            for file in [d.attrib for d in list(files_elem)]
            if file.get("supertype") == "Original"
        ]
        if not files:
            raise KeyError("Could not find original files.")
        strategy = self.decide_strategy(files)
        newdata = self.add_schema(
            SRA_SRR_Schema(
                key=acceptable_id,
                strategy=strategy,
                parent=member.attrib.get("sample_name"),
                children=None,
                raw_link=",".join([file["url"] for file in files if "url" in file]),
                title=None,
            )
        )

        return newdata
