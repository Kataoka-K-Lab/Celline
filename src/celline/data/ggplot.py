from pyper import R
from multipledispatch import dispatch
import polars as pl
from typing import Dict, NamedTuple, overload, Optional

from celline.utils.r_wrap import as_r_bool, as_r_NULL
from celline.utils.exceptions import RSessionNotFoundException, RException


class ggplot:
    class aes(NamedTuple):
        x: str
        y: str
        color: Optional[str]
        fill: Optional[str]

    @overload
    def __init__(self, r_session: R) -> None:
        ...

    @overload
    def __init__(self, r_session: R, aes_def: aes) -> None:
        ...

    @overload
    def __init__(self, r_session: R, aes_def: aes, df: pl.DataFrame) -> None:
        ...

    def __init__(
        self,
        r_session: Optional[R] = None,
        aes_def: Optional[aes] = None,
        df: Optional[pl.DataFrame] = None,
    ) -> None:
        if r_session is None:
            raise RSessionNotFoundException("Please give rsession.")
        self.r_session = r_session
        if aes_def is None and df is not None:
            raise RException("You should aes_def and df")
        self.aes_def = aes_def
        self.df = aes_def

    @property
    def title(self):
        return self._title

    @title.setter
    def title(self, name: str):
        self._title = name

    _title: Optional[str] = None
    _x_name: Optional[str]
    _y_name: Optional[str]

    def labs(
        self,
        title: Optional[str] = None,
        x: Optional[str] = None,
        y: Optional[str] = None,
    ):
        if title is not None:
            self._title = title
        if x is not None:
            self._x_name = x
        if y is not None:
            self._y_name = y
        return self

    def ggsave(
        self,
        file_path: str,
        width: int,
        height: int,
        units="cm",
        dpi=300,
        limitsize=True,
    ):
        self.r_session.assign(
            "ggplot.title", self.title if self.title is not None else "title"
        )
        log = self.r_session(
            f"""
plt <-
    plt +
    labs(
        title = ggplot.title
    )
ggsave(filename = "{file_path}", plot = plt, width = {width}, height = {height}, units = "{units}", dpi = {dpi}, limitsize = {as_r_bool(limitsize)})
"""
        )
        print(log)
