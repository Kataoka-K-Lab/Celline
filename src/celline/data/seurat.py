import os
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
import polars as pl
import pyper as pr
import scanpy as sc

from celline.config import Config, Setting
from celline.data.ggplot import ggplot
from celline.utils.r_wrap import as_r_bool, as_r_NULL, as_r_nullablestr


class Seurat:
    r: pr.R

    def __init__(self, seurat_path: str, via_seurat_disk: bool) -> None:
        if not os.path.isfile(seurat_path):
            raise FileNotFoundError(
                f"Could not find seurat file: {seurat_path}. Please try consider identifier (file name), or using seurat_from_rawpath"
            )
        print(f"Using R: {Setting.r_path}")
        self.r = pr.R(RCMD=Setting.r_path, use_pandas=True)
        self.r.assign("h5seurat_path", f"{seurat_path}")
        self.r("pacman::p_load(Seurat, SeuratDisk, tidyverse)")
        print("Loading seurat")
        if via_seurat_disk:
            result = self.r("seurat <- SeuratDisk::LoadH5Seurat(h5seurat_path)")
        else:
            result = self.r("seurat <- readRDS(h5seurat_path)")
        print(
            f"""
Done.
---- Trace --------------
{result}
"""
        )

    @property
    def metadata(self) -> pl.DataFrame:
        _metadata = pd.DataFrame(
            self.r.get('seurat@meta.data %>% tibble::rownames_to_column("cell")')
        )
        for col in _metadata.columns:
            if _metadata[col].apply(lambda x: isinstance(x, bytes)).any():
                _metadata[col] = _metadata[col].str.decode("utf-8")
        return pl.from_pandas(_metadata.convert_dtypes())

    def DimPlot(
        self,
        group_by: Optional[str] = "seurat_clusters",
        split_by: Optional[str] = None,
        pt_size: Optional[int] = None,
    ):
        if group_by is None:
            group_by = "NULL"
        if split_by is None:
            split_by = "NULL"

        log = self.r(
            f'plt <- DimPlot(seurat, group.by = "{group_by}", split.by = {as_r_nullablestr(split_by)}, pt.size = {as_r_NULL(pt_size)})'
        )
        print(log)
        return ggplot(self.r)

    def DotPlot(
        self,
        features: List[str],
        assay: Optional[str] = None,
        cols: Optional[List[str]] = None,
        col_min: float = -2.5,
        col_max: float = 2.5,
        dot_min=0,
        dot_scale=6,
        idents: Optional[str] = None,
        group_by: Optional[str] = None,
        split_by: Optional[str] = None,
        cluster_idents=False,
        scale=True,
        scale_by="radius",
        scale_min: Optional[float] = None,
        scale_max: Optional[float] = None,
    ):
        if features is None:
            features = []
        if cols is None:
            cols = ["lightgrey", "blue"]
        self.r.assign("features", features)
        self.r.assign("assay", assay)
        self.r.assign("cols", cols)
        self.r.assign("col.min", col_min)
        self.r.assign("col.max", col_max)
        self.r.assign("dot.min", dot_min)
        self.r.assign("dot.scale", dot_scale)
        self.r.assign("group.by", group_by)
        self.r.assign("idents", idents)
        self.r.assign("split.by", split_by)
        self.r.assign("cluster.idents", cluster_idents)
        self.r.assign("scale", scale)
        self.r.assign("scale.by", scale_by)
        self.r.assign("scale.min", scale_min)
        self.r.assign("scale.max", scale_max)
        cmd = """
plt <-
    seurat %>%
    Seurat::DotPlot(
        assay = assay,
        features,
        cols = cols),
        col.min = col.min,
        col.max = col.max,
        dot.min = dot.min,
        dot.scale = dot.scale,
        idents = idents,
        group.by = group.by,
        split.by = split.by,
        cluster.idents = cluster.idents,
        scale = scale,
        scale.by = scale.by,
        scale.min = scale.min,
        scale.max = scale.max
    )
"""
        self.r(cmd)
        return ggplot(self.r)

    def VlnPlot(
        self,
        features: List[str],
        cols: Optional[List[str]] = None,
        pt_size: Optional[float] = None,
        alpha: float = 1,
        idents: Optional[List[str]] = None,
        sort=False,
        assay: Optional[str] = None,
        group_by: Optional[str] = None,
        split_by: Optional[str] = None,
        adjust: float = 1,
        y_max: Optional[float] = None,
        same_y_lims=False,
        log=False,
        ncol: Optional[int] = None,
        layer="data",
        split_plot=False,
        stack=False,
        combine=True,
        fill_by="feature",
        flip=False,
        add_noise=True,
        raster: Optional[bool] = None,
    ):
        self.r.assign("features", features)
        self.r.assign("cols", cols)
        self.r.assign("pt.size", pt_size)
        self.r.assign("alpha", alpha)
        self.r.assign("idents", idents)
        self.r.assign("sort", sort)
        self.r.assign("assay", assay)
        self.r.assign("group.by", group_by)
        self.r.assign("split.by", split_by)
        self.r.assign("adjust", adjust)
        self.r.assign("y.max", y_max)
        self.r.assign("same.y.lims", same_y_lims)
        self.r.assign("log", log)
        self.r.assign("ncol", ncol)
        self.r.assign("layer", layer)
        self.r.assign("split.plot", split_plot)
        self.r.assign("stack", stack)
        self.r.assign("combine", combine)
        self.r.assign("fill.by", fill_by)
        self.r.assign("flip", flip)
        self.r.assign("add.noise", add_noise)
        self.r.assign("raster", raster)
        self.r(
            """
plt <-
    seurat %>%
    Seurat::VlnPlot(
        features,
        cols = cols,
        pt.size = pt.size,
        alpha = alpha,
        idents = idents,
        sort = sort,
        assay = assay,
        group.by = group.by,
        split.by = split.by,
        adjust = adjust,
        y.max = y.max,
        same.y.lims = same.y.lims,
        log = log,
        ncol = ncol,
        layer = layer,
        split.plot = split.plot,
        stack = stack,
        combine = combine,
        fill.by = fill.by,
        flip = flip,
        add.noise = add.noise,
        raster = raster
    )
"""
        )
        return ggplot(self.r)

    def save(self, path: str):
        # self.r.assign("savepath", path)
        cmd = f"""
seurat %>%
    saveRDS({path})
"""
        self.r(cmd)
        return

    def save_h5ad(self, path: str):
        # self.r.assign("savepath", path)
        os.makedirs(f"{Config.PROJ_ROOT}/cache", exist_ok=True)
        cmd = f"""
pacman::p_load(Matrix, tidyverse)
seurat %>%
    LayerData() %>%
    t() %>%
    writeMM("{Config.PROJ_ROOT}/cache/matrix.mtx")
seurat@meta.data %>%
    tibble::rownames_to_column("barcodes") %>%
    write_csv(paste0("{Config.PROJ_ROOT}/cache/barcodes.csv"))
rownames(seurat) %>%
    as_tibble() %>%
    dplyr::rename(features = "value") %>%
    write_csv(paste0("{Config.PROJ_ROOT}/cache/features.csv"))
"""
        self.r(cmd)
        adata = sc.read_mtx(Path(f"{Config.PROJ_ROOT}/cache/matrix.mtx"), dtype="int32")
        adata.obs = pd.read_csv(f"{Config.PROJ_ROOT}/cache/barcodes.csv")
        adata.obs.set_index("barcodes", inplace=True)
        adata.var = pd.read_csv(f"{Config.PROJ_ROOT}/cache/features.csv")
        adata.write_h5ad(Path(path))
        os.remove(f"{Config.PROJ_ROOT}/cache/matrix.mtx")
        return
