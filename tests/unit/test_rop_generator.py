"""
@File    :   test_rop_generator.py
@Time    :   2026-11-03
@Author  :   Gabriel SURIER
@Purpose :   Unit tests of the OMS simulator: reproducibility, invariants, calibration.
"""

import csv
import json
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Final

import pytest


from shared.generator.rop_generator import (
    CARRIER_CODES,
    Carrier,
    Catalog,
    GeneratorError,
    LineChanged,
    OrderCreated,
    Product,
    StatusChanged,
    build_json_schema,
    generate_events,
)

DATA_DIR: Final[Path] = Path(__file__).resolve().parents[2] / "data"
print(f"DATA_DIR: {DATA_DIR}")
SEED: Final[int] = 20260101
INIT_DATE: Final[date] = date(2026, 1, 1)
START: Final[datetime] = datetime(2025, 12, 31, 23, 0)
DAYS: Final[int] = 120
# Late rate targets by carrier code, with a wide tolerance in points.
LATE_TARGETS: Final[dict[str, float]] = {
    "TRP-001": 7.0,
    "TRP-002": 11.0,
    "TRP-003": 28.0,
    "TRP-004": 16.0,
}
LATE_TOLERANCE: Final[float] = 4.0


@pytest.fixture(name="catalog", scope="module")
def fixture_catalog() -> Catalog:
    """Builds the catalog from the reference CSV files of the repository.

    Returns:
        The 30 products and the 4 carriers of the CSV files.
    """
    with (DATA_DIR / "products.csv").open(encoding="utf-8", newline="") as handle:
        products = tuple(
            Product(row["product_cd"], Decimal(row["unit_price_amt"]))
            for row in csv.DictReader(handle)
        )
    with (DATA_DIR / "carriers.csv").open(encoding="utf-8", newline="") as handle:
        carriers = tuple(
            Carrier(row["carrier_cd"], int(row["promised_days_num"]))
            for row in csv.DictReader(handle)
        )
    return Catalog(products, carriers)


@pytest.fixture(name="events", scope="module")
def fixture_events(
    catalog: Catalog,
) -> list[OrderCreated | StatusChanged | LineChanged]:
    """Generates the events of the first 120 days, once for the whole module.

    Args:
        catalog: The catalog built from the CSV files.

    Returns:
        The sorted events of the window.
    """
    end = START + timedelta(days=DAYS)
    return generate_events(START, end, catalog, SEED, INIT_DATE)


def _status_dates(
    events: list[OrderCreated | StatusChanged | LineChanged],
) -> dict[str, dict[str, datetime]]:
    """Groups the status dates of each order, keyed by order code then status.

    Args:
        events: The events to group.

    Returns:
        For example {'CMD-0000100001': {'created': ..., 'paid': ...}}.
    """
    dates: dict[str, dict[str, datetime]] = {}
    for event in events:
        if isinstance(event, (OrderCreated, StatusChanged)):
            status = event.status_event
            dates.setdefault(status.order_cd, {})[status.status_cd] = status.event_ts
    return dates


def test_same_seed_gives_same_events(catalog: Catalog) -> None:
    """Checks that two runs with the same inputs give the same events.

    Args:
        catalog: The catalog built from the CSV files.
    """
    end = START + timedelta(days=3)
    first = generate_events(START, end, catalog, SEED, INIT_DATE)
    assert first
    assert first == generate_events(START, end, catalog, SEED, INIT_DATE)
    assert first != generate_events(START, end, catalog, SEED + 1, INIT_DATE)


def test_window_is_computed_alone(
    catalog: Catalog, events: list[OrderCreated | StatusChanged | LineChanged]
) -> None:
    """Checks that a narrow window equals the same slice of a long window.

    Args:
        catalog: The catalog built from the CSV files.
        events: The events of the first 120 days.
    """
    begin = datetime(2026, 2, 10, 8, 0)
    end = datetime(2026, 2, 10, 14, 0)
    alone = generate_events(begin, end, catalog, SEED, INIT_DATE)
    assert alone
    assert alone == [item for item in events if begin <= item.event_ts < end]


