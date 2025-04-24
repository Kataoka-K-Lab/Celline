# from __future__ import annotations
# import os
# import glob

# from typing import Dict, NamedTuple, Final, List

# import toml

# from celline.config import Config
# from celline.utils.path import Path
# from celline.utils.serialization import NamedTupleAndPolarsStructure
# from celline.DB.model import SRA_GSM


# class Resources:
#     class SampleInfo:
#         """#### Represents sample information"""

#         def __init__(self, sample_id: str, sample_name: str) -> None:
#             self.sample_id = sample_id
#             project_id = SRA_GSM().search(sample_id).parent
#             if project_id is None:
#                 raise KeyError(f"Parent ID of {project_id} is null")
#             self.project_id = project_id
#             self._name = sample_name
#             self.path = Path(project_id, sample_id)

#         sample_id: Final[str]
#         """[Immutable] Sample ID like GSM..."""
#         project_id: Final[str]
#         """[Immutable] Project ID like GSE"""
#         _name: str
#         """Sample name"""
#         path: Final[Path]
#         """[Immutable] Path object which enable search path"""

#         @property
#         def downloaded(self):
#             """Already downloaded?"""
#             # resources_sample_raw_fastqs以下の全てのディレクトリを取得
#             all_dirs = [
#                 f.path
#                 for f in os.scandir(self.path.resources_sample_raw_fastqs)
#                 if f.is_dir()
#             ]
#             # 各ディレクトリに<任意の文字列>_S1_L001_<R1, R2, I1, I2のいずれか>_001.fastq.gzという名前のファイルが最低でも2つ含まれているか
#             for directory in all_dirs:
#                 fastq_files = []
#                 for suffix in ["R1", "R2", "I1", "I2"]:  # R1, R2, I1, I2の各パターンについて
#                     fastq_files += glob.glob(
#                         f"{directory}/*_S1_L001_{suffix}_001.fastq.gz"
#                     )  # 各パターンにマッチするファイルを取得

#                 if len(fastq_files) >= 2:
#                     return True  # 該当のファイルが2つ以上含まれるディレクトリが見つかった

#             return False

#         @property
#         def counted(self):
#             """Already counted?"""
#             counted_file = f"{self.path.resources_sample_counted}/outs/filtered_feature_bc_matrix.h5"
#             return os.path.isfile(counted_file)

#         @property
#         def preprocessed(self) -> bool:
#             return os.path.isfile(
#                 f"{self.path.data_sample}/doublet_info.tsv"
#             ) and os.path.isfile(f"{self.path.data_sample}/qc_matrix.tsv")

#         @property
#         def celltype_predicted(self):
#             return os.path.isfile(f"{self.path.data_sample}/celltype_predicted.tsv")

#         @property
#         def name(self):
#             return self._name

#         @name.setter
#         def name(self, new_name: str):
#             self._name = new_name
#             all_samples = Resources.all_samples()
#             for i, sample in enumerate(all_samples):
#                 if sample.sample_id == self.sample_id:
#                     all_samples[i].name = new_name
#             Resources.save_samples(all_samples)

#     @classmethod
#     def all_samples(cls) -> List[SampleInfo]:
#         sample_info_file = f"{Config.PROJ_ROOT}/samples.toml"
#         samples: Dict[str, str] = {}
#         if os.path.isfile(sample_info_file):
#             with open(sample_info_file, mode="r", encoding="utf-8") as f:
#                 samples = toml.load(f)
#             return [Resources.SampleInfo(sample, samples[sample]) for sample in samples]
#         return []

#     @classmethod
#     def save_samples(cls, samples: List[SampleInfo]) -> None:
#         sample_info_file = f"{Config.PROJ_ROOT}/samples.toml"
#         samples_dict = {sample.sample_id: sample.name for sample in samples}
#         with open(sample_info_file, mode="w", encoding="utf-8") as f:
#             toml.dump(samples_dict, f)
