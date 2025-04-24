from typing import Callable, List, Final, NamedTuple, Type, TypeVar
from celline.DB.dev.model import BaseModel, Primary, BaseSchema


class CNCB_CRA_Schema(BaseSchema):
    summary: str
    species: str


class CNCB_CRA(BaseModel):
    def set_class_name(self) -> str:
        return __class__.__name__

    def set_schema(self) -> type[CNCB_CRA_Schema]:
        return CNCB_CRA_Schema
