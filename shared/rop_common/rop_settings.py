"""
@File    :   rop_settings.py
@Time    :   2026-11-02
@Author  :   Gabriel SURIER
@Purpose :   Provides the application settings, one pydantic class per group
"""

from datetime import date
from pathlib import Path
from typing import Final

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parent.parent.parent


class RopSettings(BaseSettings):
    """Base of the settings groups: one .env file, keys of other groups ignored."""

    model_config = SettingsConfigDict(env_file=PROJECT_ROOT / ".env", extra="ignore")


class FileSettings(RopSettings):
    """Paths of the source files and of their metadata YAML files."""

    rop_products_csv_path: Path = PROJECT_ROOT / "data" / "products.csv"
    rop_carriers_file_path: Path = PROJECT_ROOT / "data" / "carriers.csv"
    rop_products_metadata_path: Path = PROJECT_ROOT / "metadata" / "products_csv.yaml"
    rop_carriers_metadata_path: Path = PROJECT_ROOT / "metadata" / "carriers_csv.yaml"


class WorkflowSettings(RopSettings):
    """Behaviour of the workflow runner."""

    # True stops at the first failing workflow, False runs the others then raises.
    rop_stop_on_error: bool = True


class OmsSettings(RopSettings):
    """Parameters of the oms simulation, not used by the ERP ingestion."""

    rop_load_mod: str
    rop_delta_days: int
    rop_init_date: date
    rop_replay_speed: int
    rop_seed: int
    rop_timezone: str


class DatabaseSettings(RopSettings):
    """PostgreSQL credentials, missing values raise at startup."""

    rop_postgres_user: str
    rop_postgres_password: str
    rop_postgres_db: str
    rop_postgres_port: int
    rop_postgres_driver: str
