import os
from typing import TYPE_CHECKING, Dict, Final, List, NamedTuple, Optional, Union

import polars as pl
import toml
import tqdm

from celline.DB.handler import GEOHandler
from celline.DB.model import SRA_GSE, SRA_GSM, SRA_SRR
from celline.DB.model.transcriptome import Transcriptome
from celline.config import Config
from celline.functions._base import CellineFunction
from celline.utils.serialization import NamedTupleAndPolarsStructure

if TYPE_CHECKING:
    from celline import Project


class SetTranscriptome(CellineFunction):
    def __init__(self, species: str, built_path: str, force_update=True) -> None:
        self.species: Final[str] = species
        self.built_path: Final[str] = built_path
        self.force_update: Final[bool] = force_update

    def call(self, project: "Project"):
        Transcriptome().add_path(
            self.species, self.built_path, force_update=self.force_update
        )
        return self
