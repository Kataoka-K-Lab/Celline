from __future__ import annotations

from dataclasses import dataclass

# import celline.DB._base import
from typing import Final
from xml.etree import ElementTree as ET
from xml.etree.ElementTree import Element

import requests
from pysradb.sraweb import SRAweb

from celline.DB.dev.model import BaseModel, BaseSchema

# from celline.utils.type import pl_ptr


@dataclass
class SRA_GSE_Schema(BaseSchema):
    summary: str


class SRA_GSE(BaseModel[SRA_GSE_Schema]):
    DB: Final[SRAweb] = SRAweb()

    @classmethod
    def build_request_url(cls, gsm_id: str):
        return f"https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc={gsm_id}&targ=all&view=quick&form=xml"

    @classmethod
    def __fetch_result(cls, gsm_id: str):
        def _strip_namespace(elem: Element) -> None:
            """
            Remove the namespace from the XML tags.
            """
            elem.tag = elem.tag.split("}", 1)[-1] if "}" in elem.tag else elem.tag
            for child in elem:
                _strip_namespace(child)

        try:
            xml = requests.get(
                cls.build_request_url(gsm_id),
                timeout=100,
            )
        except ET.ParseError as err:
            print(f"Could not find target GSE: {gsm_id}")
            print("Tracebacks")
            print(err)
        gse_xml = ET.fromstring(xml.content.decode())  # type: ignore
        _strip_namespace(gse_xml)
        return gse_xml

    def set_class_name(self) -> str:
        return __class__.__name__

    def def_schema(self) -> type[SRA_GSE_Schema]:
        return SRA_GSE_Schema

    def search(self, acceptable_id: str, force_search=False) -> SRA_GSE_Schema:
        cache = self.get_cache(acceptable_id, force_search)
        if cache is not None:
            return cache
        __result = SRA_GSE.__fetch_result(acceptable_id)
        ser = __result.find("Series")
        if ser is None:
            raise ModuleNotFoundError(
                f"Could not found Series element: {acceptable_id}"
            )
        title = ser.find("Title")
        if title is None:
            raise ModuleNotFoundError(f"Could not found Title element: {acceptable_id}")
        summary = ser.find("Summary")
        if summary is None:
            raise ModuleNotFoundError(
                f"Could not found Summary element: {acceptable_id}"
            )
        return self.add_schema(
            SRA_GSE_Schema(
                key=acceptable_id,
                title=title.text if title.text is not None else "Unknown",
                summary=summary.text if summary.text is not None else "Unknown",
                children=",".join([
                    el.attrib["iid"] for el in __result.findall("Sample")
                ]),
                parent=None,
            )
        )
