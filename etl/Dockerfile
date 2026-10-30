# Version pinned by default for reproducible builds; override via compose
# build args if a service needs a different Airflow/Python combo.
ARG PYTHON_VERSION=3.12
FROM python:${PYTHON_VERSION}-slim

WORKDIR /app

# setup requirements packages

COPY ../etl/requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# setup data input csv
COPY data/ ./data/

# setup project modules
COPY .env_docker ./.env
COPY pyproject.toml ./pyproject.toml
COPY etl/ ./etl/
COPY src/__init__.py ./src/__init__.py
COPY src/rop_config.py ./src/rop_config.py

# install project moules after all copy commands
RUN pip install -e .

# ARG does not persist to runtime; promoted to ENV so the port
# is available both at build (EXPOSE) and at container start.
