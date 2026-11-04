"""
@File    :   rop_generator.py
@Time    :   2026-11-03
@Author  :   Gabriel SURIER
@Purpose :   Simulate the OMS activity of a time window in memory, driven by a seed.

Every day is drawn from its own generator, so the same seed always gives the same
history. The events of a window are the ones of the full history that fall inside it.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from operator import attrgetter
from typing import Final, Literal
from zoneinfo import ZoneInfo

import numpy as np
from numpy.typing import NDArray
from pydantic import BaseModel, ConfigDict, TypeAdapter
from sqlalchemy import Engine, text
from sqlalchemy.exc import SQLAlchemyError

from shared.rop_common.rop_errors import IngestionError

logger = logging.getLogger(__name__)

# ASSUMPTION: the creation hours are drawn in Paris time, as decided on 2026-10-28.
PARIS: Final[ZoneInfo] = ZoneInfo("Europe/Paris")

# Carriers are keyed by code, the names stay in the PostgreSQL table.
CARRIER_CODES: Final[tuple[str, ...]] = ("TRP-001", "TRP-002", "TRP-003", "TRP-004")
FR_CARRIER_SHARES: Final[tuple[float, ...]] = (0.15, 0.50, 0.35)
SHIPPED_MEDIAN_HOURS: Final[tuple[float, ...]] = (25.0, 46.0, 73.0, 88.0)
SIRAVO_INDEX: Final[int] = 2
INTERNATIONAL_INDEX: Final[int] = 3

SEGMENT_CODES: Final[tuple[str, ...]] = ("occasional", "regular", "loyal")
SEGMENT_SHARES: Final[tuple[float, ...]] = (0.70, 0.25, 0.05)
SEGMENT_WEIGHTS: Final[tuple[float, ...]] = (1.0, 3.0, 8.0)
COUNTRY_CODES: Final[tuple[str, ...]] = ("FR", "BE", "DE")
COUNTRY_SHARES: Final[tuple[float, ...]] = (0.90, 0.06, 0.04)
VAT_RATES: Final[tuple[Decimal, ...]] = (
    Decimal("20.00"),
    Decimal("21.00"),
    Decimal("19.00"),
)

ORDERS_MEAN_WEEKDAY: Final[float] = 94.6
ORDERS_MEAN_WEEKEND: Final[float] = 113.5
# ASSUMPTION: the standard deviation stays 15 on weekends.
ORDERS_STD: Final[float] = 15.0
# ASSUMPTION: day 1 has exactly POOL_START customers in the pool.
POOL_START: Final[int] = 5000
POOL_DAILY_GROWTH: Final[int] = 5

LINE_COUNTS: Final[tuple[int, ...]] = (1, 2, 3)
LINE_COUNT_SHARES: Final[tuple[float, ...]] = (0.65, 0.25, 0.10)
QUANTITIES: Final[tuple[int, ...]] = (1, 2)
QUANTITY_SHARES: Final[tuple[float, ...]] = (0.80, 0.20)

OPENING_HOUR: Final[int] = 7
CLOSING_HOUR: Final[int] = 21
CREATED_MEDIAN_HOURS: Final[float] = 0.5
CREATED_SIGMA: Final[float] = 0.9
PAID_MEDIAN_HOURS: Final[float] = 10.0
PAID_SIGMA: Final[float] = 0.4
SHIPPED_SIGMA: Final[float] = 0.2

CANCEL_RATE: Final[float] = 0.045
CANCEL_FROM_CREATED_SHARE: Final[float] = 0.40
PROBLEM_RATE: Final[float] = 0.02
PROBLEM_SIRAVO_SHARE: Final[float] = 0.70
PROBLEM_FACTOR: Final[float] = 3.0
# Rates per carrier giving 2 percent of problem orders, 70 percent of them at Siravo.
_SIRAVO_ORDER_SHARE: Final[float] = COUNTRY_SHARES[0] * FR_CARRIER_SHARES[SIRAVO_INDEX]
PROBLEM_RATE_SIRAVO: Final[float] = (
    PROBLEM_RATE * PROBLEM_SIRAVO_SHARE / _SIRAVO_ORDER_SHARE
)
PROBLEM_RATE_OTHER: Final[float] = (
    PROBLEM_RATE * (1.0 - PROBLEM_SIRAVO_SHARE) / (1.0 - _SIRAVO_ORDER_SHARE)
)

# ASSUMPTION: the return delay is uniform between 1 and 14 days after delivery.
RETURN_RATE: Final[float] = 0.06
RETURN_MIN_DAYS: Final[int] = 1
RETURN_MAX_DAYS: Final[int] = 14
# ASSUMPTION: a change flips the quantity of the first line between 1 and 2.
MODIFY_RATE: Final[float] = 0.02
# ASSUMPTION: a deletion removes the last line of an order with 2 lines or more.
DELETE_RATE: Final[float] = 0.01

# Kinds 0 to 5 are status events, kinds 6 and 7 are line events.
STATUS_CODES: Final[tuple[str, ...]] = (
    "created",
    "paid",
    "shipped",
    "delivered",
    "cancelled",
    "returned",
)
EVENT_COLUMNS: Final[tuple[str, ...]] = (*STATUS_CODES, "modified", "deleted")
KIND_CREATED: Final[int] = 0
KIND_MODIFIED: Final[int] = 6

NAT: Final[np.datetime64] = np.datetime64("NaT", "s")
ORDER_DTYPE: Final[np.dtype[np.void]] = np.dtype(
    [
        ("order10", "i8"),
        ("customer", "i8"),
        ("carrier", "i8"),
        ("n_lines", "i8"),
        *[(column, "M8[s]") for column in EVENT_COLUMNS],
    ]
)
LINE_DTYPE: Final[np.dtype[np.void]] = np.dtype(
    [("order10", "i8"), ("rank", "i8"), ("product", "i8"), ("quantity", "i8")]
)


class GeneratorError(IngestionError):
    """Raised when the catalog or the requested window is invalid."""


@dataclass(slots=True, frozen=True)
class Product:
    """Catalog product, read from oms.product."""

    product_cd: str
    unit_price_amt: Decimal


@dataclass(slots=True, frozen=True)
class Carrier:
    """Catalog carrier, read from oms.carrier."""

    carrier_cd: str
    promised_days_num: int


@dataclass(slots=True, frozen=True)
class Catalog:
    """Products and carriers that the simulation relies on."""

    products: tuple[Product, ...]
    carriers: tuple[Carrier, ...]


class CustomerMessage(BaseModel):
    """Row of oms.customer. The integer key is derived by the API from the code."""

    model_config = ConfigDict(frozen=True)

    customer_cd: str
    segment_cd: str
    country_cd: str
    created_ts: datetime
    updated_ts: datetime


class SalesOrderMessage(BaseModel):
    """Row of oms.sales_order. The carrier is given by its code."""

    model_config = ConfigDict(frozen=True)

    order_cd: str
    customer_cd: str
    carrier_cd: str
    created_ts: datetime
    updated_ts: datetime


class OrderLineMessage(BaseModel):
    """Row of oms.order_line. The order and the product are given by their codes."""

    model_config = ConfigDict(frozen=True)

    line_cd: str
    order_cd: str
    product_cd: str
    quantity_num: int
    unit_price_amt: Decimal
    vat_rate_num: Decimal
    created_ts: datetime
    updated_ts: datetime
    deleted_ts: datetime | None = None


class OutboxMessage(BaseModel):
    """Row of oms.outbox. The order and the customer are given by their codes."""

    model_config = ConfigDict(frozen=True)

    event_cd: str
    order_cd: str
    customer_cd: str
    status_cd: str
    event_ts: datetime


class OrderCreated(BaseModel):
    """New order with its customer, its lines and its created status event."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["order_created"] = "order_created"
    event_ts: datetime
    customer: CustomerMessage
    order: SalesOrderMessage
    lines: list[OrderLineMessage]
    status_event: OutboxMessage


