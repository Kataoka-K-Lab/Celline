from typing import Optional

import pyper as pr

from celline.config import Config, Setting


class RHandler:
    """Type-safe r handler for python users"""

    __r: pr.R

    def __init__(self, r_path: Optional[str] = None) -> None:
        """Create a new R session"""
        if r_path is None:
            r_path = Setting.r_path
        self.__r = pr.R(RCMD=Setting.r_path, use_pandas=True)

    def library(self, lib_name: str):
        self.__r(f"library({lib_name})")
        return self

    def use(self, file_path: str):
        with open(file_path, mode="r") as f:
            self.__r("\n".join(f.readlines()))
        return self
