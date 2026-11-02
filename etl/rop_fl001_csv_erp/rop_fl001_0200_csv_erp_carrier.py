"""
@File    :   rop_fl001_0200_csv_erp_carrier
@Time    :   2026-10-29
@Author  :   Gabriel SURIER
@Purpose : Ingest the ERP carriers file into the oms.carrier PostgreSQL table.
"""

import logging
import sys
from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from shared.rop_common.rop_db import build_engine, reflect_table, upsert_frame
from shared.rop_common.rop_delimited_file import load_delimited_file
from shared.rop_common.rop_errors import IngestionError
from shared.rop_common.rop_logging import configure_logging
from shared.rop_common.rop_metadata import load_metadata
from shared.rop_common.rop_settings import DatabaseSettings, FileSettings, OmsSettings

logger = logging.getLogger(__name__)

FLOW_NAME: Final[str] = "carriers_csv"


def main() -> int:
    """Runs the carriers ingestion and logs the outcome.

    Returns:
        0 when the ingestion succeeds, 1 when it fails.
    """
    configure_logging()
    oms_settings = OmsSettings()
    # Compute the timestamp once so every row of this run shares the same value.
    # ASSUMPTION: the audit columns are timestamp with time zone Paris.
    job_ts = datetime.now(ZoneInfo(oms_settings.rop_timezone)).replace(tzinfo=None)
    logger.info("START ingestion flow=%s job_ts=%s", FLOW_NAME, job_ts.isoformat())
    try:
        files = FileSettings()
        metadata = load_metadata(files.rop_carriers_metadata_path, FLOW_NAME)
        engine = build_engine(DatabaseSettings())
        table = reflect_table(engine, metadata.table)
        frame = load_delimited_file(
            files.rop_carriers_file_path, metadata, table
        ).assign(created_ts=job_ts, updated_ts=job_ts)
        upserted = upsert_frame(frame, engine, table)
    except (IngestionError, SQLAlchemyError, ValidationError):
        logger.exception("FAIL ingestion flow=%s", FLOW_NAME)
        return 1
    logger.info(
        "OK ingestion flow=%s table=%s rows_upserted=%d",
        FLOW_NAME,
        metadata.table,
        upserted,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