class StatusChanged(BaseModel):
    """Status transition of an existing order."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["status_changed"] = "status_changed"
    event_ts: datetime
    status_event: OutboxMessage


class LineChanged(BaseModel):
    """Quantity change or logical deletion of an order line, before shipping."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["line_updated", "line_deleted"]
    event_ts: datetime
    line: OrderLineMessage


@dataclass(slots=True, frozen=True)
class _DayPlan:
    """Calendar facts of one simulated day."""

    day: int
    local_date: date
    utc_offset_s: int
    pool_size: int


@dataclass(slots=True, frozen=True)
class _Population:
    """Customer traits and catalog size shared by every simulated day."""

    segments: NDArray[np.intp]
    countries: NDArray[np.intp]
    weight_cdf: NDArray[np.float64]
    product_count: int


@dataclass(slots=True, frozen=True)
class _History:
    """Orders, lines and lookups of the whole simulated history."""

    orders: NDArray[np.void]
    lines: NDArray[np.void]
    population: _Population
    products: tuple[Product, ...]


def load_catalog(engine: Engine) -> Catalog:
    """Reads the active products and carriers from PostgreSQL.

    Example: the row ('PRD-001', 24.90) becomes Product('PRD-001', Decimal('24.90')).

    Args:
        engine: The SQLAlchemy engine bound to the OLTP database.

    Returns:
        The catalog, with products and carriers sorted by code.

    Raises:
        GeneratorError: If the tables cannot be read or the catalog is invalid.
    """
    try:
        with engine.connect() as connection:
            product_rows = connection.execute(
                text(
                    "SELECT product_cd, unit_price_amt FROM oms.product "
                    "WHERE is_active ORDER BY product_cd"
                )
            ).all()
            carrier_rows = connection.execute(
                text(
                    "SELECT carrier_cd, promised_days_num FROM oms.carrier "
                    "WHERE is_active ORDER BY carrier_cd"
                )
            ).all()
    except SQLAlchemyError as exc:
        raise GeneratorError("Cannot read oms.product and oms.carrier") from exc
    catalog = Catalog(
        products=tuple(Product(str(row[0]), Decimal(row[1])) for row in product_rows),
        carriers=tuple(Carrier(str(row[0]), int(row[1])) for row in carrier_rows),
    )
    _validate_catalog(catalog)
    return catalog


