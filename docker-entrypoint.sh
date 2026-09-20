#!/bin/sh
# Container startup:
#   1. ensure Python dependencies are installed (no-op when baked in)
#   2. create the SQLite schema / seed the owner registry
#   3. run the API server
set -e

echo "[entrypoint] ensuring Python dependencies ..."
pip install --no-cache-dir -r /app/requirements.txt >/dev/null

echo "[entrypoint] initializing database at ${DB_PATH:-/data/adjudication.db} ..."
python -m app.init_db

echo "[entrypoint] starting API on ${HOST:-0.0.0.0}:${PORT:-8000} ..."
exec "$@"