def test_codes_and_lines_are_valid(
    events: list[OrderCreated | StatusChanged | LineChanged],
) -> None:
    """Checks unique codes, quantities and the carrier of every order.

    Args:
        events: The events of the first 120 days.
    """
    created = [item for item in events if isinstance(item, OrderCreated)]
    status_codes = [
        item.status_event.event_cd
        for item in events
        if isinstance(item, (OrderCreated, StatusChanged))
    ]
    line_codes = [line.line_cd for item in created for line in item.lines]
    assert len(status_codes) == len(set(status_codes))
    assert len(line_codes) == len(set(line_codes))
    assert all(line.quantity_num >= 1 for item in created for line in item.lines)
    assert all(item.order.carrier_cd in CARRIER_CODES for item in created)
    assert all(item.lines for item in created)


def test_status_order_is_respected(
    events: list[OrderCreated | StatusChanged | LineChanged],
) -> None:
    """Checks the lifecycle: no event after a terminal status, except returned.

    Args:
        events: The events of the first 120 days.
    """
    for dates in _status_dates(events).values():
        assert "created" in dates
        if "returned" in dates:
            assert dates["delivered"] < dates["returned"]
        if "cancelled" in dates:
            assert "shipped" not in dates
            assert "delivered" not in dates
        if "delivered" in dates:
            assert dates["created"] <= dates["paid"] <= dates["shipped"]
            assert dates["shipped"] <= dates["delivered"]


def test_line_changes_happen_before_shipping(
    events: list[OrderCreated | StatusChanged | LineChanged],
) -> None:
    """Checks that line changes come after creation and before shipping.

    Args:
        events: The events of the first 120 days.
    """
    dates = _status_dates(events)
    changes = [item for item in events if isinstance(item, LineChanged)]
    assert changes
    for change in changes:
        order = dates[change.line.order_cd]
        assert "cancelled" not in order
        assert order["created"] <= change.event_ts
        # The shipping may fall after the end of the window, then it is unknown.
        assert change.event_ts <= order.get("shipped", change.event_ts)
        assert change.line.updated_ts == change.event_ts


def test_calibration_is_close_to_the_targets(
    catalog: Catalog, events: list[OrderCreated | StatusChanged | LineChanged]
) -> None:
    """Checks volume, cancellations, returns and late rates, with a wide tolerance.

    Args:
        catalog: The catalog built from the CSV files.
        events: The events of the first 120 days.
    """
    created = [item for item in events if isinstance(item, OrderCreated)]
    dates = _status_dates(events)
    promised = {item.carrier_cd: item.promised_days_num for item in catalog.carriers}
    assert 90 <= len(created) / DAYS <= 110
    # Orders of the first 90 days only, so that their lifecycle is complete.
    early = [item for item in created if item.event_ts < START + timedelta(days=90)]
    cancelled = sum("cancelled" in dates[item.order.order_cd] for item in early)
    assert abs(100 * cancelled / len(early) - 4.5) < 1.5
    delivered = [item for item in early if "delivered" in dates[item.order.order_cd]]
    returned = sum("returned" in dates[item.order.order_cd] for item in delivered)
    assert abs(100 * returned / len(delivered) - 6.0) < 2.0
    for code, target in LATE_TARGETS.items():
        own = [item for item in delivered if item.order.carrier_cd == code]
        limit = timedelta(days=promised[code])
        late = sum(
            dates[item.order.order_cd]["delivered"] - item.event_ts > limit
            for item in own
        )
        assert abs(100 * late / len(own) - target) < LATE_TOLERANCE


def test_invalid_inputs_are_rejected(catalog: Catalog) -> None:
    """Checks the boundary errors: missing carrier and timezone aware window.

    Args:
        catalog: The catalog built from the CSV files.
    """
    broken = Catalog(catalog.products, catalog.carriers[:3])
    with pytest.raises(GeneratorError):
        generate_events(START, START + timedelta(days=1), broken, SEED, INIT_DATE)
    aware = START.astimezone()
    with pytest.raises(GeneratorError):
        generate_events(aware, START + timedelta(days=1), catalog, SEED, INIT_DATE)


def test_json_schema_lists_the_ddl_columns() -> None:
    """Checks that the JSON schema carries the OLTP columns and no delivery number."""
    schema = json.dumps(build_json_schema(), default=str)
    assert all(
        column in schema for column in ("customer_cd", "carrier_cd", "deleted_ts")
    )
    assert "delivery_num" not in schema