def build_json_schema() -> dict[str, object]:
    """Returns the JSON schema of the messages, built from the pydantic models.

    Example: the schema of OrderCreated lists customer_cd, segment_cd and country_cd.

    Returns:
        The JSON schema of the list of events returned by generate_events.
    """
    adapter = TypeAdapter(list[OrderCreated | StatusChanged | LineChanged])
    return adapter.json_schema()


def generate_events(
    window_start: datetime,
    window_end: datetime,
    catalog: Catalog,
    seed: int,
    init_date: date,
) -> list[OrderCreated | StatusChanged | LineChanged]:
    """Returns the events of the window [window_start, window_end), in memory.

    Events are sorted by simulated date, then by order code, then by kind, so that
    two runs with the same inputs give the same list.
    Example: window 2026-01-01 08:00 to 08:05 UTC returns the orders created then.

    Args:
        window_start: Start of the window, included, naive and in UTC.
        window_end: End of the window, excluded, naive and in UTC.
        catalog: Products and carriers read from the PostgreSQL tables.
        seed: Seed of the simulation (ROP_SEED).
        init_date: First simulated day (ROP_INIT_DATE), Paris calendar.

    Returns:
        The sorted events of the window.

    Raises:
        GeneratorError: If a date is timezone aware or the catalog is invalid.
    """
    if window_start.tzinfo is not None or window_end.tzinfo is not None:
        raise GeneratorError("The window must be given in naive UTC")
    _validate_catalog(catalog)
    last_day = _day_number(window_end, init_date)
    if last_day < 1 or window_end <= window_start:
        return []
    history = _build_history(catalog, seed, init_date, last_day)
    selected = _select_events(history.orders, window_start, window_end)
    events = [_build_event(history, kind, index) for kind, index in selected]
    logger.info(
        "window=%s..%s days=%d events=%d",
        window_start,
        window_end,
        last_day,
        len(events),
    )
    return events


