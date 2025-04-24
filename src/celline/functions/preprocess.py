import os
from typing import TYPE_CHECKING, Dict, Final, Optional

import polars as pl
import scanpy as sc
import scrublet as scr
import toml

from celline.config import Config
from celline.DB.dev.handler import HandleResolver
from celline.DB.dev.model import SampleSchema
from celline.functions._base import CellineFunction
from celline.utils.path import Path

if TYPE_CHECKING:
    pass

class Preprocess(CellineFunction):
    TARGET_CELLTYPE: Final[Optional[list[str]]]
    def __init__(self, target_celltype: Optional[list[str]] = None):
        """
        Initialize the Preprocess class.

        This constructor sets up the Preprocess object with an optional list of target cell types.

        Parameters:
        -----------
        target_celltype : Optional[list[str]], default=None
            A list of target cell types to be considered in the preprocessing.
            If None, all cell types will be considered.

        Returns:
        --------
        None
        """
        self.TARGET_CELLTYPE = target_celltype

    def call(self, project):
        """
        Perform preprocessing on the given project's samples.

        This function reads sample information from a TOML file, processes each sample,
        performs quality control, and generates cell information for further analysis.

        Parameters:
        -----------
        project : object
            The project object containing information about the samples to be processed.

        Returns:
        --------
        project : object
            The input project object, potentially modified during processing.

        Raises:
        -------
        ReferenceError
            If a sample ID cannot be resolved.
        KeyError
            If a sample's parent information is missing.
        """
        sample_info_file = f"{Config.PROJ_ROOT}/samples.toml"
        if not os.path.isfile(sample_info_file):
            print("sample.toml could not be found. Skipping.")
            return project
        with open(sample_info_file, mode="r", encoding="utf-8") as f:
            samples: Dict[str, str] = toml.load(f)
            for sample_id in samples:
                resolver = HandleResolver.resolve(sample_id)
                if resolver is None:
                    raise ReferenceError(
                        f"Could not resolve target sample id: {sample_id}"
                    )
                sample_schema: SampleSchema = resolver.sample.search(sample_id)
                if sample_schema.parent is None:
                    raise KeyError("Could not find parent")
                path = Path(sample_schema.parent, sample_id)
                path.prepare()
                if path.is_counted and path.is_predicted_celltype:
                    adata = sc.read_10x_h5(path.resources_sample_counted)
                    obs = (
                        pl.DataFrame(adata.obs.reset_index())
                        .rename({"index": "barcode"})
                        .with_columns(pl.lit(sample_schema.parent).alias("project"))
                        .with_columns(pl.lit(sample_id).alias("sample"))
                        .with_columns((pl.concat_str(pl.col("sample"), pl.cum_count("sample"), separator="_")).alias("cell"))
                        .join(
                            pl.read_csv(
                            path.data_sample_predicted_celltype,
                            separator="\t",
                            ).rename({"scpred_prediction": "cell_type"}),
                            on="cell",
                        )
                        .with_columns(
                            (pl.col("cell_type").is_in(pl.select(pl.col("cell_type")).unique(pl.col("cell_type")).get_column("cell_type").to_list() if self.TARGET_CELLTYPE is None else self.TARGET_CELLTYPE)).alias("include")
                        )
                    )
                    scrub = scr.Scrublet(adata.X)
                    doublet_scores, predicted_doublets = scrub.scrub_doublets(verbose=False)
                    adata.obs["doublet_score"] = doublet_scores
                    adata.obs["predicted_doublets"] = predicted_doublets
                    mt_prefix = "mt-"
                    adata.var["mt"] = adata.var_names.str.startswith(mt_prefix)
                    sc.pp.calculate_qc_metrics(
                        adata,
                        qc_vars=["mt"],
                        percent_top=None,
                        log1p=False,
                        inplace=True,
                    )
                    (
                        obs
                        .with_columns(((pl.col("n_genes_by_counts") >= 200) & pl.col("include")).alias("include"))
                        .with_columns(((pl.col("n_genes_by_counts") <= 5000) & pl.col("include")).alias("include"))
                        .with_columns(((pl.col("pct_counts_mt") <= 5) & pl.col("include")).alias("include"))
                        .with_columns(((pl.col("predicted_doublets") is False) & pl.col("include")).alias("include"))
                        .write_csv(f"{path.data_sample}/cell_info.tsv", separator="\t")
                    )