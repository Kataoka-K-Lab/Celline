from typing import Union
from celline.DB.dev.handler import BaseHandler
from celline.DB.model import SRA_GSE, SRA_GSM, SRA_SRR

from tqdm import tqdm
from IPython.display import display, clear_output


class GEOHandler(BaseHandler[SRA_GSE, SRA_GSM, SRA_SRR]):
    def resolver(self, acceptable_id: str):
        self._project = SRA_GSE()
        self._sample = SRA_GSM()
        self._run = SRA_SRR()
        if acceptable_id.startswith("GSE"):
            return SRA_GSE
        if acceptable_id.startswith("GSM"):
            return SRA_GSM
        if acceptable_id.startswith("SRR"):
            return SRA_SRR
        return None

    # @staticmethod
    # def sync(target_gsm_id: str, force_search=False, log=True) -> None:
    #     srr_instance = SRA_SRR()
    #     schema = SRA_GSM().search(target_gsm_id, force_search)
    #     ## Read Parent
    #     _ = SRA_GSE().search(schema.parent_gse_id, force_search)
    #     ## Read Child
    #     ids = schema.child_srr_ids.split(",")
    #     cnt = 1
    #     for srr in ids:
    #         if log:
    #             print(f"--> Migrating {srr} ({cnt}/{len(ids)})")
    #         _ = srr_instance.search(srr, force_search)
    #         cnt += 1
    #     # gses = gse_instance.as_schema(GSE.Schema)
    #     # for gse in gses:
    #     #     if log:
    #     #         print(f"Migrating GSE: {gse.accession_id}")
    #     #     for gsm_id in gse.child_gsm_ids.split(","):
    #     #         if log:
    #     #             print(f"--> Migrating GSM: {gsm_id}")
    #     #         for srr_id in gsm_instance.search(gsm_id).child_srr_ids.split(","):
    #     #             if log:
    #     #                 print(f"--> --> Migrating SRR: {srr_id}")
    #     #             srr_instance.search(srr_id)
    #     # for srr in srr_instance.as_schema(SRR.Schema):
    #     #     gse_instance.search(gsm_instance.search(srr.parent_gsm).parent_gse_id)
    #     # del gse_instance, gsm_instance, srr_instance
    #     return

    # # def __init__(self, acceptable_id: str) -> None:
    # #     self._project = SRA_GSE()
    # #     self._sample = SRA_GSM()
    # #     self._run = SRA_SRR()
    # #     super().__init__(acceptable_id)