def _validate_catalog(catalog: Catalog) -> None:
    """Checks that the catalog can feed the simulation.

    Args:
        catalog: The catalog to check.

    Raises:
        GeneratorError: If products are missing or duplicated, or a carrier is missing.
    """
    codes = [product.product_cd for product in catalog.products]
    if not codes or len(set(codes)) != len(codes):
        raise GeneratorError("The catalog needs unique and non empty products")
    missing = set(CARRIER_CODES) - {item.carrier_cd for item in catalog.carriers}
    if missing:
        raise GeneratorError(f"Carriers missing in the catalog: {sorted(missing)}")


def _day_number(moment: datetime, init_date: date) -> int:
    """Converts a naive UTC moment into a day number, day 1 being the init date.

    Example: 2026-01-01 23:30 UTC is 2026-01-02 in Paris, so day 2 for init 2026-01-01.

    Args:
        moment: The naive UTC moment.
        init_date: First simulated day.

    Returns:
        The day number in the Paris calendar, below 1 before the init date.
    """
    local_date = moment.replace(tzinfo=UTC).astimezone(PARIS).date()
    return (local_date - init_date).days + 1


def _plan_days(init_date: date, last_day: int) -> list[_DayPlan]:
    """Builds the calendar facts of days 1 to last_day.

    Args:
        init_date: First simulated day.
        last_day: Last day number to plan.

    Returns:
        One plan per day, with the Paris UTC offset taken at noon.
    """
    plans: list[_DayPlan] = []
    for day in range(1, last_day + 1):
        local_date = init_date + timedelta(days=day - 1)
        noon = datetime.combine(local_date, time(12), tzinfo=PARIS)
        offset = noon.replace(tzinfo=None) - noon.astimezone(UTC).replace(tzinfo=None)
        pool_size = POOL_START + POOL_DAILY_GROWTH * (day - 1)
        plans.append(_DayPlan(day, local_date, int(offset.total_seconds()), pool_size))
    return plans


def _customer_traits(seed: int, size: int) -> tuple[NDArray[np.intp], NDArray[np.intp]]:
    """Draws segment and country of the first size customers of the pool.

    One row of draws per customer, so the first customers never depend on size.
    Example: customer rank 1 has the same segment whatever the pool size.

    Args:
        seed: Seed of the simulation.
        size: Number of customers to draw.

    Returns:
        The segment indexes and the country indexes, one per customer.
    """
    # Stream 0 is reserved to the customers, the days use streams 1 and above.
    rng = np.random.default_rng(np.random.SeedSequence([seed, 0]))
    draws = rng.random((size, 2))
    segments = np.searchsorted(np.cumsum(SEGMENT_SHARES), draws[:, 0], side="right")
    countries = np.searchsorted(np.cumsum(COUNTRY_SHARES), draws[:, 1], side="right")
    return (
        np.minimum(segments, len(SEGMENT_CODES) - 1),
        np.minimum(countries, len(COUNTRY_CODES) - 1),
    )


def _hours(values: NDArray[np.float64]) -> NDArray[np.timedelta64]:
    """Converts hours into whole seconds.

    Example: 0.5 hour becomes 1800 seconds.

    Args:
        values: Durations in hours.

    Returns:
        The durations as timedelta64 in seconds.
    """
    return np.rint(values * 3600.0).astype(np.int64).astype("timedelta64[s]")


def _lognormal(
    rng: np.random.Generator,
    median: float | NDArray[np.float64],
    sigma: float,
    size: int,
) -> NDArray[np.float64]:
    """Draws lognormal durations in hours from a median and a dispersion.

    Args:
        rng: The generator of the day.
        median: Median in hours, one value or one value per draw.
        sigma: Lognormal dispersion.
        size: Number of draws.

    Returns:
        The durations in hours.
    """
    return rng.lognormal(np.log(median), sigma, size)


