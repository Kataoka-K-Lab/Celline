from typing import NamedTuple
from typing import Dict, Any, get_type_hints, TypeVar, Generic, List, Type
import inspect
import polars as pl


class NamedTupleAndDictStructure:
    @staticmethod
    def serialize(obj) -> Dict[str, Any]:
        """Serialize given obj (inherits NamedTuple) to dictionary type"""
        if isinstance(obj, tuple) and hasattr(
            obj, "_fields"
        ):  # check if obj is a namedtuple or subclass
            return {f: NamedTupleAndDictStructure.serialize(getattr(obj, f)) for f in obj._fields}  # type: ignore
        elif isinstance(obj, list):
            return [NamedTupleAndDictStructure.serialize(v) for v in obj]  # type: ignore
        else:
            return obj  # type: ignore

    T = TypeVar("T")

    @staticmethod
    def deserialize(data: Dict, namedtuple_cls: T) -> T:
        """Deserialize give dictionary to give type T instance"""
        if (
            inspect.isclass(namedtuple_cls)
            and issubclass(namedtuple_cls, tuple)
            and hasattr(namedtuple_cls, "_fields")
        ):
            fields = {
                f: NamedTupleAndDictStructure.deserialize(data.get(f, None), t)
                for f, t in get_type_hints(namedtuple_cls).items()
            }
            return namedtuple_cls(**fields)  # type: ignore
        elif isinstance(namedtuple_cls, list) and len(namedtuple_cls) == 1:
            return [NamedTupleAndDictStructure.deserialize(v, namedtuple_cls[0]) for v in data]  # type: ignore
        else:
            return data  # type: ignore


T = TypeVar("T", bound=NamedTuple)


class NamedTupleAndPolarsStructure(Generic[T]):
    @staticmethod
    def serialize(obj: NamedTuple) -> pl.DataFrame:
        return pl.DataFrame(
            {field: [getattr(obj, field)] for field in obj._fields},
            schema=get_type_hints(obj),
        )

    @staticmethod
    def deserialize(df: pl.DataFrame, tuple_type: Type[T]) -> List[T]:
        return [tuple_type(*t) for t in df.to_pandas().itertuples(index=False)]  # type: ignore
