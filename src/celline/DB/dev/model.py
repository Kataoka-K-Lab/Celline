from __future__ import annotations
from typing import (
    List,
    Dict,
    TypeVar,
    Generic,
    Final,
    Type,
    get_type_hints,
    Callable,
    Optional,
    get_origin,
    get_args,
)
from celline.utils.exceptions import NullPointException
import polars as pl
from dataclasses import dataclass, fields

# from celline.config import Config
from abc import ABCMeta, abstractmethod, ABC
import os
import inspect

from pprint import pprint
from polars import Expr
from celline.config import Config

## Type vars #############
TPrimary = TypeVar("TPrimary")
##########################


class Primary(Generic[TPrimary]):
    """As primary key"""

    def __init__(self, value: TPrimary = None):
        self._value = value

    def __get__(self, instance, owner):
        if instance is None:
            return self
        return self._value

    def __set__(self, instance, value: TPrimary):
        instance.__dict__[self] = value

    def __str__(self):
        return str(self._value)

    def __repr__(self):
        return f"Primary(value={self._value!r})"


class MultiplePrimaryKeysError(Exception):
    pass


class NoPrimaryKeyError(Exception):
    pass


@dataclass
@abstractmethod
class BaseSchema:
    key: Primary[str]
    parent: Optional[str]
    children: Optional[str]
    title: Optional[str]


@dataclass
@abstractmethod
class SampleSchema(BaseSchema):
    summary: str
    species: str
    raw_link: str


@dataclass
@abstractmethod
class RunSchema(BaseSchema):
    strategy: str
    raw_link: str


TSchema = TypeVar("TSchema", bound=BaseSchema)


class BaseModel(Generic[TSchema], ABC):
    _df: pl.DataFrame
    __class_name: str = ""
    schema: Final[Type[TSchema]]
    PATH: Final[str]
    EXEC_ROOT: Final[str]

    def __init__(self) -> None:
        self.__class_name = self.set_class_name()
        self.schema = self.def_schema()
        self.EXEC_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
        self.PATH = f"{self.EXEC_ROOT}/DB/{self.__class_name}.parquet"
        if os.path.isfile(self.PATH):
            self._df = pl.read_parquet(self.PATH)
        else:
            self._df = pl.DataFrame(
                {},
                schema={
                    name: get_args(t)[0]
                    if hasattr(t, "__origin__") and t.__origin__ is Primary
                    else t
                    for name, t in get_type_hints(self.schema).items()
                },
            )
            self._df.write_parquet(self.PATH)

    @abstractmethod
    def set_class_name(self) -> str:
        return __class__.__name__

    @abstractmethod
    def def_schema(self) -> Type[TSchema]:
        return

    # TS = TypeVar("TS", bound=Schema)

    @abstractmethod
    def search(self, acceptable_id: str, force_search=False) -> TSchema:
        return

    def exists(self, acceptable_id: str):
        return (self.stored.filter(self.plptr("key") == acceptable_id).shape[0]) != 0

    def get_cache(self, acceptable_id: str, force_search=False) -> Optional[TSchema]:
        if self.exists(acceptable_id) and not force_search:
            return self.as_schema(
                self.stored.filter(self.plptr("key") == acceptable_id).head(1),
            )[0]
        return None

    def as_schema(self, _df: Optional[pl.DataFrame] = None) -> List[TSchema]:
        if _df is None:
            _df = self._df

        type_hints = get_type_hints(self.schema)

        data = _df.to_pandas().itertuples(index=False)
        return [
            self.schema(
                *(
                    str(Primary(val)) if get_origin(type_hint) is Primary else val
                    for val, type_hint in zip(t, type_hints.values())
                )
            )
            for t in data
        ]

    def get(
        self, target_schema: Type[TSchema], filter_func: Callable[[TSchema], bool]
    ) -> List[TSchema]:
        type_hints = get_type_hints(target_schema)

        data = self._df.to_pandas().itertuples(index=False)
        result: List[TSchema] = []
        for schema_each in [
            target_schema(
                *(
                    val if get_origin(type_hint) is Primary else val
                    for val, type_hint in zip(t, type_hints.values())
                )
            )
            for t in data
        ]:
            if filter_func(schema_each):
                result.append(schema_each)
        return result
        # tname = ""
        # for name in self.schema._fields:
        #     if getattr(self.schema, name) == filter_col:
        #         tname = name
        #         break
        # if tname == "":
        #     raise NullPointException(
        #         "Plptr is unknown. Please designate ***.Scheme.***"
        #     )
        # target_column: List = []
        # for column in self._df.get_column(tname).to_list():
        #     if filter_func(column):
        #         target_column.append(column)
        # # target_df = self._df.filter(pl.col(tname).is_in(target_column))
        # # self.schema(target_df)
        # return [
        #     self.schema(*row)
        #     for row in self._df.filter(pl.col(tname).is_in(target_column))
        #     .to_pandas()
        #     .itertuples(index=False)
        # ]  # type: ignore

    def plptr(self, col) -> pl.Expr:
        """Returns a pointer to the column that applies to col."""
        tname = ""

        for field in fields(self.schema):
            if field.name == col:
                tname = field.name
                # type_origin = get_origin(field.type)
                # if type_origin is not None:
                #     tname = get_args(field.type)[0]
                #     print(f"{field.name}: {field.type} -> {tname}")
                #     break
                # else:
                #     tname = field.type
        if tname == "":
            raise NullPointException(
                "Plptr is unknown. Please designate ***.Scheme.***"
            )
        return pl.col(tname)

    def get_all_type_hints(cls: Type) -> dict:  # type: ignore
        hints = {}
        for base in reversed(cls.mro()):
            hints.update(get_type_hints(base))
        return hints

    def as_dataframe(self, schema_instance: TSchema) -> pl.DataFrame:
        type_hints = BaseModel.get_all_type_hints(type(schema_instance))
        for field, type_hint in type_hints.items():
            if get_origin(type_hint) is Primary:
                type_hints[field] = get_args(type_hint)[0]  # Replace Primary[T] with T

        return pl.DataFrame(
            {
                f.name: [getattr(schema_instance, f.name)]
                for f in fields(schema_instance)
            },
            schema=type_hints,
        )

    def add_schema(
        self, schema_instance: TSchema, force_update: bool = True
    ) -> TSchema:
        all_t: Dict[str, Type] = BaseModel.get_all_type_hints(type(schema_instance))
        primary_fields = [
            field
            for field in fields(schema_instance)
            if get_origin(all_t[field.name]) is Primary
        ]
        if not primary_fields:
            raise NoPrimaryKeyError("No primary key found.")

        if len(primary_fields) > 1:
            raise MultiplePrimaryKeysError("Multiple primary keys found.")

        mask: Expr = pl.lit(True)
        if force_update:
            for primary_field in primary_fields:
                primary_val = getattr(schema_instance, primary_field.name)
                mask &= pl.col(primary_field.name) == primary_val

            if self._df.filter(mask).shape[0] > 0:
                self._df = self._df.filter(~mask)
        newdata = self.as_dataframe(schema_instance)
        self._df = pl.concat([self._df, newdata])
        self.flush()
        return self.as_schema(newdata)[0]

    def flush(self):
        self._df.write_parquet(f"{self.EXEC_ROOT}/DB/{self.__class_name}.parquet")

    @property
    def stored(self) -> pl.DataFrame:
        return self._df
