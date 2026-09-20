"""Standalone database initializer used by the container entrypoint."""
from __future__ import annotations

from . import db


def main() -> None:
    db.init_db()
    n = len(db.registered_owner_codes())
    print(f"database ready at {db.config.DB_PATH} ({n} owner codes seeded)")


if __name__ == "__main__":
    main()
