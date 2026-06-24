"""Ticker universe loading and caching for Pegasus."""
from __future__ import annotations

import csv
import sqlite3
from datetime import datetime, timedelta, timezone
from io import StringIO
from urllib.request import Request, urlopen

from argus.providers import iso_utc, parse_utc
from argus.pegasus import init_pegasus_db

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
IWM_URL = "https://www.ishares.com/us/products/239710/ishares-russell-2000-etf/1467271812596.ajax?fileType=csv&fileName=IWM_holdings&dataType=fund"


def _http_text(url: str) -> str:
    with urlopen(Request(url, headers={"User-Agent": "Argus Capital Lab research@argus.com"}), timeout=30) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _clean(ticker: str) -> str:
    return ticker.strip().upper().replace(".", "-")


def load_sp500() -> list[str]:
    import pandas as pd
    tables = pd.read_html(SP500_URL)
    return sorted({_clean(t) for t in tables[0]["Symbol"].astype(str) if t and t != "nan"})


def load_russell2000() -> list[str]:
    text = _http_text(IWM_URL)
    start = next((i for i, line in enumerate(text.splitlines()) if line.startswith("Ticker,")), 0)
    rows = csv.DictReader(StringIO("\n".join(text.splitlines()[start:])))
    return sorted({_clean(r.get("Ticker", "")) for r in rows if r.get("Ticker") and r.get("Ticker") != "-"})


def load_universe() -> list[str]:
    return sorted(set(load_sp500()) | set(load_russell2000()))


def cached_universe_is_fresh(conn: sqlite3.Connection, max_age_days: int = 7) -> bool:
    init_pegasus_db(conn)
    row = conn.execute("SELECT MAX(loaded_at) AS loaded_at FROM ticker_universe").fetchone()
    return bool(row and row["loaded_at"] and parse_utc(row["loaded_at"]) > datetime.now(timezone.utc) - timedelta(days=max_age_days))


def get_cached_universe(conn: sqlite3.Connection) -> list[str]:
    init_pegasus_db(conn)
    return [r["ticker"] for r in conn.execute("SELECT ticker FROM ticker_universe ORDER BY ticker")]


def cache_universe(conn: sqlite3.Connection, tickers: list[str]) -> None:
    init_pegasus_db(conn)
    loaded_at = iso_utc(datetime.now(timezone.utc))
    conn.execute("DELETE FROM ticker_universe")
    conn.executemany("INSERT INTO ticker_universe (ticker, loaded_at) VALUES (?, ?)", [(_clean(t), loaded_at) for t in tickers])
