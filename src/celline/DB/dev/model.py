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
    Any,
)
from celline.utils.exceptions import NullPointException
from dataclasses import dataclass, fields, asdict

from abc import ABCMeta, abstractmethod, ABC
import os

from celline.config import Config
from celline.DB.dev.excel_handler import ExcelMetadataHandler

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
    _excel_handler: ExcelMetadataHandler
    __class_name: str = ""
    schema: Final[Type[TSchema]]
    EXCEL_PATH: str
    _sheet_name: str = ""

    def __init__(self, validate_on_init: bool = False) -> None:
        self.__class_name = self.set_class_name()
        self.schema = self.def_schema()
        # Get PROJ_ROOT from running Config instance
        if Config.current in Config.runnings:
            self.EXCEL_PATH = f"{Config.runnings[Config.current].PROJ_ROOT}/metadata.xlsx"
        else:
            raise RuntimeError("Config not initialized. Please create a Config instance first.")
        self._sheet_name = self._get_sheet_name()
        self._excel_handler = ExcelMetadataHandler(self.EXCEL_PATH)

        # Only validate structure on init, not data integrity
        if validate_on_init:
            self._validate_structure_only()

    def _get_sheet_name(self) -> str:
        """Determine the sheet name (samples, projects, or runs) based on schema type."""
        if issubclass(self.schema, SampleSchema):
            return "samples"
        elif issubclass(self.schema, RunSchema):
            return "runs"
        else:
            return "projects"

    def _validate_structure_only(self) -> None:
        """Validate only Excel file structure (sheets and columns)."""
        structure_result = self._excel_handler.validate_structure()
        if not structure_result.is_valid:
            error_msgs = [f"{e.error_type}: {e.message}" for e in structure_result.errors]
            raise ValueError(f"Excel structure validation failed:\n" + "\n".join(error_msgs))

    def validate_data_integrity(self) -> None:
        """
        Validate data integrity across all sheets.
        This should be called manually after all data has been added.
        """
        integrity_result = self._excel_handler.validate_data_integrity()
        if not integrity_result.is_valid:
            error_msgs = [
                f"Sheet '{e.sheet}' Row {e.row} Column '{e.column}': {e.error_type} - {e.message}"
                for e in integrity_result.errors
            ]
            raise ValueError(f"Excel data integrity validation failed:\n" + "\n".join(error_msgs))

        # Log warnings
        if integrity_result.warnings:
            import warnings
            for w in integrity_result.warnings:
                warnings.warn(
                    f"Sheet '{w.sheet}' Row {w.row} Column '{w.column}': {w.error_type} - {w.message}",
                    UserWarning
                )

    @abstractmethod
    def set_class_name(self) -> str:
        return __class__.__name__

    @abstractmethod
    def def_schema(self) -> Type[TSchema]:
        return

    @abstractmethod
    def search(self, acceptable_id: str, force_search=False) -> TSchema:
        return

    def exists(self, acceptable_id: str) -> bool:
        """Check if an entry exists in the storage."""
        record = self._excel_handler.get_record(self._sheet_name, acceptable_id)
        return record is not None

    def get_cache(self, acceptable_id: str, force_search=False) -> Optional[TSchema]:
        """Get cached entry if exists and force_search is False."""
        if self.exists(acceptable_id) and not force_search:
            record = self._excel_handler.get_record(self._sheet_name, acceptable_id)
            if record:
                return self._dict_to_schema(record)
        return None

    def _dict_to_schema(self, data: Dict[str, Any]) -> TSchema:
        """Convert dictionary to schema instance."""
        import pandas as pd
        type_hints = get_type_hints(self.schema)
        kwargs = {}
        for field_name, field_type in type_hints.items():
            if field_name in data:
                value = data[field_name]
                # Handle pandas NaN
                if pd.isna(value):
                    kwargs[field_name] = None
                elif get_origin(field_type) is Primary:
                    kwargs[field_name] = str(value) if value is not None else None
                else:
                    kwargs[field_name] = value
            else:
                kwargs[field_name] = None
        return self.schema(**kwargs)

    def _schema_to_dict(self, schema_instance: TSchema) -> Dict[str, Any]:
        """Convert schema instance to dictionary."""
        result = {}
        for field in fields(schema_instance):
            value = getattr(schema_instance, field.name)
            if isinstance(value, Primary):
                result[field.name] = str(value)
            else:
                result[field.name] = value if value is not None else ""
        return result

    def as_schema(self, keys: Optional[List[str]] = None) -> List[TSchema]:
        """Convert stored data to schema instances."""
        df = self._excel_handler.read_sheet(self._sheet_name)
        if df.empty:
            return []

        if keys is not None:
            df = df[df["key"].astype(str).isin(keys)]

        result = []
        for _, row in df.iterrows():
            result.append(self._dict_to_schema(row.to_dict()))
        return result

    def get(
        self, target_schema: Type[TSchema], filter_func: Callable[[TSchema], bool]
    ) -> List[TSchema]:
        """Get entries matching the filter function."""
        all_records = self.as_schema()
        return [record for record in all_records if filter_func(record)]

    def get_all_type_hints(cls: Type) -> dict:
        """Get all type hints including from base classes."""
        hints = {}
        for base in reversed(cls.mro()):
            hints.update(get_type_hints(base))
        return hints

    def add_schema(
        self, schema_instance: TSchema, force_update: bool = True
    ) -> TSchema:
        """
        Add or update a schema instance in storage.
        Note: Does not validate data integrity automatically.
        Call validate_data_integrity() manually when all data is added.
        """
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

        primary_key = str(getattr(schema_instance, primary_fields[0].name))
        record = self._schema_to_dict(schema_instance)

        self._excel_handler.add_or_update_record(self._sheet_name, record)

        # Return the stored record
        stored_record = self._excel_handler.get_record(self._sheet_name, primary_key)
        if stored_record:
            return self._dict_to_schema(stored_record)
        return schema_instance

    def flush(self):
        """Flush data to Excel file (not needed as writes are immediate)."""
        pass

    @property
    def stored(self) -> List[Dict[str, Any]]:
        """Return all stored data as list of dictionaries."""
        df = self._excel_handler.read_sheet(self._sheet_name)
        return df.to_dict('records')
