"""Compile Pegasus event-study summaries for Athena."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from argus.providers import iso_utc
from argus.pegasus import init_pegasus_db
from argus.pegasus.study import run_event_study


class PegasusSummary(dict):
    """Athena-friendly summary row with both mapping and attribute access."""

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _confidence(n: int, validity: float | None) -> str:
    if validity is None:
        return "insufficient"
    if n >= 30 and validity >= 0.6:
        return "high"
    return "med" if n >= 10 else "low"


def compile_summary(conn: sqlite3.Connection, ticker: str) -> None:
    init_pegasus_db(conn)
    studies = {h: run_event_study(conn, ticker, "layoff", h) for h in (10, 30, 60, 90)}
    s60 = studies[60]
    now = datetime.now(timezone.utc)
    computed_at = iso_utc(now)
    expires_at = iso_utc(now + timedelta(days=30))
    conn.execute("""
        INSERT INTO pegasus_summaries (ticker,computed_at,expires_at,layoff_signal_validity,
        median_excess_return_post_layoff_10d,median_excess_return_post_layoff_30d,median_excess_return_post_layoff_60d,median_excess_return_post_layoff_90d,
        n_layoff_events,layoff_mean_excess_60d,layoff_t_statistic,layoff_p_value,summary_confidence)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(ticker) DO UPDATE SET computed_at=excluded.computed_at, expires_at=excluded.expires_at,
        layoff_signal_validity=excluded.layoff_signal_validity, median_excess_return_post_layoff_10d=excluded.median_excess_return_post_layoff_10d,
        median_excess_return_post_layoff_30d=excluded.median_excess_return_post_layoff_30d, median_excess_return_post_layoff_60d=excluded.median_excess_return_post_layoff_60d,
        median_excess_return_post_layoff_90d=excluded.median_excess_return_post_layoff_90d, n_layoff_events=excluded.n_layoff_events,
        layoff_mean_excess_60d=excluded.layoff_mean_excess_60d, layoff_t_statistic=excluded.layoff_t_statistic,
        layoff_p_value=excluded.layoff_p_value, summary_confidence=excluded.summary_confidence
    """, (ticker.upper(), computed_at, expires_at, s60["signal_validity"], studies[10]["median_excess_return"], studies[30]["median_excess_return"], studies[60]["median_excess_return"], studies[90]["median_excess_return"], s60["n_events"], s60["mean_excess_return"], s60["t_statistic"], s60["p_value"], _confidence(s60["n_events"], s60["signal_validity"])))


def compile_all(conn: sqlite3.Connection) -> dict[str, int]:
    init_pegasus_db(conn)
    tickers = [r["ticker"] for r in conn.execute("SELECT ticker FROM ticker_universe ORDER BY ticker")]
    if not tickers:
        tickers = [r["ticker"] for r in conn.execute("SELECT DISTINCT ticker FROM historical_events ORDER BY ticker")]
    valid = insufficient = 0
    for t in tickers:
        compile_summary(conn, t)
        row = conn.execute("SELECT layoff_signal_validity FROM pegasus_summaries WHERE ticker=?", (t,)).fetchone()
        if row and row["layoff_signal_validity"] is None:
            insufficient += 1
        else:
            valid += 1
    print(f"  Summaries written: {len(tickers):,}\n  Summaries with valid signal score: {valid:,}\n  Summaries with insufficient data (NULL validity): {insufficient:,}")
    return {"written": len(tickers), "valid": valid, "insufficient": insufficient}


def get_summary(conn: sqlite3.Connection, ticker: str) -> PegasusSummary | None:
    init_pegasus_db(conn)
    row = conn.execute("SELECT * FROM pegasus_summaries WHERE ticker=? AND julianday(expires_at) > julianday('now')", (ticker.upper(),)).fetchone()
    return PegasusSummary(dict(row)) if row else None


def attach_summary_to_snapshot(conn: sqlite3.Connection, ticker: str, snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return an Athena snapshot copy with the fresh Pegasus summary attached.

    Missing or stale summaries are represented as ``None`` so Athena can
    degrade gracefully without doing historical computation inline.
    """
    enriched = dict(snapshot)
    summary = get_summary(conn, ticker)
    enriched["pegasus"] = dict(summary) if summary is not None else None
    return enriched


def summaries_needing_refresh(conn: sqlite3.Connection) -> list[str]:
    init_pegasus_db(conn)
    return [r["ticker"] for r in conn.execute("SELECT ticker FROM pegasus_summaries WHERE julianday(expires_at) <= julianday('now') ORDER BY ticker")]
