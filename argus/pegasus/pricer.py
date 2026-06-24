"""Historical price outcome computation for Pegasus events."""
from __future__ import annotations

import sqlite3, time
from datetime import timedelta
from argus.providers import Provider, YFinanceProvider, iso_utc, parse_utc
from argus.pegasus import init_pegasus_db

DEFAULT_HORIZONS = [10, 30, 60, 90]


def compute_event_outcomes(conn: sqlite3.Connection, event_id: int, horizons: list[int] | None = None, provider: Provider | None = None) -> dict[str, int]:
    init_pegasus_db(conn)
    horizons = horizons or DEFAULT_HORIZONS
    provider = provider or YFinanceProvider()
    event = conn.execute("SELECT * FROM historical_events WHERE id = ?", (event_id,)).fetchone()
    if event is None:
        raise ValueError(f"event not found: {event_id}")
    ok = skipped = 0
    for h in horizons:
        try:
            entry_at = iso_utc(parse_utc(event["event_date"]))
            exit_at = iso_utc(parse_utc(event["event_date"]) + timedelta(days=h))
            entry = provider.price_on_or_after(event["ticker"], entry_at)
            exitp = provider.price_on_or_after(event["ticker"], exit_at)
            spy_entry = provider.price_on_or_after("SPY", entry_at)
            spy_exit = provider.price_on_or_after("SPY", exit_at)
            asset_ret = exitp.close / entry.close - 1
            spy_ret = spy_exit.close / spy_entry.close - 1
            conn.execute("INSERT OR REPLACE INTO event_outcomes (event_id,horizon_days,entry_price,exit_price,asset_return_pct,spy_entry_price,spy_exit_price,spy_return_pct,excess_return_pct) VALUES (?,?,?,?,?,?,?,?,?)", (event_id, h, entry.close, exitp.close, asset_ret, spy_entry.close, spy_exit.close, spy_ret, asset_ret - spy_ret))
            ok += 1
        except Exception as exc:
            print(f"  Skipping event_id={event_id} ticker={event['ticker']} horizon={h}: {exc}")
            skipped += 1
    return {"computed": ok, "skipped": skipped}


def compute_all_missing_outcomes(conn: sqlite3.Connection, provider: Provider | None = None, batch_size: int = 100) -> dict[str, int]:
    init_pegasus_db(conn)
    rows = conn.execute("SELECT id FROM historical_events WHERE id NOT IN (SELECT DISTINCT event_id FROM event_outcomes) ORDER BY id LIMIT ?", (batch_size,)).fetchall()
    print(f"  Events needing outcomes: {len(rows):,}")
    computed = skipped = 0
    for row in rows:
        res = compute_event_outcomes(conn, int(row["id"]), provider=provider)
        computed += res["computed"]
        skipped += res["skipped"]
        time.sleep(0.05)
    print(f"  Computed successfully: {computed:,}\n  Skipped (delisted/missing data): {skipped:,}")
    return {"events": len(rows), "computed": computed, "skipped": skipped}
