# Version pinned by default for reproducible builds; override via compose
# build args if a service needs a different Airflow/Python combo.
ARG AIRFLOW_VERSION=3.3.1
ARG AIRFLOW_PYTHON_VERSION=3.11
FROM apache/airflow:${AIRFLOW_VERSION}-python${AIRFLOW_PYTHON_VERSION}

WORKDIR /opt/airflow

# Dependencies copied and installed separately from source code
# to avoid busting the pip cache on every code change.
# Switched to airflow user: the base image forbids pip install as root.
USER airflow

COPY orchestration/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY orchestration/dags/ ./dags/


# ARG does not persist to runtime; promoted to ENV so the port
# is available both at build (EXPOSE) and at container start.

ARG AIRFLOW_PORT=8085
ENV AIRFLOW_PORT=${AIRFLOW_PORT}
EXPOSE ${AIRFLOW_PORT}

# No custom ENTRYPOINT/CMD here: the base apache/airflow image already
# ships its own entrypoint script (init, db migration, user creation).
# Overriding it would break "webserver" / "scheduler" / "standalone"
# command dispatch. The command itself is set in docker-compose.yml.