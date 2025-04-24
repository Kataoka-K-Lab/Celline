# from __future__ import annotations
# from typing import Final, Type
from typing import Union
from celline.DB.dev.handler import BaseHandler
from celline.DB.model import CNCB_PRJCA, CNCB_CRA, CNCB_CRR


class CNCBHandler(BaseHandler[CNCB_PRJCA, CNCB_CRA, CNCB_CRR]):
    def resolver(self, acceptable_id: str):
        self._project = CNCB_PRJCA()
        if acceptable_id.startswith("PRJCA"):
            return CNCB_PRJCA


#     BASE_XML_PATH: Final[
#         str
#     ] = "https://ngdc.cncb.ac.cn/gwh/gsa/ajax/getAssembliesListByBioSampleAccession"

#     class XStructure:
#         ACCESSIOM_ID: Final[
#             str
#         ] = "/html/body/div[2]/div/div/div[1]/div/div[1]/table/tr[1]/td"
#         TITLE: Final[str] = "/html/body/div[2]/div/div/div[1]/div/div[1]/table/tr[2]/td"
#         SUMMARY: Final[
#             str
#         ] = "/html/body/div[2]/div/div/div[1]/div/div[1]/table/tr[6]/td"
#         SPECIES: Final[
#             str
#         ] = "/html/body/div[2]/div/div/div[1]/div/div[1]/table/tr[5]/td/a"
#         PARENT: Final[
#             str
#         ] = "/html/body/div[2]/div/div/div[1]/div/div[1]/table/tr[9]/td/a"
#         CHILD: Final[
#             str
#         ] = "/html/body/div[2]/div/div/div[1]/div/div[1]/table/tr[9]/td/a"

#     def __init__(self, acceptable_id: str) -> None:
#         super().__init__(acceptable_id)

#     @property
#     def handler(self) -> Type[CNCBHandler]:
#         return __class__

#     @property
#     def project(self) -> CNCB_PRJCA:
#         return super().project
