# from celline.functions._base import CellineFunction
# from celline.utils.thread import split_jobs
# from celline.plugins.collections.generic import DictionaryC, ListC
# from celline.database import NCBI
# from celline.data.ncbi import GSE, GSM, SRR
# from celline.config import Config
# from celline.data.genome import Genome
# from celline.job.jobsystem import JobSystem
# from celline.job.PBS import PBS
# from typing import Optional, List, Dict
# import subprocess
# import os
# import datetime

# # from celline.data.manager import DataManager
# # from celline.data.SRAData import SRAData
# # from celline.ncbi.SRAID import SRAID
# # import asyncio
# # from celline.utils.directory import Directory, DirectoryType


# class Count(CellineFunction):
#     """
#     Count data
#     """

#     options: DictionaryC[str, Optional[str]]

#     def register(self) -> str:
#         return "count"

#     @property
#     def nthread(self) -> int:
#         nthread = self.options["nthread"]
#         if nthread is None:
#             return 1
#         elif nthread.isdecimal():
#             print("[ERROR] nthread argument should be int number.")
#             quit()
#         return int(nthread)

#     @property
#     def cluster_num(self):
#         cluster = self.options["parallel"]
#         if cluster is None:
#             return 1
#         elif not cluster.isdecimal():
#             print("[ERROR] 'parallel' argument requires int number.")
#             quit()
#         return int(cluster)

#     def build_job(self, gsm: GSM, each_nthread: int):
#         root_dir = f"{Config.PROJ_ROOT}/resources/{gsm.id}"
#         raw_dir = f"{root_dir}/raw"
#         dist_dir = f"{root_dir}/counted"
#         if len(gsm.child_srr_ids) == 0:
#             print(f"[ERROR] Could not find child SRR IDs @ {gsm.id}")
#         srr = SRR.search(gsm.child_srr_ids[0])
#         if srr.file_type == SRR.ScRun.FileType.Bam:
#             return f"""
# cd {raw_dir}
# echo "Converting bam to fastq files."
# rm -rf fastqs
# cellranger bamtofastq --nthreads={each_nthread} {gsm.id}.bam fastqs
# counted={dist_dir}
# raw_path={raw_dir}/fastqs
# cd {Config.EXEC_ROOT}
# dirpath=$(poetry run python {Config.EXEC_ROOT}/bin/runtime/get_subdir.py $raw_path)
# cd $counted
# cellranger count --id={gsm.id} --fastqs=$dirpath --sample=bamtofastq --transcriptome={Genome.get(gsm.species)} --no-bam --localcores {each_nthread}
# """
#         elif srr.file_type == SRR.ScRun.FileType.Fastq:
#             return f"""
# counted="{dist_dir}"
# raw_path="{raw_dir}/fastqs"
# cd $counted
# cellranger count --id={gsm.id} --fastqs=$raw_path --sample={gsm.id} --transcriptome={Genome.get(gsm.species)} --no-bam --localcores {each_nthread}
# """
#         else:
#             print(f"[ERROR] Unknown file type: {srr.file_type.name}. Skip.")

#     def on_call(self, args: Dict[str, DictionaryC[str, Optional[str]]]):
#         options = args["options"]
#         self.options = options
#         __nthread = options["nthread"]
#         if __nthread is None:
#             nthread = 1
#         else:
#             try:
#                 nthread = int(__nthread, 10)
#             except ValueError:
#                 print("[ERROR] nthread parameter should express as <int> format")
#                 quit()
#         del __nthread
#         __cluster = options["cluster"]
#         if __cluster is None:
#             cluster = 1
#         else:
#             try:
#                 cluster = int(__cluster, 10)
#             except ValueError:
#                 print("[ERROR] nthread parameter should express as <int> format")
#                 quit()
#         del __cluster
#         current = NCBI.get_gsms()
#         path = f"{Config.PROJ_ROOT}/resources"
#         existing_dirs = [
#             f for f in os.listdir(path) if os.path.isdir(os.path.join(path, f))
#         ]
#         target_gsms: List[str] = []
#         """Count target gsms"""
#         for d in existing_dirs:
#             if (not os.path.isdir(f"{d}/counted")) and (d in current.keys()):
#                 target_gsms.append(d)
#         if cluster > len(target_gsms):
#             print(f"[WARNING] Cluster number will be {len(target_gsms)}")
#             cluster = len(target_gsms)
#         __base_job_num = 0
#         cluster_num = 0
#         job_system: JobSystem = JobSystem.default_bash
#         server_name: str = ""
#         job_cluster = self.options["job"]
#         if job_cluster is not None:
#             if "PBS" in job_cluster:
#                 if "@" not in job_cluster:
#                     print("[ERROR] PBS job shold called as PBS@<cluster_server_name>")
#                     quit()
#                 splitted = job_cluster.split("@")
#                 if splitted[0] == "PBS":
#                     job_system = JobSystem.PBS
#                     if len(splitted) != 2:
#                         print(
#                             "[ERROR] PBS job shold called as PBS@<cluster_server_name>"
#                         )
#                         quit()
#                     server_name = splitted[1]
#                 else:
#                     print("[ERROR] PBS job shold called as PBS@<cluster_server_name>")
#                     quit()
#         directory_time_str = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
#         job_directory = f"{Config.PROJ_ROOT}/jobs/auto/1_count/{directory_time_str}"
#         os.makedirs(job_directory, exist_ok=True)
#         log_dir = f"{Config.PROJ_ROOT}/jobs/auto/1_count/{directory_time_str}/logs"
#         if not os.path.exists(log_dir):
#             os.makedirs(log_dir, exist_ok=True)
#         for job in split_jobs(len(target_gsms), cluster):
#             if job_system == JobSystem.PBS:
#                 result_cmd = (
#                     "".join(
#                         PBS(
#                             nthread,
#                             server_name,
#                             job_system.name,
#                             f"{log_dir}/cluster{cluster_num}.log",
#                         ).header
#                     )
#                     + "\n"
#                 )
#             else:
#                 result_cmd = ""
#             if job != 0:
#                 for __gsm in target_gsms[__base_job_num : __base_job_num + job]:
#                     __generated = self.build_job(current[__gsm], each_nthread=nthread)
#                     if __generated is not None:
#                         result_cmd += __generated
#                 with open(f"{job_directory}/cluster{cluster_num}.sh", mode="w") as f:
#                     f.write(result_cmd)
#                 cluster_num += 1
#             __base_job_num += job
#             if not self.options.ContainsKey("norun"):
#                 for target_cluster in range(cluster_num):
#                     if job_system == JobSystem.default_bash:
#                         subprocess.run(
#                             f"bash {job_directory}/cluster{target_cluster}.sh",
#                             shell=True,
#                         )
#                     elif job_system == JobSystem.nohup:
#                         subprocess.run(
#                             f"nohup bash {job_directory}/cluster{target_cluster}.sh > {Config.PROJ_ROOT}/jobs/auto/0_dump/{directory_time_str}/__logs.log &",
#                             shell=True,
#                         )
#                     elif job_system == JobSystem.PBS:
#                         subprocess.run(
#                             f"qsub {job_directory}/cluster{target_cluster}.sh",
#                             shell=True,
#                         )
#                     else:
#                         print("[ERROR] Unknown job system :(")
#         return
