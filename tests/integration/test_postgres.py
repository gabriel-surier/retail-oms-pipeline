"""
@File    :   test_postgres.py
@Time    :   2026-11-03
@Author  :   Gabriel SURIER
@Purpose :   Integration tests on a real PostgreSQL: YAML against DDL, upsert, workflows
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Final

import pandas as pd
import pytest
from sqlalchemy import Engine, func, select

from etl.rop_fl001_csv_erp import (
    rop_fl001_0100_csv_erp_product,
    rop_fl001_0200_csv_erp_carrier,
)
from shared.rop_common.rop_db import reflect_table, upsert_frame
from shared.rop_common.rop_delimited_file import build_dtypes
from shared.rop_common.rop_metadata import load_metadata
from shared.rop_common.rop_settings import PROJECT_ROOT

# The ids 998 and 999 are reserved for these tests, see RESERVED_IDS in conftest.py.
TEST_IDS: Final[list[int]] = [998, 999]

# Settings of the oms simulation, required by the workflows but unused by the tests.
OMS_ENV: Final[dict[str, str]] = {
    "ROP_LOAD_MOD": "DELTA",
    "ROP_DELTA_DAYS": "1",
    "ROP_INIT_DATE": "2026-01-01",
    "ROP_REPLAY_SPEED": "1",
    "ROP_SEED": "42",
    "ROP_TIMEZONE": "Europe/Paris",
}

PRODUCTS_CSV: Final[str] = (
    "product_cd,category_cd,brand_name,product_name,unit_price_amt,is_active\n"
    'PRD-998,face_care,Acme,"Chair, wood",19.90,true\n'
    "PRD-999,body_care,Acme,Table,89.00,false\n"
)
CARRIERS_CSV: Final[str] = (
    "carrier_cd,carrier_name,service_cd,promised_days_num,is_active\n"
    "TRP-998,Fast Co,express,2,TRUE\n"
    "TRP-999,Slow Co,standard,5,FALSE\n"
)


@dataclass(slots=True, frozen=True)
class WorkflowCase:
    """One workflow to run end to end, grouped to keep the test signature short.

    Attributes:
        main: The main function of the workflow.
        path_variable: The environment variable holding the CSV path.
        csv_content: The content of the CSV file to ingest.
        table_name: The target table as schema.table.
        key_column: The primary key column of the target table.
    """

    main: Callable[[], int]
    path_variable: str
    csv_content: str
    table_name: str
    key_column: str


@pytest.mark.parametrize(
    ("file_name", "flow"),
    [("products_csv.yaml", "products_csv"), ("carriers_csv.yaml", "carriers_csv")],
)
def test_yaml_matches_ddl(clean_engine: Engine, file_name: str, flow: str) -> None:
    """Checks that every column named by a YAML exists in the real table.

    Args:
        clean_engine: An engine on the test database.
        file_name: The YAML file name in the metadata folder.
        flow: The flow name the YAML must declare.
    """
    metadata = load_metadata(PROJECT_ROOT / "metadata" / file_name, flow)
    table = reflect_table(clean_engine, metadata.table)

    # Raises if a mapped target is missing from the table or has an unsupported type.
    build_dtypes(metadata, table)

    # The workflow adds the audit columns, the derived targets come from the YAML.
    expected = [item.target for item in metadata.derived] + ["created_ts", "updated_ts"]
    missing = [name for name in expected if name not in table.columns]
    assert not missing, f"Columns missing in {metadata.table}: {missing}"


def test_upsert_idempotent(clean_engine: Engine) -> None:
    """Checks that a second upsert updates the rows and keeps created_ts.

    Args:
        clean_engine: An engine on the test database.
    """
    table = reflect_table(clean_engine, "oms.product")
    first_ts = datetime(2026, 1, 1, 8, 0, 0)
    second_ts = datetime(2026, 1, 2, 8, 0, 0)
    first_run = pd.DataFrame(
        {
            "product_id": TEST_IDS,
            "product_cd": ["PRD-998", "PRD-999"],
            "unit_price_amt": [10.0, 20.0],
            "created_ts": [first_ts, first_ts],
            "updated_ts": [first_ts, first_ts],
        }
    )
    second_run = first_run.assign(
        unit_price_amt=[11.0, 21.0],
        created_ts=[second_ts, second_ts],
        updated_ts=[second_ts, second_ts],
    )

    upsert_frame(first_run, clean_engine, table)
    upserted = upsert_frame(second_run, clean_engine, table)

    statement = (
        select(
            table.c.created_ts,
            table.c.updated_ts,
            table.c.unit_price_amt,
        )
        .where(table.c.product_id.in_(TEST_IDS))
        .order_by(table.c.product_id)
    )
    with clean_engine.connect() as connection:
        rows = connection.execute(statement).all()
    assert upserted == 2
    # Two runs on the same keys must not create duplicates.
    assert len(rows) == 2
    # created_ts is never refreshed, updated_ts and the price are.
    assert [row.created_ts for row in rows] == [first_ts, first_ts]
    assert [row.updated_ts for row in rows] == [second_ts, second_ts]
    assert [row.unit_price_amt for row in rows] == [Decimal("11.00"), Decimal("21.00")]


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            WorkflowCase(
                rop_fl001_0100_csv_erp_product.main,
                "ROP_PRODUCTS_CSV_PATH",
                PRODUCTS_CSV,
                "oms.product",
                "product_id",
            ),
            id="products",
        ),
        pytest.param(
            WorkflowCase(
                rop_fl001_0200_csv_erp_carrier.main,
                "ROP_CARRIERS_FILE_PATH",
                CARRIERS_CSV,
                "oms.carrier",
                "carrier_id",
            ),
            id="carriers",
        ),
    ],
)
def test_workflow_end_to_end(
    case: WorkflowCase,
    clean_engine: Engine,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Checks that a workflow reads a CSV and loads its rows in PostgreSQL.

    Args:
        case: The workflow to run and its input.
        clean_engine: An engine on the test database.
        tmp_path: A temporary directory created by pytest.
        monkeypatch: The pytest fixture used to set the environment variables.
    """
    csv_path = tmp_path / "input.csv"
    csv_path.write_text(case.csv_content, encoding="utf-8")
    monkeypatch.setenv(case.path_variable, str(csv_path))
    for key, value in OMS_ENV.items():
        monkeypatch.setenv(key, value)

    exit_code = case.main()

    table = reflect_table(clean_engine, case.table_name)
    statement = (
        select(func.count())
        .select_from(table)
        .where(table.c[case.key_column].in_(TEST_IDS))
    )
    with clean_engine.connect() as connection:
        loaded = connection.execute(statement).scalar_one()
    assert exit_code == 0
    assert loaded == 2
