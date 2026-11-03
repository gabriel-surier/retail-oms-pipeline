"""
@File    :   test_rop_common.py
@Time    :   2026-11-03
@Author  :   Gabriel SURIER
@Purpose :   Unit tests of the metadata loader and of the delimited file reading
"""

import re
from pathlib import Path
from typing import Final

import pandas as pd
import pytest
from sqlalchemy import Table

from shared.rop_common.rop_db import to_records
from shared.rop_common.rop_delimited_file import (
    build_dtypes,
    derive_int_id,
    load_delimited_file,
    select_columns,
)
from shared.rop_common.rop_errors import IngestionError
from shared.rop_common.rop_metadata import DelimitedFileMetadata, load_metadata
from shared.rop_common.rop_settings import PROJECT_ROOT

# Assume the ERP file has one header line, then one product per line.
PRODUCTS_CSV: Final[str] = (
    "product_cd,category_cd,brand_name,product_name,unit_price_amt,is_active\n"
    'PRD-001,face_care,Acme,"Chair, wood",19.90,true\n'
    "PRD-030,body_care,Acme,Table,89.00,false\n"
)


@pytest.mark.parametrize(
    ("file_name", "flow", "table", "valid_codes", "invalid_codes"),
    [
        (
            "products_csv.yaml",
            "products_csv",
            "oms.product",
            ["PRD-001", "PRD-999"],
            ["PRD-1", "PRD-0001", "PRD-1000", "TRP-001"],
        ),
        (
            "carriers_csv.yaml",
            "carriers_csv",
            "oms.carrier",
            ["TRP-001", "TRP-999"],
            ["TRP-1", "TRP-0001", "TRP-1000", "PRD-001"],
        ),
    ],
)
def test_real_yaml_load(
    file_name: str,
    flow: str,
    table: str,
    valid_codes: list[str],
    invalid_codes: list[str],
) -> None:
    """Checks that a real metadata YAML loads and that its id pattern fits the ERP.

    The ERP sends codes with exactly 3 digits, so the pattern must reject the others.

    Args:
        file_name: The YAML file name in the metadata folder.
        flow: The flow name the YAML must declare.
        table: The target table the YAML must declare.
        valid_codes: Codes the derived id pattern must accept.
        invalid_codes: Codes the derived id pattern must reject.
    """
    metadata = load_metadata(PROJECT_ROOT / "metadata" / file_name, flow)
    pattern = metadata.derived[0].pattern

    assert metadata.table == table
    for code in valid_codes:
        assert re.search(pattern, code), f"{code} should match {pattern}"
    for code in invalid_codes:
        assert re.search(pattern, code) is None, f"{code} should not match {pattern}"


def test_build_dtypes(
    product_metadata: DelimitedFileMetadata, product_table: Table
) -> None:
    """Checks the pandas dtype derived from each SQL type of oms.product.

    Args:
        product_metadata: The products metadata.
        product_table: The in-memory oms.product table.
    """
    dtypes = build_dtypes(product_metadata, product_table)

    assert dtypes == {
        "product_cd": "string",
        "category_cd": "string",
        "brand_name": "string",
        "product_name": "string",
        "unit_price_amt": "float64",
        "is_active": "boolean",
    }


def test_select_columns() -> None:
    """Checks the order and the renaming of the columns, then the two rejections."""
    metadata = DelimitedFileMetadata.model_validate(
        {
            "name": "demo",
            "type": "delimited_file",
            "table": "oms.product",
            "read_options": {
                "delimiter": ",",
                "encoding": "utf-8",
                "text_enclosure": '"',
                "header": True,
            },
            "mapping": [
                {"source": "CODE", "target": "product_cd"},
                {"source": "PRICE", "target": "unit_price_amt"},
            ],
        }
    )
    # The file holds the columns in another order, plus one column not in the mapping.
    frame = pd.DataFrame(
        {"PRICE": [1.5, 2.5], "EXTRA": ["x", "y"], "CODE": ["PRD-001", "PRD-002"]}
    )

    result = select_columns(frame, metadata, "products.csv")

    assert list(result.columns) == ["product_cd", "unit_price_amt"]
    assert result["product_cd"].tolist() == ["PRD-001", "PRD-002"]
    with pytest.raises(IngestionError, match="Missing columns"):
        select_columns(frame.drop(columns="PRICE"), metadata, "products.csv")
    with pytest.raises(IngestionError, match="contains no row"):
        select_columns(frame.iloc[0:0], metadata, "products.csv")


def test_derive_int_id() -> None:
    """Checks that PRD-001 gives 1, PRD-030 gives 30, and a bad code is rejected."""
    pattern = r"^PRD-(\d{3})$"
    frame = pd.DataFrame(
        {"product_cd": pd.array(["PRD-001", "PRD-030"], dtype="string")}
    )

    result = derive_int_id(frame, "product_cd", "product_id", pattern)

    assert result["product_id"].tolist() == [1, 30]
    assert str(result["product_id"].dtype) == "int64"
    # The input frame is not modified, a new frame is returned.
    assert "product_id" not in frame.columns
    bad_frame = pd.DataFrame(
        {"product_cd": pd.array(["PRD-001", "XXX"], dtype="string")}
    )
    with pytest.raises(IngestionError, match="XXX"):
        derive_int_id(bad_frame, "product_cd", "product_id", pattern)


def test_load_delimited_file(
    tmp_path: Path,
    product_metadata: DelimitedFileMetadata,
    product_table: Table,
) -> None:
    """Checks the file reading end to end: quoted comma, dtypes and derived id.

    Args:
        tmp_path: A temporary directory created by pytest.
        product_metadata: The products metadata.
        product_table: The in-memory oms.product table.
    """
    csv_path = tmp_path / "products.csv"
    csv_path.write_text(PRODUCTS_CSV, encoding="utf-8")

    frame = load_delimited_file(csv_path, product_metadata, product_table)

    assert list(frame.columns) == [
        "product_cd",
        "category_cd",
        "brand_name",
        "product_name",
        "unit_price_amt",
        "is_active",
        "product_id",
    ]
    assert frame["product_id"].tolist() == [1, 30]
    # The comma inside the quotes must stay in the name.
    assert frame["product_name"].tolist() == ["Chair, wood", "Table"]
    assert frame["unit_price_amt"].tolist() == [19.9, 89.0]
    assert frame["is_active"].tolist() == [True, False]


def test_to_records() -> None:
    """Checks that pandas missing values become None in the SQL parameters."""
    frame = pd.DataFrame(
        {
            "id": pd.array([1, None], dtype="Int64"),
            "name": pd.array(["a", None], dtype="string"),
            "price": [1.5, float("nan")],
        }
    )

    records = to_records(frame)

    assert records == [
        {"id": 1, "name": "a", "price": 1.5},
        {"id": None, "name": None, "price": None},
    ]
