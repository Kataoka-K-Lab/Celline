from typing import Callable, List, Final, NamedTuple, Type, TypeVar
from celline.DB.dev.model import BaseModel, Primary, BaseSchema
from dataclasses import dataclass
from celline.utils.html_scraper import HTMLScrapeHelper


@dataclass
class CNCB_PRJCA_Schema(BaseSchema):
    summary: str


class CNCB_PRJCA(BaseModel[CNCB_PRJCA_Schema]):
    BASE_URL: Final[str] = "https://ngdc.cncb.ac.cn/bioproject/browse"

    class HTMLStructure(NamedTuple):
        Title = "/html/body/div[2]/div/div/div[1]/div/div[1]/table/tr[2]/td"
        Summary = "/html/body/div[2]/div/div/div[1]/div/div[1]/table/tr[6]/td"

    def set_class_name(self) -> str:
        return __class__.__name__

    def def_schema(self) -> type[CNCB_PRJCA_Schema]:
        return CNCB_PRJCA_Schema

    def search(self, acceptable_id: str, force_search=False) -> CNCB_PRJCA_Schema:
        helper = HTMLScrapeHelper(f"{CNCB_PRJCA.BASE_URL}/{acceptable_id}")
        return super().search(acceptable_id, force_search)
