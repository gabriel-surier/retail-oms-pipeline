"""
@File    :   rop_config.py
@Time    :   2026-10-26
@Author  :   Gabriel SURIER
@Purpose :   Provides application settings
"""

import logging
from collections.abc import Mapping
from datetime import date
from pathlib import Path

import pandas as pd
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine, create_engine
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file.

    Values are validated by pydantic at import time; missing required
    fields raise at startup rather than failing later mid-pipeline.
    """

    # --- Environment path config ---

    project_root: Path = Path(__file__).resolve().parent.parent
    model_config = SettingsConfigDict(env_file=project_root / ".env")

    # --- Python config ---
    python_version: str
    airflow_python_version: str
    # --- referential csv --

    rop_products_csv_path: Path = project_root / "data" / "products.csv"
    rop_carriers_file_path: Path = project_root / "data" / "carriers.csv"

    # --- oms config ---

    rop_load_mod: str
    rop_delta_days: int
    rop_init_date: date
    rop_replay_speed: int
    rop_seed: int

    # --- PostgreSQL config ---

    rop_postgres_host: str
    rop_postgres_user: str
    rop_postgres_password: str
    rop_postgres_db: str
    rop_postgres_port: int

    # --- Main job config ---

    rop_stop_on_error: bool

    # --- Time config --
    rop_timezone: str

    # --- Airflow config --
    airflow_version: str
    airflow_port: int
    airflow_user: str
    airflow_admin_user: str
    airflow_admin_email: str
    airflow_jwt_secret: str
    airflow_uid: int


logger = logging.getLogger(__name__)


class IngestionError(Exception):
    """Base exception for every business error raised by the ingestion jobs."""


def build_engine(settings: Settings) -> Engine:
    """Builds the SQLAlchemy engine.

    Args:
        settings: The application settings holding the PostgreSQL credentials.

    Returns:
        A SQLAlchemy engine bound to the target database.
    """
    url = URL.create(
        drivername="postgresql+psycopg",
        username=settings.rop_postgres_user,
        password=settings.rop_postgres_password,
        host=settings.rop_postgres_host,
        port=settings.rop_postgres_port,
        database=settings.rop_postgres_db,
    )
    return create_engine(url, pool_pre_ping=True)


def read_csv_typed(path: Path, dtypes: Mapping[str, str]) -> pd.DataFrame:
    """Reads a CSV file and keeps only the columns named in ``dtypes``.

    Example: dtypes {'carrier_cd': 'string'} returns a frame with one string column.

    Args:
        path: Path of the CSV file.
        dtypes: The expected columns, mapped to their pandas dtype.

    Returns:
        The typed columns, in the order of ``dtypes``.

    Raises:
        IngestionError: If the file cannot be read, has no row, or misses a column.
    """
    # Assume the file is UTF-8, comma separated, with a header naming every dtypes key.
    try:
        frame = pd.read_csv(path, sep=",", encoding="utf-8", dtype=dict(dtypes))
    except (OSError, ValueError, pd.errors.ParserError) as exc:
        raise IngestionError(f"Cannot read {path}: {exc}") from exc
    missing = [name for name in dtypes if name not in frame.columns]
    if missing:
        raise IngestionError(f"Missing columns in {path.name}: {missing}")
    if frame.empty:
        raise IngestionError(f"{path.name} contains no row")
    logger.info("File read source=%s rows=%d", path, len(frame))
    return frame.loc[:, list(dtypes)].copy()


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


def to_records(frame: pd.DataFrame) -> list[dict[str, object]]:
    """Turns a frame into SQL parameters, with None instead of missing values.

    Example: a row (1, pd.NA) becomes {'id': 1, 'name': None}.

    Args:
        frame: The DataFrame to convert.

    Returns:
        One dict per row, keyed by column name.
    """
    clean = frame.astype(object).where(frame.notna(), None)
    return [
        {str(key): value for key, value in row.items()}
        for row in clean.to_dict("records")
    ]
