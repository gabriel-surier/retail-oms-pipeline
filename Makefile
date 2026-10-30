# Default env files, override if needed
ENV_FILE ?= .env

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
