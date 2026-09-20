"""Application configuration read from environment variables.

All values have sensible defaults so the service starts with zero
configuration (see README for the list of overridable variables).
"""
from __future__ import annotations

import os


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# SQLite database file (container startup creates the schema and seeds it).
DB_PATH: str = os.getenv("DB_PATH", "/data/adjudication.db")

# When true, positions 1-3 must be registered in the owner-code registry.
# When false, only the ISO 6346 structural rule (3 capital letters) applies.
ENFORCE_OWNER_REGISTRY: bool = _bool(os.getenv("ENFORCE_OWNER_REGISTRY"), False)

# Allowed category identifiers at position 4 (ISO 6346: U/J/Z).
CATEGORY_LETTERS: frozenset[str] = frozenset(
    ch.upper()
    for ch in os.getenv("CATEGORY_LETTERS", "UJZ")
    if ch.upper().isalpha()
) or frozenset({"U", "J", "Z"})

# Number of ranked candidates returned; the total count is never affected.
TOP_K: int = max(1, int(os.getenv("TOP_K", "20")))

# Server bind address / port.
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8000"))
