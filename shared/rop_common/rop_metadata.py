"""
@File    :   rop_metadata.py
@Time    :   2026-11-02
@Author  :   Gabriel SURIER
@Purpose :   Provides the pydantic models of the metadata YAML files and their loader
"""

import re
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from shared.rop_common.rop_errors import IngestionError


class ReadOptions(BaseModel):
    """How to read the delimited file.

    Attributes:
        delimiter: The one character field separator, such as ';'.
        encoding: The file encoding, such as 'utf-8'.
        text_enclosure: The one character quote around fields, such as '"'.
        header: True when the first line holds the column names.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    delimiter: str = Field(min_length=1, max_length=1)
    encoding: str
    text_enclosure: str = Field(min_length=1, max_length=1)
    header: bool


class ColumnMapping(BaseModel):
    """One file column mapped to one table column.

    Attributes:
        source: The header name in the file, or the name given to the position.
        target: The column name in the target table.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str
    target: str


class DerivedColumn(BaseModel):
    """A table column computed from a source column.

    Example: source 'product_cd', pattern '^PRD-(\\d+)$' turns 'PRD-001' into 1.

    Attributes:
        source: The mapped source column holding the code.
        target: The integer table column to fill, such as product_id.
        pattern: A regex with exactly one capture group, the numeric part.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    source: str
    target: str
    pattern: str

    @field_validator("pattern")
    @classmethod
    def check_pattern(cls, value: str) -> str:
        """Checks that the pattern is a regex with exactly one capture group.

        Args:
            value: The pattern read from the YAML.

        Returns:
            The unchanged pattern.

        Raises:
            ValueError: If the regex is invalid or has not one capture group.
        """
        try:
            groups = re.compile(value).groups
        except re.error as exc:
            raise ValueError(f"invalid regex {value}: {exc}") from exc
        if groups != 1:
            raise ValueError(f"pattern {value} needs one capture group, has {groups}")
        return value


class FileMetadata(BaseModel):
    """Metadata shared by every kind of source file, read from its YAML file.

    Attributes:
        name: The flow name, checked against the one the script expects.
        table: The target table as schema.table, reflected from the database.
        mapping: The file columns in file order, each mapped to a table column.
        derived: The table columns computed from a mapped source column.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    table: str
    mapping: list[ColumnMapping] = Field(min_length=1)
    derived: list[DerivedColumn] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_columns(self) -> Self:
        """Checks that sources and targets are unique and derived sources exist.

        Returns:
            The validated metadata.

        Raises:
            ValueError: On a duplicated source or target, or an unmapped source.
        """
        sources = [item.source for item in self.mapping]
        targets = [item.target for item in self.mapping]
        targets += [item.target for item in self.derived]
        if len(set(sources)) != len(sources):
            raise ValueError(f"duplicated source in mapping: {sources}")
        if len(set(targets)) != len(targets):
            raise ValueError(f"duplicated target: {targets}")
        unmapped = [item.source for item in self.derived if item.source not in sources]
        if unmapped:
            raise ValueError(f"derived source not in mapping: {unmapped}")
        return self


class DelimitedFileMetadata(FileMetadata):
    """Metadata of one delimited file flow, read from its YAML file.

    Attributes:
        type: The kind of source, only 'delimited_file' is supported.
        read_options: How to read the file.
    """

    type: Literal["delimited_file"]
    read_options: ReadOptions


def load_metadata(path: Path, expected_name: str) -> DelimitedFileMetadata:
    """Loads and validates the metadata YAML of one flow.

    Example: expected_name 'products_csv' requires 'name: products_csv' in the file.

    Args:
        path: Path of the metadata YAML file.
        expected_name: The flow name the calling script is written for.

    Returns:
        The validated metadata.

    Raises:
        IngestionError: If the file is unreadable, invalid or for another flow.
    """
    try:
        with path.open(encoding="utf-8") as handle:
            content = yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        raise IngestionError(f"Cannot read metadata {path}: {exc}") from exc
    try:
        metadata = DelimitedFileMetadata.model_validate(content)
    except ValidationError as exc:
        raise IngestionError(f"Invalid metadata {path}: {exc}") from exc
    if metadata.name != expected_name:
        raise IngestionError(f"Metadata {path} is {metadata.name}, not {expected_name}")
    return metadata
