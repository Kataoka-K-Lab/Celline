from dataclasses import dataclass
import os
from typing import Dict, Final

import rich
import toml

from celline.DB.dev.handler import HandleResolver
from celline.DB.dev.model import SampleSchema
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
        SAMPLE_PATH: Final[str] = f"{Config.PROJ_ROOT}/samples.toml"
        if not cls.__called and os.path.isfile(SAMPLE_PATH):
            with open(SAMPLE_PATH, mode="r", encoding="utf-8") as f:
                __samples = toml.load(f)
            for sample_id in __samples:
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
