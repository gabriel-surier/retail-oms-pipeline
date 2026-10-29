# PostgreSQL demo image
FROM postgres:17

ARG ROP_POSTGRES_DB
ENV POSTGRES_DB=${ROP_POSTGRES_DB}

COPY init/ /docker-entrypoint-initdb.d/