def _count_orders(rng: np.random.Generator, weekend: bool) -> int:
    """Draws the number of orders of a day, rounded and bounded at 0.

    Args:
        rng: The generator of the day.
        weekend: True on Saturday and Sunday.

    Returns:
        The number of orders of the day.
    """
    mean = ORDERS_MEAN_WEEKEND if weekend else ORDERS_MEAN_WEEKDAY
    return max(0, int(np.rint(rng.normal(mean, ORDERS_STD))))


def _creation_times(
    rng: np.random.Generator, size: int, local_date: date, utc_offset_s: int
) -> NDArray[np.datetime64]:
    """Draws sorted creation instants between the opening and closing hours.

    Hours are uniform in Paris time and returned in naive UTC.
    Example: 08:00 in Paris in winter becomes 07:00 UTC.

    Args:
        rng: The generator of the day.
        size: Number of orders.
        local_date: The Paris date of the day.
        utc_offset_s: Paris offset to UTC on that day, in seconds.

    Returns:
        The sorted creation instants.
    """
    seconds = rng.integers(OPENING_HOUR * 3600, CLOSING_HOUR * 3600, size)
    local_midnight = np.datetime64(local_date.isoformat(), "s")
    offset = np.timedelta64(utc_offset_s, "s")
    return local_midnight + np.sort(seconds).astype("timedelta64[s]") - offset


def _draw_customers(
    rng: np.random.Generator,
    size: int,
    pool_size: int,
    weight_cdf: NDArray[np.float64],
) -> NDArray[np.intp]:
    """Draws customer ranks in the pool of the day, weighted by segment.

    Args:
        rng: The generator of the day.
        size: Number of orders.
        pool_size: Number of customers in the pool on that day.
        weight_cdf: Cumulative weights of the whole customer pool.

    Returns:
        The customer ranks, starting at 1.
    """
    points = rng.random(size) * weight_cdf[pool_size - 1]
    ranks = np.searchsorted(weight_cdf[:pool_size], points, side="right")
    capped: NDArray[np.intp] = np.minimum(ranks, pool_size - 1)
    return capped + 1


def _draw_carriers(
    rng: np.random.Generator, countries: NDArray[np.intp]
) -> NDArray[np.intp]:
    """Draws the carrier of each order: split for FR, one carrier for BE and DE.

    Args:
        rng: The generator of the day.
        countries: Country index of the customer of each order.

    Returns:
        The carrier index of each order, in CARRIER_CODES order.
    """
    shares = np.cumsum(FR_CARRIER_SHARES)
    french = np.searchsorted(shares, rng.random(len(countries)), side="right")
    french = np.minimum(french, len(FR_CARRIER_SHARES) - 1)
    return np.where(countries == 0, french, INTERNATIONAL_INDEX)


def _fill_timeline(rng: np.random.Generator, orders: NDArray[np.void]) -> None:
    """Fills the paid, shipped, delivered and cancelled dates of the orders.

    A cancelled order stops in Created or in Paid and is never shipped.

    Args:
        rng: The generator of the day.
        orders: The orders of the day, with creation date and carrier already set.
    """
    size = len(orders)
    created_hours = _lognormal(rng, CREATED_MEDIAN_HOURS, CREATED_SIGMA, size)
    paid_hours = _lognormal(rng, PAID_MEDIAN_HOURS, PAID_SIGMA, size)
    medians = np.array(SHIPPED_MEDIAN_HOURS)[orders["carrier"]]
    problem_rates = np.where(
        orders["carrier"] == SIRAVO_INDEX, PROBLEM_RATE_SIRAVO, PROBLEM_RATE_OTHER
    )
    factors = np.where(rng.random(size) < problem_rates, PROBLEM_FACTOR, 1.0)
    shipped_hours = _lognormal(rng, medians, SHIPPED_SIGMA, size) * factors
    cancelled = rng.random(size) < CANCEL_RATE
    from_created = rng.random(size) < CANCEL_FROM_CREATED_SHARE
    paid = orders["created"] + _hours(created_hours)
    shipped = paid + _hours(paid_hours)
    delivered = shipped + _hours(shipped_hours)
    orders["cancelled"] = np.where(
        cancelled, np.where(from_created, paid, shipped), NAT
    )
    orders["paid"] = np.where(cancelled & from_created, NAT, paid)
    orders["shipped"] = np.where(cancelled, NAT, shipped)
    orders["delivered"] = np.where(cancelled, NAT, delivered)


