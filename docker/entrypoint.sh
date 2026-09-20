#!/usr/bin/env bash
# 容器启动：1) 确认依赖安装  2) 建库  3) 启动服务
# 每一步均为幂等操作：镜像构建期已预装依赖、init_db 使用 IF NOT EXISTS。
set -euo pipefail

echo "[entrypoint] ensuring Python dependencies ..."
if ! python -c "import fastapi, uvicorn, pydantic" 2>/dev/null; then
    echo "[entrypoint] dependencies missing, installing from requirements.txt ..."
    pip install --no-cache-dir -r /app/requirements.txt
fi

echo "[entrypoint] initializing SQLite database at ${DB_PATH:-/data/adjudication.db} ..."
python -m app.init_db

echo "[entrypoint] starting service: $*"
exec "$@"
