"""Pegasus offline historical event study engine."""
from __future__ import annotations

import sqlite3
from pathlib import Path

PEGASUS_SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "pegasus_schema.sql"


def init_pegasus_db(conn: sqlite3.Connection) -> None:
    """Apply Pegasus-only tables without modifying existing Argus tables."""
    conn.executescript(PEGASUS_SCHEMA_PATH.read_text())