def _fill_returns(rng: np.random.Generator, orders: NDArray[np.void]) -> None:
    """Fills the return date of delivered orders, 1 to 14 days after delivery.

    Args:
        rng: The generator of the day.
        orders: The orders of the day, with the delivery date already set.
    """
    size = len(orders)
    returned = rng.random(size) < RETURN_RATE
    delay = _hours(rng.uniform(RETURN_MIN_DAYS * 24, RETURN_MAX_DAYS * 24, size))
    delivered = orders["delivered"]
    orders["returned"] = np.where(
        returned & ~np.isnat(delivered), delivered + delay, NAT
    )


def _fill_changes(rng: np.random.Generator, orders: NDArray[np.void]) -> None:
    """Fills the dates of line changes and line deletions, before shipping.

    Only orders that are not cancelled are concerned, so no line is touched after
    a cancellation. A deletion needs at least 2 lines, an order keeps one line.

    Args:
        rng: The generator of the day.
        orders: The orders of the day, with the shipping date already set.
    """
    size = len(orders)
    is_open = ~np.isnat(orders["shipped"])
    pick_change = (rng.random(size) < MODIFY_RATE) & is_open
    pick_delete = (rng.random(size) < DELETE_RATE) & is_open & (orders["n_lines"] >= 2)
    span = orders["shipped"] - orders["created"]
    change_at = orders["created"] + span * rng.random(size)
    delete_at = orders["created"] + span * rng.random(size)
    orders["modified"] = np.where(pick_change, change_at, NAT)
    orders["deleted"] = np.where(pick_delete, delete_at, NAT)


def _draw_lines(
    rng: np.random.Generator, orders: NDArray[np.void], product_count: int
) -> NDArray[np.void]:
    """Draws the lines of the orders of a day: product and quantity.

    ASSUMPTION: products are drawn uniformly and may repeat within an order.

    Args:
        rng: The generator of the day.
        orders: The orders of the day, with the number of lines already set.
        product_count: Number of products in the catalog.

    Returns:
        One row per line, grouped by order and ranked from 1 within the order.
    """
    n_lines = orders["n_lines"]
    total = int(n_lines.sum())
    lines = np.zeros(total, dtype=LINE_DTYPE)
    starts = np.cumsum(n_lines) - n_lines
    lines["order10"] = np.repeat(orders["order10"], n_lines)
    lines["rank"] = np.arange(total) - np.repeat(starts, n_lines) + 1
    lines["product"] = rng.integers(0, product_count, total)
    lines["quantity"] = rng.choice(QUANTITIES, size=total, p=QUANTITY_SHARES)
    return lines


def _simulate_day(
    seed: int, plan: _DayPlan, population: _Population
) -> tuple[NDArray[np.void], NDArray[np.void]]:
    """Draws the orders and the lines of one day from its own generator.

    Args:
        seed: Seed of the simulation.
        plan: Calendar facts of the day.
        population: Customer traits and catalog size.

    Returns:
        The orders and the lines created that day.
    """
    rng = np.random.default_rng(np.random.SeedSequence([seed, plan.day]))
    size = _count_orders(rng, plan.local_date.weekday() >= 5)
    orders = np.zeros(size, dtype=ORDER_DTYPE)
    # Order code: day on 5 digits then rank on 5 digits, ranks follow creation time.
    orders["order10"] = plan.day * 100_000 + np.arange(1, size + 1)
    orders["created"] = _creation_times(rng, size, plan.local_date, plan.utc_offset_s)
    orders["customer"] = _draw_customers(
        rng, size, plan.pool_size, population.weight_cdf
    )
    countries = population.countries[orders["customer"] - 1]
    orders["carrier"] = _draw_carriers(rng, countries)
    orders["n_lines"] = rng.choice(LINE_COUNTS, size=size, p=LINE_COUNT_SHARES)
    _fill_timeline(rng, orders)
    _fill_returns(rng, orders)
    _fill_changes(rng, orders)
    return orders, _draw_lines(rng, orders, population.product_count)


