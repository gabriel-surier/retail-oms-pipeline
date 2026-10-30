"""
@File    :   rop_fl001_0000_csv_erp_main.py
@Time    :   2026-10-30
@Author  :   Gabriel SURIER
@Purpose :   Create the Airflow DAG to orchestrate the rop csv erp workflows

"""

import logging
import os
from datetime import timedelta

import pendulum
from airflow import DAG
from airflow.providers.docker.operators.docker import DockerOperator
from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import Variable

logger = logging.getLogger(__name__)

# ASSUMPTION: image name, network and command are placeholders to adjust.
# The command follows the folder seen in the traceback: etl/01_rop_f001_csv_erp.
ETL_IMAGE = "retail-oms-etl:latest"
ETL_NETWORK = "airflow-net"
ETL_COMMAND = "python -m etl.rop_fl001_csv_erp"

# Key -> default. Resolution order: Airflow Variable, then .env, then default
# ROP_STOP_ON_ERROR: true stops at the first failing workflow, false runs the
# next ones then fails the task at the end.
# ASSUMPTION: defaults of the oms settings are guesses, align them with your .env.
VARIABLE_KEYS = {
    "ROP_STOP_ON_ERROR": "true",
    "ROP_LOAD_MOD": "DELTA",
    "ROP_DELTA_DAYS": "1",
    "ROP_INIT_DATE": "2026-01-01",
    "ROP_REPLAY_SPEED": "1",
    "ROP_SEED": "42",
    "ROP_POSTGRES_USER": "",
    "ROP_POSTGRES_PASSWORD": "",
    "ROP_POSTGRES_DB": "",
    "ROP_POSTGRES_PORT": "",
}

# Every key of VARIABLE_KEYS becomes a templated container variable
ETL_ENVIRONMENT = {
    "AIRFLOW_CTX_DAG_RUN_ID": "{{ run_id }}",
    "AIRFLOW_CTX_EXECUTION_DATE": "{{ ts }}",
    **{key: "{{ resolve_value('" + key + "') }}" for key in VARIABLE_KEYS},
}

default_args = {
    "owner": "gabriel.surier",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": timedelta(minutes=5),
}


def resolve(key: str) -> tuple[str, str]:
    """Resolve a key from Airflow Variable, then environment, then default.

    Called at runtime only (task execution or template rendering), so a
    variable created at any time is picked up on the next run.

    Args:
        key: Name of the variable to resolve, must be in VARIABLE_KEYS.

    Returns:
        A tuple (value, source), source being "airflow_variable", "env"
        or "default".
    """
    value = Variable.get(key, default=None)
    if value is not None:
        return value, "airflow_variable"
    value = os.getenv(key)
    if value is not None:
        return value, "env"
    return VARIABLE_KEYS[key], "default"


def resolve_value(key: str) -> str:
    """Return only the resolved value, for use in Jinja templates.

    Args:
        key: Name of the variable to resolve, must be in VARIABLE_KEYS.

    Returns:
        The resolved value, whatever its source.
    """
    return resolve(key)[0]


def log_and_resolve_variables() -> None:
    """Log each resolved variable with its source.

    Values from Airflow Variables or defaults are logged (masked by
    Airflow when the key name is sensitive). Any value coming from the
    environment (.env) is hidden and triggers a warning.
    """
    for key in VARIABLE_KEYS:
        value, source = resolve(key)
        if source == "env":
            logger.warning("%s loaded from .env (value hidden)", key)
        else:
            logger.info("%s=%s (source=%s)", key, value, source)


with DAG(
    dag_id="rop_fl001_0000_csv_erp_main",
    default_args=default_args,
    description="retail oms pipeline workflow # 01",
    start_date=pendulum.datetime(2026, 10, 30, tz="Europe/Paris"),
    schedule="0 8 * * *",
    catchup=False,
    tags={"rop", "demo"},
    user_defined_macros={"resolve_value": resolve_value},
) as dag:

    log_variables = PythonOperator(
        task_id="log_and_resolve_variables",
        python_callable=log_and_resolve_variables,
    )

    run_main = DockerOperator(
        task_id="rop_fl001_0000_csv_erp_run_main",
        image=ETL_IMAGE,
        docker_url="unix://var/run/docker.sock",
        network_mode=ETL_NETWORK,
        command=ETL_COMMAND,
        environment=ETL_ENVIRONMENT,
        auto_remove="success",
        mount_tmp_dir=False,
    )

    log_variables >> run_main  # pylint: disable=pointless-statement
