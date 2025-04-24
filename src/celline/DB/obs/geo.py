from celline.DB.model import SRA_GSE, SRA_GSM, SRA_SRR

from tqdm import tqdm
from IPython.display import display, clear_output


class GEOHandler:
    # Sync
    # EXEC_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    # PATH = f"{EXEC_ROOT}/DB/GEO_relation.yaml"
    # if os.path.isfile(PATH):
    #     with open(PATH, mode="r", encoding="utf-8") as f:
    #         self.geo: GEORelation = deserialize(yaml.safe_load(f), GEORelation)  # type: ignore
    @staticmethod
    def sync(target_gsm_id: str, force_search=False, log=True) -> None:
        srr_instance = SRA_SRR()
        schema = SRA_GSM().search(target_gsm_id, force_search)
        ## Read Parent
        _ = SRA_GSE().search(schema.parent_gse_id, force_search)
        ## Read Child
        ids = schema.child_srr_ids.split(",")
        cnt = 1
        for srr in ids:
            if log:
                print(f"--> Migrating {srr} ({cnt}/{len(ids)})")
            _ = srr_instance.search(srr, force_search)
            cnt += 1
        # gses = gse_instance.as_schema(GSE.Schema)
        # for gse in gses:
        #     if log:
        #         print(f"Migrating GSE: {gse.accession_id}")
        #     for gsm_id in gse.child_gsm_ids.split(","):
        #         if log:
        #             print(f"--> Migrating GSM: {gsm_id}")
        #         for srr_id in gsm_instance.search(gsm_id).child_srr_ids.split(","):
        #             if log:
        #                 print(f"--> --> Migrating SRR: {srr_id}")
        #             srr_instance.search(srr_id)
        # for srr in srr_instance.as_schema(SRR.Schema):
        #     gse_instance.search(gsm_instance.search(srr.parent_gsm).parent_gse_id)
        # del gse_instance, gsm_instance, srr_instance
        return

    # @staticmethod
    # def sync(log=True) -> None:
    #     gse_instance = GSE()
    #     gsm_instance = GSM()
    #     srr_instance = SRR()

    #     gses = gse_instance.as_schema(GSE.Schema)
    #     pbar1 = tqdm(gses, desc="GSE", dynamic_ncols=True)
    #     for gse in pbar1:
    #         pbar1.set_description(f"Migrating GSE: {gse.accession_id}")
    #         gsm_ids = gse.child_gsm_ids.split(",")
    #         pbar2 = tqdm(gsm_ids, desc="GSM", leave=False, dynamic_ncols=True)
    #         for gsm_id in pbar2:
    #             pbar2.set_description(f"--> Migrating GSM: {gsm_id}")
    #             srr_ids = gsm_instance.search(gsm_id).child_srr_ids.split(",")
    #             pbar3 = tqdm(srr_ids, desc="SRR", leave=False, dynamic_ncols=True)
    #             for srr_id in pbar3:
    #                 pbar3.set_description(f"--> --> Migrating SRR: {srr_id}")
    #                 srr_instance.search(srr_id)
    #             pbar3.close()
    #         pbar2.close()

    #     srrs = srr_instance.as_schema(SRR.Schema)
    #     pbar4 = tqdm(srrs, desc="SRR", dynamic_ncols=True)
    #     for srr in pbar4:
    #         gse_instance.search(gsm_instance.search(srr.parent_gsm).parent_gse_id)
    #     pbar4.close()

    #     del gse_instance, gsm_instance, srr_instance
    #     return

    # def __sync(self):
    #     gse_instance = GSE()
    #     gsm_instance = GSM()
    #     srr_instance = SRR()

    #     gses = gse_instance.as_schema(GSE.Schema)
    #     gsm_cache = {}
    #     for gse in gses:
    #         for gsm_id in gse.child_gsm_ids.split(","):
    #             if gsm_id not in gsm_cache:
    #                 gsm_cache[gsm_id] = gsm_instance.search(gsm_id)
    #             for srr_id in gsm_cache[gsm_id].child_srr_ids.split(","):
    #                 srr_instance.search(srr_id)

    #     srrs = srr_instance.as_schema(SRR.Schema)
    #     gse_cache = {}
    #     for srr in srrs:
    #         gsm_id = srr.parent_gsm
    #         if gsm_id not in gsm_cache:
    #             gsm_cache[gsm_id] = gsm_instance.search(gsm_id)
    #         gse_id = gsm_cache[gsm_id].parent_gse_id
    #         if gse_id not in gse_cache:
    #             gse_cache[gse_id] = gse_instance.search(gse_id)

    #     return

    # def flush(self):
    #     print(serialize(self.geo))
    #     return
