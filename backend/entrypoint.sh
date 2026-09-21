#!/bin/sh
set -e
if [ "${SKIP_MIGRATIONS:-0}" != "1" ]; then
  echo "Running migrations..."
  alembic upgrade head
fi
echo "Starting application..."
exec "$@"
