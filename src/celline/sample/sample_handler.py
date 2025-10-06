from dataclasses import dataclass
import os
from typing import Dict, Final

import rich

from celline.DB.dev.handler import HandleResolver
from celline.DB.dev.model import SampleSchema
from celline.DB.dev.excel_handler import ExcelMetadataHandler
from celline.config import Config
from celline.utils.path import Path


@dataclass
class SampleInfo:
    schema: SampleSchema
    path: Path


class SampleResolver:
    __samples: Dict[str, SampleInfo] = {}
    __called = False

    @classmethod
    @property
    def samples(cls) -> Dict[str, SampleInfo]:
        if Config.current in Config.runnings:
            EXCEL_PATH: Final[str] = f"{Config.runnings[Config.current].PROJ_ROOT}/metadata.xlsx"
        else:
            raise RuntimeError("Config not initialized")

        if not cls.__called and os.path.isfile(EXCEL_PATH):
            excel_handler = ExcelMetadataHandler(EXCEL_PATH)
            sample_keys = excel_handler.get_all_keys("samples")

            for sample_id in sample_keys:
                __resolver = HandleResolver.resolve(sample_id)
                if __resolver is None:
                    rich.print(
                        f"[bold red]Unresolved error[/] Could not resolve {sample_id}"
                    )
                else:
                    __sample: SampleSchema = __resolver.sample.search(sample_id)
                    if __sample.parent is not None:
                        cls.__samples[sample_id] = SampleInfo(
                            schema=__sample,
                            path=Path(str(__sample.parent), str(__sample.key)),
                        )
            cls.__called = True
        return cls.__samples

    @classmethod
    def refresh(cls):
        cls.__called = False
