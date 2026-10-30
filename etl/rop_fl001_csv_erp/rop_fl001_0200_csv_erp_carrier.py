"""
@File    :   rop_fl001_0200_csv_erp_carrier
@Time    :   2026-10-29
@Author  :   Gabriel SURIER
@Purpose : Ingest the ERP carriers file into the oms.carrier PostgreSQL table.

@Description :

Reads carriers.csv with pandas, validates its columns, derives the integer carrier_id
from carrier_cd (TRP-001 becomes 1), adds the audit timestamps created_ts and
updated_ts, and upserts the rows into ``oms.carrier`` through SQLAlchemy
(INSERT ... ON CONFLICT DO UPDATE). Both timestamps are computed once at the start of
the job, so every row of a run shares the same value. On conflict, created_ts is kept
and updated_ts is refreshed. The whole load runs in one transaction.

The table oms.carrier must already exist with a primary key on carrier_id (int4).
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

CARRIER_DTYPES: Final[dict[str, str]] = {
    "carrier_cd": "string",
    "carrier_name": "string",
    "service_cd": "string",
    "promised_days_num": "Int64",
    "is_active": "boolean",
}
# ASSUMPTION: carrier_cd always looks like TRP-001; the number after 'TRP-' is kept.
CARRIER_CD_PATTERN: Final[str] = r"^TRP-(\d+)$"
# created_ts is deliberately absent from the DO UPDATE part: it never changes.
UPSERT_SQL: Final[TextClause] = text("""
    INSERT INTO oms.carrier (
        carrier_id, carrier_cd, carrier_name, service_cd,
        promised_days_num, is_active, created_ts, updated_ts
    ) VALUES (
        :carrier_id, :carrier_cd, :carrier_name, :service_cd,
        :promised_days_num, :is_active, :created_ts, :updated_ts
    )
    ON CONFLICT (carrier_id) DO UPDATE SET
        carrier_cd = EXCLUDED.carrier_cd,
        carrier_name = EXCLUDED.carrier_name,
        service_cd = EXCLUDED.service_cd,
        promised_days_num = EXCLUDED.promised_days_num,
        is_active = EXCLUDED.is_active,
        updated_ts = EXCLUDED.updated_ts
    """)


def load_carriers(settings: Settings) -> pd.DataFrame:
    """Reads carriers.csv and derives the integer carrier_id.

    Example: carrier_cd 'TRP-001' gives carrier_id 1.

    Args:
        settings: The application settings holding the carriers file path.

    Returns:
        The carriers with carrier_id appended.
    """
    frame = read_csv_typed(settings.rop_carriers_file_path, CARRIER_DTYPES)
    return derive_int_id(frame, "carrier_cd", "carrier_id", CARRIER_CD_PATTERN)


def upsert_carriers(frame: pd.DataFrame, engine: Engine) -> int:
    """Upserts the carriers into oms.carrier in one transaction.

    Args:
        frame: The carriers, including carrier_id, created_ts and updated_ts.
        engine: The SQLAlchemy engine.

    Returns:
        The number of rows sent to the upsert.
    """
    with engine.begin() as connection:
        connection.execute(UPSERT_SQL, to_records(frame))
    return len(frame)


def main() -> int:
    """Runs the carriers ingestion and logs the outcome.

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
    logger.info("START ingestion table=oms.carrier job_ts=%s", job_ts)
    try:

        frame = load_carriers(settings).assign(created_ts=job_ts, updated_ts=job_ts)
        upserted = upsert_carriers(frame, build_engine(settings))
    except (IngestionError, SQLAlchemyError, ValidationError):
        logger.exception("FAIL ingestion table=oms.carrier")
        return 1
    logger.info("OK ingestion table=oms.carrier rows_upserted=%d", upserted)
    return 0


if __name__ == "__main__":
    sys.exit(main())
