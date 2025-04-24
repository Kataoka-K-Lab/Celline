import pandas as pd
from typing import List
from celline.config import Config
import os
from glob import glob


class DirectoryManager:
    __loaded: bool = False
    __runs: List[str] = []

    @staticmethod
    def runs() -> List[str]:
        filepath = f"{Config.PROJ_ROOT}/runs.tsv"
        if not DirectoryManager.__loaded:
            if os.path.exists(filepath):
                DirectoryManager.__runs = pd.read_csv(
                    filepath, sep="\t", index_col=0).index.tolist()
            else:
                DirectoryManager.__runs = []
        return DirectoryManager.__runs

    @staticmethod
    def __is_systematically_generated(gsm_id: str):
        if os.path.isdir(f"{Config.PROJ_ROOT}/resources/{gsm_id}"):
            return True
        return False

    @staticmethod
    def is_dumped(gsm_id: str):
        """Returns whether the target gsm_id data has already been downloaded."""
        if not DirectoryManager.__is_systematically_generated(gsm_id):
            return False
        target_extentions = [".bam", ".fastq"]
        dumped_files = glob(
            f"{Config.PROJ_ROOT}/resources/{gsm_id}/raw/**/*.*", recursive=True)
        for f in dumped_files:
            for ext in target_extentions:
                if ext in f.split("/")[-1]:
                    return True
        return False

    @staticmethod
    def is_counted(gsm_id: str):
        """Returns whether the target gsm_id data has already been counted."""
        if not DirectoryManager.__is_systematically_generated(gsm_id):
            return False
        if os.path.isfile(f"{Config.PROJ_ROOT}/resources/{gsm_id}/outs/filtered_feature_bc_matrix.h5"):
            return True
        return False
