# # import celline.DB._base import
# from enum import Enum, unique
# import polars as pl
# from typing import List, Final, NamedTuple, Type, get_type_hints
# from celline.DB.dev.model import BaseModel
# from pysradb.sraweb import SRAweb
# from pprint import pprint
# from varname import nameof
# from xml.etree import ElementTree as ET
# from xml.etree.ElementTree import Element, ElementTree
# import requests


# class GSM(BaseModel):
#     DB: Final[SRAweb] = SRAweb()

#     class Schema(NamedTuple):
#         accession_id: str
#         title: str
#         summary: str
#         species: str
#         raw_link: str
#         srx_id: str
#         parent_gse_id: str
#         child_srr_ids: str
#         # projna_id = Ref
#         # srp_id = "srp_id"

#     def set_class_name(self) -> str:
#         return __class__.__name__

#     def set_schema(self) -> Type[Schema]:
#         return GSM.Schema

#     def exist(self, gsm_id: str):
#         return (
#             self.df.filter(self.plptr(GSM.Schema.accession_id) == gsm_id).shape[0]
#         ) != 0

#     BASE_REQUEST_URL: Final[str] = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc="

#     def search(self, gsm_id: str) -> Schema:
#         if self.exist(gsm_id):
#             return self.as_schema(
#                 GSM.Schema,
#                 self.df.filter(self.plptr(GSM.Schema.accession_id) == gsm_id).head(1),
#             )[0]
#         xml = requests.get(
#             f"{GSM.BASE_REQUEST_URL}{gsm_id}&targ=all&view=quick&form=xml", timeout=100
#         )

#         def strip_namespace(elem: Element):
#             elem.tag = elem.tag.split("}", 1)[-1] if "}" in elem.tag else elem.tag
#             for child in elem:
#                 strip_namespace(child)
#             # [strip_namespace(child) for child in elem]

#         gsm_xml = ET.fromstring(xml.content.decode())
#         strip_namespace(gsm_xml)
#         __series = gsm_xml.find("Series")
#         if __series is None:
#             raise KeyError(f"Requested GSM: {gsm_id} does not exists in database.")

#         def get_run_ids_from_srp(srp):
#             base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
#             db = "sra"
#             retmode = "xml"
#             search_url = f"{base_url}esearch.fcgi?db={db}&term={srp}&retmode={retmode}"
#             response = requests.get(search_url, timeout=100)
#             root = ET.fromstring(response.content)
#             # SRA Project IDを取得
#             id_list = root.find("IdList")
#             sra_project_id = ""
#             for __id in id_list.findall("Id"):
#                 sra_project_id = __id.text
#                 break
#             # SRA Project IDを使って関連するSRA Run IDを取得
#             fetch_url = (
#                 f"{base_url}efetch.fcgi?db={db}&id={sra_project_id}&retmode={retmode}"
#             )
#             response = requests.get(fetch_url, timeout=100)
#             root = ET.fromstring(response.content)
#             return [
#                 run.attrib["accession"]
#                 for run in root.find("EXPERIMENT_PACKAGE").find("RUN_SET").findall("*")
#             ]

#         __proto = gsm_xml.find("Sample/Extract-Protocol")
#         __organism = gsm_xml.find("Sample/Organism")
#         __srps = [
#             rel.attrib["target"].split("?term=")[1]
#             for rel in gsm_xml.findall("Sample/Relation")
#             if rel.attrib["type"] == "SRA"
#         ]
#         if len(__srps) > 0:
#             __srps = get_run_ids_from_srp(__srps[0])
#         else:
#             __srps = ""

#         newdata = self.add_schema(
#             GSM.Schema(
#                 accession_id=gsm_id,
#                 title=gsm_xml.find("Sample/Title").text,
#                 summary=__proto.text if __proto is not None else "",
#                 species=__organism.text if __organism is not None else "",
#                 raw_link=",".join(
#                     [raw.text for raw in gsm_xml.findall("Series/Supplementary-Data")]
#                 ),
#                 srx_id=gsm_xml.find("Series/Relation").text,
#                 parent_gse_id=__series.attrib["iid"] if __series is not None else "",
#                 child_srr_ids=",".join(__srps),
#             )
#         )
#         del __series
#         return newdata  # type: ignore

from enum import Enum, unique
from typing import List, NamedTuple, Optional, Type, get_type_hints, Final
from pysradb.sraweb import SRAweb
from xml.etree import ElementTree as ET
from xml.etree.ElementTree import Element, ElementTree
import requests

from celline.DB.dev.model import BaseModel, Primary, BaseSchema, SampleSchema
from dataclasses import dataclass


@dataclass
class SRA_GSM_Schema(SampleSchema):
    srx_id: str


