import os
from typing import TYPE_CHECKING, Final, List, Optional

from rich.progress import track
import toml

from celline.DB.dev.handler import HandleResolver
from celline.config import Config
from celline.functions._base import CellineFunction

if TYPE_CHECKING:
    from celline import Project


class SyncDB(CellineFunction):
    def __init__(self, force_update_target: Optional[List[str]] = None) -> None:
        self.update_target = force_update_target

    def call(self, project: "Project"):
        fpath: Final[str] = f"{Config.PROJ_ROOT}/samples.toml"
        if not os.path.isfile(fpath):
            raise FileNotFoundError("sample.toml file was not found.")
        with open(fpath, encoding="utf-8", mode="r") as f:
            all_samples = list(toml.load(f).keys())
        for sample in track(all_samples, description="Fetching..."):
            force_search = False
            if self.update_target is not None and sample in self.update_target:
                force_search = True
            handler = HandleResolver.resolve(sample)
            if handler is None:
                raise NotImplementedError(f"Could not resolve target handler: {sample}")
            handler.add(sample, force_search)
        return self
