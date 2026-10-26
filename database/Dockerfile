# PostgreSQL demo image
FROM postgres:17

ARG OMS_POSTGRES_DB
ENV POSTGRES_DB=${OMS_POSTGRES_DB}

COPY init/ /docker-entrypoint-initdb.d/