def _build_history(
    catalog: Catalog, seed: int, init_date: date, last_day: int
) -> _History:
    """Simulates the whole history from day 1 to last_day.

    Args:
        catalog: Products and carriers read from the PostgreSQL tables.
        seed: Seed of the simulation.
        init_date: First simulated day.
        last_day: Last day number to simulate.

    Returns:
        The orders, the lines and the lookups needed to build the messages.
    """
    products = tuple(sorted(catalog.products, key=attrgetter("product_cd")))
    plans = _plan_days(init_date, last_day)
    segments, countries = _customer_traits(seed, plans[-1].pool_size)
    weights = np.array(SEGMENT_WEIGHTS)[segments]
    population = _Population(segments, countries, np.cumsum(weights), len(products))
    days = [_simulate_day(seed, plan, population) for plan in plans]
    orders = np.concatenate([day_orders for day_orders, _ in days])
    lines = np.concatenate([day_lines for _, day_lines in days])
    return _History(orders, lines, population, products)


def _select_events(
    orders: NDArray[np.void], window_start: datetime, window_end: datetime
) -> list[tuple[int, int]]:
    """Lists the (kind, order index) pairs of a window, sorted.

    Sort key: event date, then order code, then kind, which is deterministic.

    Args:
        orders: All simulated orders.
        window_start: Start of the window, included, naive UTC.
        window_end: End of the window, excluded, naive UTC.

    Returns:
        The sorted pairs, one per event of the window.
    """
    start = np.datetime64(window_start, "s")
    end = np.datetime64(window_end, "s")
    kinds: list[NDArray[np.intp]] = []
    indexes: list[NDArray[np.intp]] = []
    for kind, column in enumerate(EVENT_COLUMNS):
        stamps = orders[column]
        found = np.flatnonzero((stamps >= start) & (stamps < end))
        indexes.append(found)
        kinds.append(np.full(len(found), kind, dtype=np.intp))
    all_kinds = np.concatenate(kinds)
    all_indexes = np.concatenate(indexes)
    stamps_int = np.concatenate(
        [
            orders[column][index].astype(np.int64)
            for column, index in zip(EVENT_COLUMNS, indexes)
        ]
    )
    ranking = np.lexsort((all_kinds, orders["order10"][all_indexes], stamps_int))
    return list(zip(all_kinds[ranking].tolist(), all_indexes[ranking].tolist()))


def _timestamp(value: np.datetime64) -> datetime:
    """Converts a numpy date in seconds into a naive datetime.

    Example: numpy 2026-01-01T09:13:00 becomes datetime(2026, 1, 1, 9, 13).

    Args:
        value: A numpy date, never NaT.

    Returns:
        The naive datetime, in UTC.
    """
    return datetime.fromisoformat(str(value))


def _order_lines(history: _History, order: np.void) -> NDArray[np.void]:
    """Returns the line rows of an order, ranked from 1.

    Args:
        history: The simulated history.
        order: The order row.

    Returns:
        The line rows of the order.
    """
    start = int(np.searchsorted(history.lines["order10"], order["order10"]))
    return history.lines[start : start + int(order["n_lines"])]


def _outbox_message(order: np.void, kind: int) -> OutboxMessage:
    """Builds the status event of an order for a status kind.

    Example: order 100001 and kind 1 give the event code EVT-00001000012.

    Args:
        order: The order row.
        kind: The status kind, from 0 (created) to 5 (returned).

    Returns:
        The outbox message, with the event code ending with the status digit.
    """
    order10 = int(order["order10"])
    return OutboxMessage(
        event_cd=f"EVT-{order10:010d}{kind + 1}",
        order_cd=f"CMD-{order10:010d}",
        customer_cd=f"CLI-{int(order['customer']):06d}",
        status_cd=STATUS_CODES[kind],
        event_ts=_timestamp(order[EVENT_COLUMNS[kind]]),
    )


