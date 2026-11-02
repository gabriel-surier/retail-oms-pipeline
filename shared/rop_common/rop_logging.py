"""
@File    :   rop_logging.py
@Time    :   2026-11-02
@Author  :   Gabriel SURIER
@Purpose :   Provides the logging configuration shared by every job of the project
"""

import logging
from typing import Final

LOG_FORMAT: Final[str] = "%(asctime)s %(levelname)s %(module)s %(message)s"


def configure_logging(level: int = logging.INFO) -> None:
    """Configures the root logger with the project format.

    Does nothing if the root logger is already configured, so a workflow can call
    it whether it runs alone or from the main of the package.
    Example: configure_logging() prints '2026-11-02 19:40:00,000 INFO module msg'.

    Args:
        level: The minimum level of the messages to print.
    """
    logging.basicConfig(level=level, format=LOG_FORMAT)
