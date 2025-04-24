from typing import Type
import polars as pl
from varname import nameof


class ClassProperty(property):
    """Subclass property to make classmethod properties possible"""

    def __get__(self, _, owner):
        return self.fget.__get__(None, owner)()  # type:ignore


def pl_ptr(variable: Type):
    return pl.col(nameof(variable))
