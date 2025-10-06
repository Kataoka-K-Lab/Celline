import os
from typing import TYPE_CHECKING, Final, List, Optional

from rich.progress import track

from celline.DB.dev.handler import HandleResolver
from celline.DB.dev.excel_handler import ExcelMetadataHandler
from celline.config import Config
from celline.functions._base import CellineFunction

if TYPE_CHECKING:
    from celline import Project


class SyncDB(CellineFunction):
    def __init__(self, force_update_target: Optional[List[str]] = None) -> None:
        self.update_target = force_update_target

    def call(self, project: "Project"):
        if Config.current in Config.runnings:
            excel_path = f"{Config.runnings[Config.current].PROJ_ROOT}/metadata.xlsx"
        else:
            raise RuntimeError("Config not initialized")

        if not os.path.isfile(excel_path):
            raise FileNotFoundError("metadata.xlsx file was not found.")

        excel_handler = ExcelMetadataHandler(excel_path)
        all_samples = list(excel_handler.get_all_keys("samples"))
        for sample in track(all_samples, description="Fetching..."):
            force_search = False
            if self.update_target is not None and sample in self.update_target:
                force_search = True
            handler = HandleResolver.resolve(sample)
            if handler is None:
                raise NotImplementedError(f"Could not resolve target handler: {sample}")
            handler.add(sample, force_search)
        return self
