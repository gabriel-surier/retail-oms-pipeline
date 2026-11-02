"""
@File    :   rop_errors.py
@Time    :   2026-11-02
@Author  :   Gabriel SURIER
@Purpose :   Provides the business exception shared by the ERP jobs
"""


class IngestionError(Exception):
    """Base exception for every business error raised by the ingestion jobs."""
