"""
@File    :   rop_db.py
@Time    :   2026-11-02
@Author  :   Gabriel SURIER
@Purpose :   Provides the SQLAlchemy engine, table reflection and upsert helpers
"""

from typing import Final

import pandas as pd
from sqlalchemy import Engine, MetaData, Table, create_engine
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import URL
from sqlalchemy.exc import NoSuchTableError

from shared.rop_common.rop_errors import IngestionError
from shared.rop_common.rop_settings import DatabaseSettings

# ASSUMPTION: DatabaseSettings has no host field, so PostgreSQL is reached on localhost.
POSTGRES_HOST: Final[str] = "localhost"
# created_ts is set at the first insert and must never change on conflict.
CREATED_TS: Final[str] = "created_ts"


def build_engine(settings: DatabaseSettings) -> Engine:
    """Builds the SQLAlchemy engine.

    Args:
        settings: The PostgreSQL credentials.

    Returns:
        A SQLAlchemy engine bound to the target database.
    """
    url = URL.create(
        drivername=settings.rop_postgres_driver,
        username=settings.rop_postgres_user,
        password=settings.rop_postgres_password,
        host=POSTGRES_HOST,
        port=settings.rop_postgres_port,
        database=settings.rop_postgres_db,
    )
    return create_engine(url, pool_pre_ping=True)


def reflect_table(engine: Engine, qualified_name: str) -> Table:
    """Reflects an existing table with SQLAlchemy MetaData.

    The table is created beforehand by the init .sql scripts.
    Example: 'oms.product' gives the table 'product' of the schema 'oms'.

    Args:
        engine: The SQLAlchemy engine bound to the database.
        qualified_name: The table name as schema.table, or table alone.

    Returns:
        The reflected table, with its columns, types and primary key.

    Raises:
        IngestionError: If the table does not exist in the database.
    """
    schema, _, name = qualified_name.rpartition(".")
    try:
        return Table(name, MetaData(), schema=schema or None, autoload_with=engine)
    except NoSuchTableError as exc:
        raise IngestionError(
            f"Table {qualified_name} not found, run the init .sql scripts"
        ) from exc


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


def upsert_frame(frame: pd.DataFrame, engine: Engine, table: Table) -> int:
    """Upserts the frame into a reflected table, in one transaction.

    The conflict key is the primary key of the table. On conflict every column of
    the frame is refreshed, except the key and created_ts.
    Example: columns product_id, product_cd, created_ts, updated_ts on a table keyed
    by product_id refresh product_cd and updated_ts only.

    Args:
        frame: The rows to upsert, with column names matching the table columns.
        engine: The SQLAlchemy engine bound to the database.
        table: The reflected target table.

    Returns:
        The number of rows sent to the upsert.

    Raises:
        IngestionError: If a frame column is not in the table, or it has no key.
    """
    columns = [str(name) for name in frame.columns]
    unknown = [name for name in columns if name not in table.columns]
    if unknown:
        raise IngestionError(f"Columns missing in table {table.fullname}: {unknown}")
    keys = [column.name for column in table.primary_key.columns]
    if not keys:
        raise IngestionError(f"Table {table.fullname} has no primary key")
    refreshed = [name for name in columns if name not in (*keys, CREATED_TS)]
    statement = insert(table)
    statement = statement.on_conflict_do_update(
        index_elements=keys,
        set_={name: statement.excluded[name] for name in refreshed},
    )
    with engine.begin() as connection:
        connection.execute(statement, to_records(frame))
    return len(frame)
