"""
@File    :   conftest.py
@Time    :   2026-11-03
@Author  :   Gabriel SURIER
@Purpose :   Provides the shared pytest fixtures: in-memory table, metadata, PostgreSQL
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Engine,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    bindparam,
    text,
)

from shared.rop_common.rop_db import build_engine
from shared.rop_common.rop_metadata import DelimitedFileMetadata
from shared.rop_common.rop_settings import DatabaseSettings

# The ids 998 and 999 are reserved for the integration tests, see TEST_IDS there.
RESERVED_IDS = [998, 999]


@pytest.fixture(name="product_table")
def fixture_product_table() -> Table:
    """Builds an in-memory oms.product table with the types of the DDL.

    Returns:
        A table that needs no database connection.
    """
    return Table(
        "product",
        MetaData(),
        Column("product_id", Integer, primary_key=True),
        Column("product_cd", String(20), nullable=False),
        Column("category_cd", String(50)),
        Column("brand_name", String(50)),
        Column("product_name", String(120)),
        Column("unit_price_amt", Numeric(10, 2)),
        Column("is_active", Boolean),
        Column("created_ts", DateTime),
        Column("updated_ts", DateTime),
        schema="oms",
    )


@pytest.fixture(name="product_metadata")
def fixture_product_metadata() -> DelimitedFileMetadata:
    """Builds the products metadata, same mapping as metadata/products_csv.yaml.

    Returns:
        The validated metadata of the products flow.
    """
    return DelimitedFileMetadata.model_validate(
        {
            "name": "products_csv",
            "type": "delimited_file",
            "table": "oms.product",
            "read_options": {
                "delimiter": ",",
                "encoding": "utf-8",
                "text_enclosure": '"',
                "header": True,
            },
            "mapping": [
                {"source": "product_cd", "target": "product_cd"},
                {"source": "category_cd", "target": "category_cd"},
                {"source": "brand_name", "target": "brand_name"},
                {"source": "product_name", "target": "product_name"},
                {"source": "unit_price_amt", "target": "unit_price_amt"},
                {"source": "is_active", "target": "is_active"},
            ],
            "derived": [
                {
                    "source": "product_cd",
                    "target": "product_id",
                    "pattern": r"^PRD-(\d{3})$",
                }
            ],
        }
    )


def delete_reserved_rows(engine: Engine) -> None:
    """Deletes the product and carrier rows that use the reserved test ids.

    Args:
        engine: The SQLAlchemy engine bound to the test database.
    """
    statements = (
        text("DELETE FROM oms.product WHERE product_id IN :ids"),
        text("DELETE FROM oms.carrier WHERE carrier_id IN :ids"),
    )
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(
                statement.bindparams(bindparam("ids", expanding=True)),
                {"ids": RESERVED_IDS},
            )


@pytest.fixture(name="clean_engine")
def fixture_clean_engine() -> Iterator[Engine]:
    """Yields an engine on the test database, with the reserved test rows removed.

    Only the rows with the reserved ids are deleted, before and after the test, so
    the other rows of a development database are never touched.
    The connection settings come from the ROP_POSTGRES_* variables.

    Yields:
        An engine bound to the PostgreSQL database.
    """
    engine = build_engine(DatabaseSettings())
    delete_reserved_rows(engine)
    yield engine
    delete_reserved_rows(engine)
    engine.dispose()
