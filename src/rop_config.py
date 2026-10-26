"""
@File    :   rop_config.py
@Time    :   2026-08-26
@Author  :   Gabriel SURIER
@Purpose :   Provides application settings
"""

from datetime import date
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables or .env file.

    Values are validated by pydantic at import time; missing required
    fields raise at startup rather than failing later mid-pipeline.
    """

    # --- Environment path config ---

    project_root: Path = Path(__file__).resolve().parent.parent
    model_config = SettingsConfigDict(env_file=project_root / ".env")

    # --- Environment path config ---

    oms_load_mod: str
    oms_delta_days: int
    oms_init_date: date
    oms_replay_speed: int
    oms_seed: int
