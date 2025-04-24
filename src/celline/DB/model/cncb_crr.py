from typing import Callable, List, Final, NamedTuple, Type, TypeVar
from celline.DB.dev.model import BaseModel, Primary, RunSchema


class CNCB_CRR_Schema(RunSchema):
    summary: str
    species: str


class CNCB_CRR(BaseModel):
    def set_class_name(self) -> str:
        return __class__.__name__

    def set_schema(self) -> type[CNCB_CRR_Schema]:
        return CNCB_CRR_Schema
