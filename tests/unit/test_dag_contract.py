"""
@File    :   test_dag_contract.py
@Time    :   2026-11-03
@Author  :   Gabriel SURIER
@Purpose :   Unit test of the contract between the DAG variables and the settings
"""

import ast
from pathlib import Path
from typing import Final

from shared.rop_common.rop_settings import PROJECT_ROOT, DatabaseSettings, OmsSettings

DAG_FILE: Final[Path] = (
    PROJECT_ROOT / "orchestration" / "dags" / "rop_fl001_0000_csv_erp_main.py"
)


def read_variable_keys(path: Path) -> set[str]:
    """Reads the keys of VARIABLE_KEYS in a DAG file, without importing Airflow.

    Args:
        path: Path of the DAG file.

    Returns:
        The keys of the VARIABLE_KEYS dictionary.

    Raises:
        AssertionError: If the file has no VARIABLE_KEYS dictionary.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == "VARIABLE_KEYS"
            for target in node.targets
        ):
            keys: dict[str, str] = ast.literal_eval(node.value)
            return set(keys)
    raise AssertionError(f"VARIABLE_KEYS not found in {path}")


def test_variable_keys_cover_settings() -> None:
    """Checks that every required setting is passed by the DAG to the container."""
    required = {
        name.upper()
        for settings in (DatabaseSettings, OmsSettings)
        for name, field in settings.model_fields.items()
        if field.is_required()
    }

    missing = sorted(required - read_variable_keys(DAG_FILE))

    assert not missing, f"Required settings missing in VARIABLE_KEYS: {missing}"