class SRA_GSM(BaseModel[SRA_GSM_Schema]):
    """
    Class to fetch data from the Gene Expression Omnibus (GEO) database.
    """

    DB: SRAweb = SRAweb()

    def set_class_name(self) -> str:
        return __class__.__name__

    def def_schema(self) -> type:
        return SRA_GSM_Schema

    BASE_REQUEST_URL: Final[str] = "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc="

    def search(self, acceptable_id: str, force_search=False) -> SRA_GSM_Schema:
        """
        Search for a particular GSM id in the database.
        If it exists, returns the data, else fetches it from the GEO database.
        """
        cache = self.get_cache(acceptable_id, force_search)
        if cache is not None:
            return cache
        return self._fetch_gsm_from_geo(acceptable_id)

    def _fetch_gsm_from_geo(self, gsm_id: str) -> SRA_GSM_Schema:
        """
        Fetch GSM data from the GEO database.
        """
        gsm_xml = self._get_gsm_xml(gsm_id)
        self._strip_namespace(gsm_xml)

        series = gsm_xml.find("Series")
        if series is None:
            raise KeyError(f"Requested GSM: {gsm_id} does not exists in database.")

        run_ids = self._get_run_ids_from_srp(gsm_xml)

        return self._add_schema_to_gsm(gsm_xml, gsm_id, run_ids, series)

    @staticmethod
    def _get_gsm_xml(gsm_id: str) -> ElementTree:
        """
        Get the GSM data in XML format.
        """
        try:
            xml = requests.get(
                f"{SRA_GSM.BASE_REQUEST_URL}{gsm_id}&targ=all&view=quick&form=xml",
                timeout=100,
            )
        except ET.ParseError as err:
            print(f"Could not find target GSM: {gsm_id}")
            print("Tracebacks")
            print(err)
        return ET.fromstring(xml.content.decode())

    @staticmethod
    def get_gsm_xml_structure(gsm_id: str):
        gsm_xml = SRA_GSM._get_gsm_xml(gsm_id)
        SRA_GSM._strip_namespace(gsm_xml)

        series = gsm_xml.find("Series")
        if series is None:
            raise KeyError(f"Requested GSM: {gsm_id} does not exists in database.")
        return gsm_xml

    @staticmethod
    def _strip_namespace(elem: Element) -> None:
        """
        Remove the namespace from the XML tags.
        """
        elem.tag = elem.tag.split("}", 1)[-1] if "}" in elem.tag else elem.tag
        for child in elem:
            SRA_GSM._strip_namespace(child)

    def _get_run_ids_from_srp(self, gsm_xml: ElementTree) -> str:
        """
        Get the Run IDs associated with the SRA Project ID.
        """
        srp = [
            rel.attrib["target"].split("?term=")[1]
            for rel in gsm_xml.findall("Sample/Relation")
            if rel.attrib["type"] == "SRA"
        ]

        if srp:
            return self._fetch_run_ids_from_sra(srp[0])
        else:
            return ""

    def _fetch_run_ids_from_sra(self, srp: str) -> str:
        """
        Fetch the Run IDs from the SRA database.
        """
        base_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        db = "sra"
        retmode = "xml"
        search_url = f"{base_url}esearch.fcgi?db={db}&term={srp}&retmode={retmode}"
        response = requests.get(search_url, timeout=100)
        root = ET.fromstring(response.content)
        sra_project_id = (
            root.find("IdList/Id").text if root.find("IdList/Id") is not None else ""
        )

        fetch_url = (
            f"{base_url}efetch.fcgi?db={db}&id={sra_project_id}&retmode={retmode}"
        )
        response = requests.get(fetch_url, timeout=100)
        root = ET.fromstring(response.content)
        return ",".join(
            run.attrib["accession"]
            for run in root.find("EXPERIMENT_PACKAGE/RUN_SET").findall("*")
            if "accession" in run.attrib
        )

    def _add_schema_to_gsm(
        self, gsm_xml: ElementTree, gsm_id: str, run_ids: str, series: Element
    ) -> SRA_GSM_Schema:
        """
        Add the Schema data to the GSM.
        """
        sample = gsm_xml.find("Sample")
        proto = sample.find("Extract-Protocol")
        organism = sample.find("Organism")
        if organism is None:
            platform = gsm_xml.find("Platform")
            if platform is not None:
                organism = platform.find("Organism")
                if organism is None:
                    raise KeyError("Could not identify target species")
            else:
                raise KeyError("Could not identify target species")
        title = sample.find("Title").text if sample.find("Title") is not None else ""
        summary = proto.text if proto is not None else ""
        species = organism.text if organism is not None else ""
        raw_link = ",".join(
            raw.text.replace("\n", "").replace(" ", "")
            for raw in gsm_xml.findall("Series/Supplementary-Data")
            if raw.text is not None
        )
        srx_id = (
            gsm_xml.find("Series/Relation").text
            if gsm_xml.find("Series/Relation") is not None
            else ""
        )
        parent_gse_id = series.attrib["iid"] if "iid" in series.attrib else ""

        return self.add_schema(
            SRA_GSM_Schema(
                key=gsm_id,
                parent=parent_gse_id,
                children=run_ids,
                title=title,
                summary=summary,
                species=species,
                raw_link=raw_link,
                srx_id=srx_id,
            )
        )
