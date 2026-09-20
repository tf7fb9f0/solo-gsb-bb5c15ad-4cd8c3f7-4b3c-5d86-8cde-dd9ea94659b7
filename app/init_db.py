"""容器启动时建库入口：python -m app.init_db"""
from __future__ import annotations

from .config import settings
from .database import init_db


def main() -> None:
    init_db(settings.db_path)
    print(f"database ready at {settings.db_path}")


if __name__ == "__main__":
    main()
