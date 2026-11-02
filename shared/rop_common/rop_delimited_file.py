"""
@File    :   rop_delimited_file.py
@Time    :   2026-11-02
@Author  :   Gabriel SURIER
@Purpose :   Provides the reading of a delimited file as described by its metadata
"""

import logging
from decimal import Decimal
from pathlib import Path
from typing import Final

import pandas as pd
from sqlalchemy import Table

from shared.rop_common.rop_errors import IngestionError
from shared.rop_common.rop_metadata import DelimitedFileMetadata

logger = logging.getLogger(__name__)

# The column type comes from the DDL, the pandas dtype follows from its python type.
PANDAS_DTYPES: Final[dict[type[object], str]] = {
    int: "Int64",
    float: "float64",
    Decimal: "float64",
    bool: "boolean",
    str: "string",
}


def build_dtypes(metadata: DelimitedFileMetadata, table: Table) -> dict[str, str]:
    """Derives the pandas dtype of every mapped target from the table DDL.

    Example: a target on a numeric(10,2) column gets 'float64', on a boolean
    column 'boolean', on a varchar column 'string'.

    Args:
        metadata: The metadata of the flow.
        table: The reflected target table.

    Returns:
        The pandas dtype of each mapped target column.

    Raises:
        IngestionError: If a target is not in the table or its type is unsupported.
    """
    dtypes: dict[str, str] = {}
    for item in metadata.mapping:
        if item.target not in table.columns:
            raise IngestionError(f"Target {item.target} not in table {table.fullname}")
        try:
            python_type = table.columns[item.target].type.python_type
        except NotImplementedError as exc:
            raise IngestionError(f"Type of {item.target} is unsupported") from exc
        if python_type not in PANDAS_DTYPES:
            raise IngestionError(f"Type of {item.target} is unsupported: {python_type}")
        dtypes[item.target] = PANDAS_DTYPES[python_type]
    return dtypes


def read_frame(
    path: Path, metadata: DelimitedFileMetadata, dtypes: dict[str, str]
) -> pd.DataFrame:
    """Reads the delimited file as described by the read options.

    With a header the columns are named by the file, without it they are taken by
    position and named by the mapping, in file order.

    Args:
        path: Path of the delimited file.
        metadata: The metadata of the flow.
        dtypes: The pandas dtype of every mapped target column.

    Returns:
        The raw frame, typed on the mapped columns.

    Raises:
        IngestionError: If the file cannot be read or decoded.
    """
    options = metadata.read_options
    typed = {item.source: dtypes[item.target] for item in metadata.mapping}
    by_position = {
        position: dtypes[item.target] for position, item in enumerate(metadata.mapping)
    }
    try:
        if options.header:
            return pd.read_csv(
                path,
                sep=options.delimiter,
                quotechar=options.text_enclosure,
                encoding=options.encoding,
                header=0,
                dtype=typed,
            )
        return pd.read_csv(
            path,
            sep=options.delimiter,
            quotechar=options.text_enclosure,
            encoding=options.encoding,
            header=None,
            index_col=False,
            dtype=by_position,
        )
    except (OSError, ValueError, LookupError, pd.errors.ParserError) as exc:
        raise IngestionError(f"Cannot read {path}: {exc}") from exc


def select_columns(
    frame: pd.DataFrame, metadata: DelimitedFileMetadata, file_name: str
) -> pd.DataFrame:
    """Keeps the mapped columns, checks them and renames source to target.

    Args:
        frame: The raw frame returned by read_frame.
        metadata: The metadata of the flow.
        file_name: The file name, used in the error messages.

    Returns:
        A new frame holding the target columns, in mapping order.

    Raises:
        IngestionError: If a mapped column is missing or the file has no row.
    """
    sources = [item.source for item in metadata.mapping]
    if metadata.read_options.header:
        missing = [name for name in sources if name not in frame.columns]
        if missing:
            raise IngestionError(f"Missing columns in {file_name}: {missing}")
        extra = [name for name in frame.columns if name not in sources]
        selected = frame.loc[:, sources]
    else:
        if frame.shape[1] < len(sources):
            raise IngestionError(
                f"{file_name} has {frame.shape[1]} columns, mapping needs {len(sources)}"
            )
        extra = [str(name) for name in frame.columns[len(sources) :]]
        selected = frame.iloc[:, : len(sources)].set_axis(sources, axis=1)
    if extra:
        logger.warning("Columns ignored, not in mapping: %s", extra)
    if selected.empty:
        raise IngestionError(f"{file_name} contains no row")
    renames = {item.source: item.target for item in metadata.mapping}
    return selected.rename(columns=renames).copy()


def derive_int_id(
    frame: pd.DataFrame, code_column: str, id_column: str, pattern: str
) -> pd.DataFrame:
    """Derives an integer id from a prefixed code column.

    Example: with pattern '^PRD-(\\d+)$', 'PRD-001' becomes 1 and 'PRD-030' becomes 30.

    Args:
        frame: The DataFrame holding the code column.
        code_column: The column holding the code, such as product_cd.
        id_column: The name of the id column to append.
        pattern: A regex with exactly one capture group, the numeric part of the code.

    Returns:
        A new DataFrame with the int64 id column appended.

    Raises:
        IngestionError: If a code does not match the pattern.
    """
    extracted = frame[code_column].str.extract(pattern).iloc[:, 0]
    if extracted.isna().any():
        invalid = frame.loc[extracted.isna(), code_column].tolist()
        raise IngestionError(f"{code_column} not matching {pattern}: {invalid}")
    # Convert to int64 to drop the leading zeros and match an int4 column.
    return frame.assign(**{id_column: pd.to_numeric(extracted).astype("int64")})


def load_delimited_file(
    path: Path, metadata: DelimitedFileMetadata, table: Table
) -> pd.DataFrame:
    """Reads a delimited file into a frame keyed by the table column names.

    Example: with the products metadata, 'PRD-001,...' gives product_cd 'PRD-001'
    and product_id 1.

    Args:
        path: Path of the delimited file.
        metadata: The metadata of the flow.
        table: The reflected target table, source of the column types.

    Returns:
        The mapped columns, then the derived columns.
    """
    dtypes = build_dtypes(metadata, table)
    frame = select_columns(read_frame(path, metadata, dtypes), metadata, path.name)
    logger.info("File read source=%s rows=%d", path, len(frame))
    renames = {item.source: item.target for item in metadata.mapping}
    for item in metadata.derived:
        frame = derive_int_id(frame, renames[item.source], item.target, item.pattern)
    return frame
