"""Command line interface for Pegasus."""
from __future__ import annotations

import argparse, json, sys
from datetime import date
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from argus.pipeline import connect, init_db
from argus.pegasus import init_pegasus_db
from argus.pegasus.compiler import compile_all, get_summary, summaries_needing_refresh
from argus.pegasus.ingester import ingest_events
from argus.pegasus.pricer import compute_all_missing_outcomes
from argus.pegasus.universe import cache_universe, cached_universe_is_fresh, get_cached_universe, load_universe


def _ensure_universe(conn):
    if cached_universe_is_fresh(conn):
        tickers = get_cached_universe(conn)
    else:
        tickers = load_universe()
        cache_universe(conn, tickers)
    print(f"Loading universe... {len(tickers):,} tickers loaded")
    return tickers


def status(conn):
    init_pegasus_db(conn)
    counts = {k: conn.execute(f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"] for k, t in {"events":"historical_events", "outcomes":"event_outcomes", "summaries":"pegasus_summaries"}.items()}
    stale = len(summaries_needing_refresh(conn))
    print(f"events={counts['events']} outcomes={counts['outcomes']} summaries={counts['summaries']} stale={stale}")
    print("Known limitation: the current S&P 500 + Russell 2000 universe has survivorship bias and can miss delisted tickers.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m argus.pegasus.cli")
    sub = parser.add_subparsers(dest="cmd", required=True)
    ing = sub.add_parser("ingest"); ing.add_argument("--start", default="2015-01-01"); ing.add_argument("--end", default=date.today().isoformat())
    sub.add_parser("price"); sub.add_parser("compile"); sub.add_parser("run"); sub.add_parser("status")
    summ = sub.add_parser("summary"); summ.add_argument("ticker")
    args = parser.parse_args(argv)
    init_db()
    with connect() as conn:
        init_pegasus_db(conn)
        if args.cmd == "ingest":
            _ensure_universe(conn); print(f"Ingesting 8-K layoff events {args.start} to {args.end}..."); ingest_events(conn, args.start, args.end)
        elif args.cmd == "price":
            print("Computing price outcomes..."); compute_all_missing_outcomes(conn)
        elif args.cmd == "compile":
            print("Compiling summaries..."); compile_all(conn)
        elif args.cmd == "run":
            _ensure_universe(conn)
            print("Ingesting 8-K layoff events 2015-present..."); ingest_events(conn, "2015-01-01", date.today().isoformat())
            print("Computing price outcomes..."); compute_all_missing_outcomes(conn)
            print("Compiling summaries..."); compile_all(conn)
            print("Done. Run `python -m argus.pegasus.cli status` to review.")
        elif args.cmd == "status":
            status(conn)
        elif args.cmd == "summary":
            print(json.dumps(get_summary(conn, args.ticker), indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