def _line_message(history: _History, order: np.void, row: np.void) -> OrderLineMessage:
    """Builds the initial message of an order line.

    Args:
        history: The simulated history.
        order: The order row.
        row: The line row.

    Returns:
        The line message, with the price and the VAT rate frozen at order time.
    """
    order10 = int(order["order10"])
    product = history.products[int(row["product"])]
    country = int(history.population.countries[int(order["customer"]) - 1])
    created = _timestamp(order["created"])
    return OrderLineMessage(
        line_cd=f"LIG-{order10:010d}{int(row['rank']):02d}",
        order_cd=f"CMD-{order10:010d}",
        product_cd=product.product_cd,
        quantity_num=int(row["quantity"]),
        unit_price_amt=product.unit_price_amt,
        vat_rate_num=VAT_RATES[country],
        created_ts=created,
        updated_ts=created,
    )


def _build_created(history: _History, order: np.void) -> OrderCreated:
    """Builds the event of a new order: customer, order, lines and created status.

    The customer is sent with every order, the API creates it on its first order.

    Args:
        history: The simulated history.
        order: The order row.

    Returns:
        The OrderCreated event.
    """
    rank = int(order["customer"])
    created = _timestamp(order["created"])
    customer = CustomerMessage(
        customer_cd=f"CLI-{rank:06d}",
        segment_cd=SEGMENT_CODES[int(history.population.segments[rank - 1])],
        country_cd=COUNTRY_CODES[int(history.population.countries[rank - 1])],
        created_ts=created,
        updated_ts=created,
    )
    sales_order = SalesOrderMessage(
        order_cd=f"CMD-{int(order['order10']):010d}",
        customer_cd=customer.customer_cd,
        carrier_cd=CARRIER_CODES[int(order["carrier"])],
        created_ts=created,
        updated_ts=created,
    )
    return OrderCreated(
        event_ts=created,
        customer=customer,
        order=sales_order,
        lines=[
            _line_message(history, order, row) for row in _order_lines(history, order)
        ],
        status_event=_outbox_message(order, KIND_CREATED),
    )


def _build_line_change(history: _History, order: np.void, kind: int) -> LineChanged:
    """Builds a quantity change of the first line or a deletion of the last line.

    Args:
        history: The simulated history.
        order: The order row.
        kind: The event kind, 6 (modified) or 7 (deleted).

    Returns:
        The LineChanged event, carrying the full line row.
    """
    rows = _order_lines(history, order)
    stamp = _timestamp(order[EVENT_COLUMNS[kind]])
    if kind == KIND_MODIFIED:
        row = rows[0]
        line = _line_message(history, order, row).model_copy(
            update={
                "quantity_num": sum(QUANTITIES) - int(row["quantity"]),
                "updated_ts": stamp,
            }
        )
        return LineChanged(kind="line_updated", event_ts=stamp, line=line)
    line = _line_message(history, order, rows[-1]).model_copy(
        update={"updated_ts": stamp, "deleted_ts": stamp}
    )
    return LineChanged(kind="line_deleted", event_ts=stamp, line=line)


def _build_event(
    history: _History, kind: int, index: int
) -> OrderCreated | StatusChanged | LineChanged:
    """Builds the event of a given kind for the order at the given index.

    Args:
        history: The simulated history.
        kind: The event kind, from 0 (created) to 7 (deleted).
        index: The index of the order in the history.

    Returns:
        The event message.
    """
    order = history.orders[index]
    if kind == KIND_CREATED:
        return _build_created(history, order)
    if kind < KIND_MODIFIED:
        status_event = _outbox_message(order, kind)
        return StatusChanged(event_ts=status_event.event_ts, status_event=status_event)
    return _build_line_change(history, order, kind)
