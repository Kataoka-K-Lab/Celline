import os
import subprocess
from typing import TYPE_CHECKING, Callable, Dict, Final, List, NamedTuple, Optional

import rich
from rich.progress import track

from celline.config import Config, Setting
from celline.functions._base import CellineFunction
from celline.middleware import ThreadObservable
from celline.sample import SampleResolver
from celline.server import ServerSystem
from celline.template import TemplateManager

if TYPE_CHECKING:
    from celline import Project


class Reduce(CellineFunction):
    FILES_TO_KEEP: Final = [
        "outs/filtered_feature_bc_matrix.h5",
        "outs/molecule_info.h5",
        "outs/web_summary.html",
        "_log",
        "outs/filtered_feature_bc_matrix/matrix.mtx.gz",
        "outs/filtered_feature_bc_matrix/features.tsv.gz",
        "outs/filtered_feature_bc_matrix/barcodes.tsv.gz",
    ]

    def call(self, project: "Project"):
        for sample in track(
            SampleResolver.samples.values(),
            description="Processing reducing files...",
        ):
            target_path = sample.path.resources_sample_counted
            if os.path.exists(target_path):
                for foldername, subfolders, filenames in os.walk(
                    target_path, topdown=False, followlinks=True
                ):
                    for filename in filenames:
                        rel_path = os.path.relpath(
                            os.path.join(foldername, filename), target_path
                        )
                        if rel_path not in Reduce.FILES_TO_KEEP:
                            os.remove(os.path.join(foldername, filename))

                    # 2. 空のディレクトリやシンボリックリンクを削除
                    for subfolder in subfolders:
                        full_subfolder_path = os.path.join(foldername, subfolder)
                        if os.path.islink(full_subfolder_path):
                            os.remove(full_subfolder_path)
                        elif os.path.isdir(full_subfolder_path) and not os.listdir(
                            full_subfolder_path
                        ):
                            os.rmdir(full_subfolder_path)
        return project
