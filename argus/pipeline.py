"""Argus Phase 1 research-log pipeline."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any

from argus.providers import Provider, assert_no_lookahead, iso_utc, parse_utc

DB_PATH = Path("argus.sqlite3")
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "schema.sql"


@dataclass(frozen=True)
class Report:
    logged_outcomes: int
    hit_rate: float | None
    verdict: str


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: Path = DB_PATH) -> None:
    with connect(path) as conn:
        conn.executescript(SCHEMA_PATH.read_text())


def store_brief(
    conn: sqlite3.Connection,
    *,
    ticker: str,
    data_as_of: str,
    horizon_days: int,
    snapshot: dict[str, Any],
    thesis: str,
    invalidation_condition: str,
) -> int:
    if not invalidation_condition.strip():
        raise ValueError("invalidation_condition is required")
    assert_no_lookahead(snapshot, data_as_of)
    cur = conn.execute(
        """
        INSERT INTO briefs (ticker, data_as_of, horizon_days, snapshot_json, thesis, invalidation_condition)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (ticker.upper(), data_as_of, horizon_days, json.dumps(snapshot, sort_keys=True), thesis.strip(), invalidation_condition.strip()),
    )
    conn.execute("INSERT INTO rule_log (event, detail) VALUES (?, ?)", ("brief_created", f"brief_id={cur.lastrowid}"))
    return int(cur.lastrowid)


def due_briefs(conn: sqlite3.Connection, now: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT b.* FROM briefs b
        LEFT JOIN outcomes o ON o.brief_id = b.id
        WHERE o.id IS NULL AND julianday(?) >= julianday(b.data_as_of, '+' || b.horizon_days || ' days')
        ORDER BY b.id
        """,
        (now,),
    ).fetchall()


def log_outcome(conn: sqlite3.Connection, provider: Provider, brief_id: int, logged_at: str) -> int:
    brief = conn.execute("SELECT * FROM briefs WHERE id = ?", (brief_id,)).fetchone()
    if brief is None:
        raise ValueError(f"brief not found: {brief_id}")
    horizon_at = parse_utc(brief["data_as_of"]) + timedelta(days=int(brief["horizon_days"]))
    if parse_utc(logged_at) < horizon_at:
        raise ValueError("outcome before horizon is forbidden")

    start = provider.price_on_or_after(brief["ticker"], brief["data_as_of"])
    end = provider.price_on_or_after(brief["ticker"], iso_utc(horizon_at))
    spy_start = provider.price_on_or_after("SPY", brief["data_as_of"])
    spy_end = provider.price_on_or_after("SPY", iso_utc(horizon_at))
    ticker_return = end.close / start.close - 1
    spy_return = spy_end.close / spy_start.close - 1
    excess = ticker_return - spy_return
    verdict = "TIED_SPY" if abs(excess) < 1e-12 else ("BEAT_SPY" if excess > 0 else "LAGGED_SPY")
    cur = conn.execute(
        """
        INSERT INTO outcomes
        (brief_id, logged_at, start_price, end_price, spy_start_price, spy_end_price, ticker_return, spy_return, excess_return, verdict)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (brief_id, logged_at, start.close, end.close, spy_start.close, spy_end.close, ticker_return, spy_return, excess, verdict),
    )
    conn.execute("INSERT INTO rule_log (event, detail) VALUES (?, ?)", ("outcome_logged", f"brief_id={brief_id}"))
    return int(cur.lastrowid)


def validation_report(conn: sqlite3.Connection, min_outcomes: int = 50) -> Report:
    rows = conn.execute("SELECT verdict FROM outcomes").fetchall()
    n = len(rows)
    if n < min_outcomes:
        return Report(n, None, "INSUFFICIENT DATA")
    hits = sum(1 for r in rows if r["verdict"] == "BEAT_SPY")
    hit_rate = hits / n
    verdict = "POSSIBLE EDGE" if hit_rate >= 0.60 else "NO EDGE DETECTED"
    return Report(n, hit_rate, verdict)
