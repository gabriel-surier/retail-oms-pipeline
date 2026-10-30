.PHONY: setup env dirs perms init build-etl up up-local network down logs ps clean \
    check-docker-gid print-docker-gid password \
    deploy reload-streamlit ensure-buckets rebuild up


# Default env files, override if needed
ENV_FILE ?= .env
ENV_DOCKER_FILE ?= .env_docker

# DOCKER_GID computed from the socket. := (not =) avoids re-expanding a CLI override as $(shell ...).
DOCKER_GID := $(shell stat -c '%g' /var/run/docker.sock)
export DOCKER_GID

check-docker-gid:
	@test -n "$(DOCKER_GID)" || \
	   (echo "Could not resolve DOCKER_GID. Override: make up DOCKER_GID=<gid>."; exit 1)

# --- Print the resolved value, for a quick unit test ---
print-docker-gid:
	@echo "$(DOCKER_GID)"

up: check-docker-gid
	docker compose --env-file $(ENV_FILE) up -d

rebuild:
	docker compose --env-file $(ENV_FILE) up --build -d
	docker compose up etl-rop --build -d
# --- Build database for the first time ---
build-oms-pg:
	docker compose up postgres --build -d

# --- Rebuild database for init testing ---

rebuild-oms-pg:
	docker compose down postgres -v
	docker compose up postgres --build -d

# --- Local ps ---
ps:
	docker compose ps

# --- Build airflow ---
build-airflow:
	docker compose up  airflow-init --build -d
	docker compose up  api-server --build -d
	docker compose up  airflow-scheduler --build -d
	docker compose up  airflow-dag-processor --build -d


# --- Build the ETL image, tagged for on-demand use by DockerOperator, never a standing container ---
build-etl:
	docker compose --profile build-only build etl-rop


# --- Print the auto-generated Airflow admin password. Retries: api-server may take a few seconds ---
password:
	@user=$$(docker exec api-server printenv \
	   AIRFLOW__CORE__SIMPLE_AUTH_MANAGER_USERS | cut -d: -f1); \
	tries=0; \
	while [ $$tries -lt 15 ]; do \
	   pass=$$(docker exec api-server python3 -c \
	      "import json,sys; \
	      f='/opt/airflow/simple_auth_manager_passwords.json.generated'; \
	      d=json.load(open(f)); \
	      print(d.get(sys.argv[1], ''))" "$$user" 2>/dev/null); \
	   test -n "$$pass" && break; \
	   tries=$$((tries + 1)); \
	   sleep 2; \
	done; \
	if [ -z "$$pass" ]; then \
	   echo "Password not ready yet, is api-server up? Retry: make password"; \
	   exit 1; \
	fi; \
	echo "Airflow admin user:     $$user"; \
	echo "Airflow admin password: $$pass"

