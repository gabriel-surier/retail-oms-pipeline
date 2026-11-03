"""
@File    :   test_runner.py
@Time    :   2026-11-03
@Author  :   Gabriel SURIER
@Purpose :   Unit test of the workflow runner: stop or continue after a failure
"""

from unittest.mock import Mock

import pytest

from etl.rop_fl001_csv_erp import __main__ as runner
from shared.rop_common.rop_errors import IngestionError


@pytest.mark.parametrize(
    ("stop_on_error", "message", "last_calls"),
    [
        (True, "next workflows skipped", 0),
        (False, "Workflows failed", 1),
    ],
)
def test_stop_on_error(
    monkeypatch: pytest.MonkeyPatch,
    stop_on_error: bool,
    message: str,
    last_calls: int,
) -> None:
    """Checks that a failure always raises, the next workflows run if not stopping.

    Args:
        monkeypatch: The pytest fixture used to replace the workflow list.
        stop_on_error: The value given to the runner.
        message: A part of the expected error message.
        last_calls: How many times the workflow after the failing one must run.
    """
    last = Mock(return_value=0)
    workflows = (
        ("first_ok", Mock(return_value=0)),
        ("failing", Mock(return_value=1)),
        ("last", last),
    )
    monkeypatch.setattr(runner, "WORKFLOWS", workflows)

    with pytest.raises(IngestionError, match=message):
        runner.main(stop_on_error=stop_on_error)

    assert last.call_count == last_calls
