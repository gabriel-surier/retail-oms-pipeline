"""
@File    :   rop_fl001_0100_csv_erp_product.py
@Time    :   2026-10-29
@Author  :   Gabriel SURIER
@Purpose :   Ingest the ERP products CSV file into the oms.product PostgreSQL table.

@Description :

Reads products.csv with pandas, validates its columns, derives the integer product_id
from product_cd (PRD-001 becomes 1), adds the audit timestamps created_ts and
updated_ts, and upserts the rows into ``oms.product`` through SQLAlchemy
(INSERT ... ON CONFLICT DO UPDATE). Both timestamps are computed once at the start of
the job, so every row of a run shares the same value. On conflict, created_ts is kept
and updated_ts is refreshed. The whole load runs in one transaction.

The table oms.product must already exist with a primary key on product_id (int4).
Extra dependency outside the declared stack: psycopg[binary] (PostgreSQL driver).
Settings come from src.rop_config.Settings (env variables or .env file).

"""

import logging
import sys
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Final

import pandas as pd
from pydantic import ValidationError
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.sql.elements import TextClause

from src.rop_config import (
    IngestionError,
    Settings,
    build_engine,
    derive_int_id,
    read_csv_typed,
    to_records,
)

logger = logging.getLogger(__name__)

PRODUCT_DTYPES: Final[dict[str, str]] = {
    "product_cd": "string",
    "category_cd": "string",
    "brand_name": "string",
    "product_name": "string",
    "unit_price_amt": "float64",
    "is_active": "boolean",
}
# ASSUMPTION: product_cd always looks like PRD-001; the number after 'PRD-' is kept.
PRODUCT_CD_PATTERN: Final[str] = r"^PRD-(\d+)$"
# created_ts is deliberately absent from the DO UPDATE part: it never changes.
UPSERT_SQL: Final[TextClause] = text("""
    INSERT INTO oms.product (
        product_id, product_cd, category_cd, brand_name, product_name,
        unit_price_amt, is_active, created_ts, updated_ts
    ) VALUES (
        :product_id, :product_cd, :category_cd, :brand_name, :product_name,
        :unit_price_amt, :is_active, :created_ts, :updated_ts
    )
    ON CONFLICT (product_id) DO UPDATE SET
        product_cd = EXCLUDED.product_cd,
        category_cd = EXCLUDED.category_cd,
        brand_name = EXCLUDED.brand_name,
        product_name = EXCLUDED.product_name,
        unit_price_amt = EXCLUDED.unit_price_amt,
        is_active = EXCLUDED.is_active,
        updated_ts = EXCLUDED.updated_ts
    """)


def load_products(settings: Settings) -> pd.DataFrame:
    """Reads products.csv and derives the integer product_id.

    Example: product_cd 'PRD-001' gives product_id 1.

    Args:
        settings: The application settings holding the products file path.

    Returns:
        The products with product_id appended.
    """
    frame = read_csv_typed(settings.rop_products_csv_path, PRODUCT_DTYPES)
    return derive_int_id(frame, "product_cd", "product_id", PRODUCT_CD_PATTERN)


def upsert_products(frame: pd.DataFrame, engine: Engine) -> int:
    """Upserts the products into oms.product in one transaction.

    Args:
        frame: The products, including product_id, created_ts and updated_ts.
        engine: The SQLAlchemy engine.

    Returns:
        The number of rows sent to the upsert.
    """
    with engine.begin() as connection:
        connection.execute(UPSERT_SQL, to_records(frame))
    return len(frame)


def main() -> int:
    """Runs the products ingestion and logs the outcome.

    Returns:
        0 when the ingestion succeeds, 1 when it fails.
    """
    settings = Settings()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(module)s %(message)s",
    )
    # Compute the timestamp once so every row of this run shares the same value.
    # ASSUMPTION: the audit columns are timestamp without time zone, so store naive UTC.
    job_ts = datetime.now(ZoneInfo(settings.rop_timezone)).isoformat()
    logger.info("START ingestion table=oms.product job_ts=%s", job_ts)
    try:

        frame = load_products(settings).assign(created_ts=job_ts, updated_ts=job_ts)
        upserted = upsert_products(frame, build_engine(settings))
    except (IngestionError, SQLAlchemyError, ValidationError):
        logger.exception("FAIL ingestion table=oms.product")
        return 1
    logger.info("OK ingestion table=oms.product rows_upserted=%d", upserted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
