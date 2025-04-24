from __future__ import annotations

import os
import subprocess
from collections.abc import Callable

# from celline.database import NCBI, GSE, GSM
from typing import Final

import pyper as pr
import toml

from celline.config import Config, Setting
from celline.data import Seurat
from celline.functions._base import CellineFunction
from celline.middleware import ThreadObservable
from celline.server import ServerSystem
from celline.utils.path import Path


class Project:
    """Celline project"""

    EXEC_PATH: Final[str]
    PROJ_PATH: Final[str]

    def __init__(self, project_dir: str, proj_name: str = "", r_path: str = "") -> None:
        """#### Load or create new celline project"""

        def get_r_path() -> str:
            with subprocess.Popen(
                "which R",
                stdout=subprocess.PIPE,
                shell=True,
            ) as proc:
                result = proc.communicate()
            return result[0].decode("utf-8").replace("\n", "")

        def get_default_proj_name() -> str:
            return os.path.basename(project_dir)

        self.EXEC_PATH = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
        self.PROJ_PATH = project_dir
        Config.EXEC_ROOT = self.EXEC_PATH
        Config.PROJ_ROOT = self.PROJ_PATH
        if not os.path.isfile(f"{self.PROJ_PATH}/setting.toml"):
            Setting.name = get_default_proj_name() if proj_name == "" else proj_name
            Setting.r_path = get_r_path() if r_path == "" else r_path
            Setting.version = "0.01"
            Setting.wait_time = 4
            Setting.flush()
        with open(f"{self.PROJ_PATH}/setting.toml", encoding="utf-8") as f:
            setting = toml.load(f)
            Setting.name = setting["project"]["name"]
            Setting.r_path = setting["R"]["r_path"]
            Setting.version = setting["project"]["version"]
            Setting.wait_time = setting["fetch"]["wait_time"]

    @property
    def nthread(self) -> int:
        return ThreadObservable.njobs

    def call(self, func: CellineFunction, wait_for_complete=True):
        """#### Call celline function"""
        func.call(self)
        ThreadObservable.wait_for_complete = wait_for_complete
        if wait_for_complete:
            ThreadObservable.watch()
        return self

    def call_if_else(
        self,
        condition: Callable[[Project], bool],
        true: CellineFunction,
        false: CellineFunction,
    ):
        """Call function if"""
        if condition(self):
            true.call(self)
        else:
            false.call(self)
        return self

    def parallelize(self, njobs: int):
        """#### Starts parallel computation\n
        @ njobs<int>: Number of jobs
        """
        ThreadObservable.set_jobs(njobs)
        return self

    def singularize(self):
        """#### End pararel computation"""
        ThreadObservable.set_jobs(1)
        return self

    def start_logging(self):
        return self

    def end_logging(self):
        return self

    def if_else(
        self,
        condition: Callable[[Project], bool],
        true: Callable[[Project], None],
        false: Callable[[Project], None],
    ):
        if condition(self):
            true(self)
        else:
            false(self)
        return self

    def usePBS(self, cluster_server_name: str):
        """#### Use PBS system."""
        print(f"--: Use PBS system: {cluster_server_name}")
        ServerSystem.usePBS(cluster_server_name)
        return self

    def useMultiThreading(self):
        """#### Use mutithreading system."""
        print("--: Use default multi threading")
        ServerSystem.useMultiThreading()
        return self

    def seurat(
        self,
        project_id: str,
        sample_id: str,
        identifier: str = "seurat.seurat",
        via_seurat_disk: bool = False,
    ):
        path = Path(project_id, sample_id)
        seurat_path = f"{path.data_sample}/{identifier}"
        bcmatrix_path = f"{path.resources_sample_counted}/outs/filtered_feature_bc_matrix.h5"
        if not os.path.isfile(seurat_path) and os.path.isfile(bcmatrix_path):
            return self.create_seurat(project_id, sample_id)
        return self.seurat_from_rawpath(seurat_path, via_seurat_disk)

    def seurat_from_rawpath(self, raw_path: str, via_seurat_disk: bool = True):
        return Seurat(raw_path, via_seurat_disk)

    def create_seurat(self, project_id: str, sample_id: str):
        identifier: str = "seurat.seurat"
        path = Path(project_id, sample_id)
        seurat_path = f"{path.data_sample}/{identifier}"
        r: pr.R = pr.R(RCMD=Setting.r_path, use_pandas=True)
        r.assign(
            "h5_path",
            f"{path.resources_sample_counted}/outs/filtered_feature_bc_matrix.h5",
        )
        r.assign("h5seurat_path", f"{seurat_path}")
        r.assign("proj", Setting.name)
        print("Loading raw matrix")
        result = r(
            """
pacman::p_load(Seurat, SeuratDisk, tidyverse)
raw <-
    Read10X_h5(h5_path) %>%
    CreateSeuratObject(proj) %>%
    NormalizeData() %>%
    FindVariableFeatures() %>%
    ScaleData()
raw %>%
    RunPCA(features = VariableFeatures(object = raw)) %>%
    FindNeighbors(dims = 1:20) %>%
    FindClusters(dims = 1:20) %>%
    RunUMAP(dims = 1:20) %>%
    saveRDS(h5seurat_path)
""",
        )
        print(
            f"""
Done.
---- Trace --------------
{result}
""",
        )
        return Seurat(seurat_path, False)
