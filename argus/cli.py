"""Command line interface for Argus Phase 1."""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from argus.author import validate_brief_payload
from argus.pipeline import connect, due_briefs, init_db, log_outcome, store_brief, validation_report
from argus.providers import iso_utc, provider_by_name


def now_utc() -> str:
    return iso_utc(datetime.now(timezone.utc))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="argus")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init")
    brief = sub.add_parser("brief")
    brief.add_argument("ticker")
    brief.add_argument("--provider", default="fake", choices=["fake", "yfinance"])
    brief.add_argument("--horizon-days", type=int, default=30)
    brief.add_argument("--as-of", default=None)
    brief.add_argument("--thesis", default="Falsifiable qualitative thesis based only on the stored snapshot.")
    brief.add_argument("--invalidation-condition", default="The thesis is invalidated if excess return versus SPY is not positive at horizon.")
    due = sub.add_parser("due")
    due.add_argument("--now", default=None)
    outcome = sub.add_parser("outcome")
    outcome.add_argument("brief_id", type=int)
    outcome.add_argument("--provider", default="fake", choices=["fake", "yfinance"])
    outcome.add_argument("--logged-at", default=None)
    sub.add_parser("report")
    args = parser.parse_args(argv)

    if args.cmd == "init":
        init_db()
        print("initialized argus.sqlite3")
        return 0

    init_db()
    with connect() as conn:
        if args.cmd == "brief":
            provider = provider_by_name(args.provider)
            data_as_of = args.as_of or now_utc()
            snapshot = provider.snapshot(args.ticker, data_as_of)
            payload = validate_brief_payload({"thesis": args.thesis, "invalidation_condition": args.invalidation_condition})
            brief_id = store_brief(conn, ticker=args.ticker, data_as_of=data_as_of, horizon_days=args.horizon_days, snapshot=snapshot, **payload)
            print(f"brief_id={brief_id}")
        elif args.cmd == "due":
            for row in due_briefs(conn, args.now or now_utc()):
                print(f"{row['id']} {row['ticker']} due")
        elif args.cmd == "outcome":
            provider = provider_by_name(args.provider)
            outcome_id = log_outcome(conn, provider, args.brief_id, args.logged_at or now_utc())
            print(f"outcome_id={outcome_id}")
        elif args.cmd == "report":
            report = validation_report(conn)
            rate = "n/a" if report.hit_rate is None else f"{report.hit_rate:.1%}"
            print(f"{report.verdict}: outcomes={report.logged_outcomes} hit_rate={rate}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
