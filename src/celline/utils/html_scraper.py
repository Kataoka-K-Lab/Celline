import requests
from lxml import html
from lxml.html import HtmlElement
from typing import Optional, List
import polars as pl


class HTMLScrapeHelper:
    def __init__(self, url: str) -> None:
        response = requests.get(url, timeout=200)
        response.raise_for_status()
        self.__parsed_html: HtmlElement = html.fromstring(response.content)

    def get(self, xpath: str) -> Optional[List[HtmlElement]]:
        el = self.__parsed_html.xpath(xpath)
        if len(el) == 0:
            return None
        return el

    def get_ignoreerr(self, xpath: str) -> List[HtmlElement]:
        res = self.get(xpath)
        if res is None:
            return []
        return res

    def as_dataframe(self, xpath: str):
        data = []
        target_frame = self.get(xpath)
        if target_frame is None:
            raise LookupError(f"Could not find target xpath: {xpath}")
        rows = target_frame[0].xpath(".//tr")

        # ヘッダーを取得
        header = [col.text for col in rows[0].xpath(".//th")]

        data = []
        for row in rows[1:]:
            data.append([col.text for col in row.xpath(".//td")])

        return pl.DataFrame(
            {header[i]: [row[i] for row in data] for i in range(len(header))}
        )
