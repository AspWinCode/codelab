# Окружение "SQL (SQLite)" (ADM-001/002/003).
# Собрать: docker build -t codelab-runner:sql-sqlite backend/sandbox/sql-sqlite
#
# Решение ученика — это .sql-скрипт, исполняется как
# `sqlite3 -header -csv /sandbox/db.sqlite3 < /sandbox/solution.sql`
# (см. app/services/environments.py) — база собирается на лету методистовым
# ProblemRevision.sql_fixture (app/services/runner.py) и монтируется рядом
# read-only, отдельно от решения ученика.
FROM debian:bookworm-slim

WORKDIR /sandbox

RUN apt-get update \
    && apt-get install -y --no-install-recommends sqlite3 \
    && rm -rf /var/lib/apt/lists/*
