"""
@File    :   __main__.py (01_rop_fl001_csv_erp_main)
@Time    :   2026-10-30
@Author  :   Gabriel SURIER
@Purpose :   Run the ERP ingestion workflows in order: products (0100) then carriers (0200).

@Description :

The workflows are independent and each one stays runnable alone, as a script or
through its own main() function. A failing workflow always ends in an IngestionError.
The flag --continue-on-error only decides whether the next workflows still run first.
Usage from the project root: python -m etl [--continue-on-error]

"""

import logging
from collections.abc import Callable
from typing import Final

from etl.rop_fl001_csv_erp import (
    rop_fl001_0100_csv_erp_product,
    rop_fl001_0200_csv_erp_carrier,
)
from src.rop_config import IngestionError, Settings

logger = logging.getLogger(__name__)

WORKFLOWS: Final[tuple[tuple[str, Callable[[], int]], ...]] = (
    (
        rop_fl001_0100_csv_erp_product.__name__,
        rop_fl001_0100_csv_erp_product.main,
    ),
    (
        rop_fl001_0200_csv_erp_carrier.__name__,
        rop_fl001_0200_csv_erp_carrier.main,
    ),
)


def main(stop_on_error: bool = True) -> None:
    """Runs the workflows in order and raises an error if one of them failed.

    Args:
        stop_on_error: True to raise at the first failure and skip the next
            workflows, False to log the failure, run the next workflows and
            raise once all of them have run.

    Raises:
        IngestionError: If at least one workflow failed.
    """
    failed: list[str] = []
    for name, workflow in WORKFLOWS:
        if workflow() == 0:
            continue
        if stop_on_error:
            raise IngestionError(f"Workflow {name} failed, next workflows skipped")
        logger.error("Workflow %s failed, continuing with the next ones", name)
        failed.append(name)
    if failed:
        raise IngestionError(f"Workflows failed: {failed}")


if __name__ == "__main__":
    main(stop_on_error=Settings().rop_stop_on_error)
