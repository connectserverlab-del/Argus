"""Offline tests for Pegasus."""
from __future__ import annotations

import sqlite3, sys, tempfile, unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from argus.pipeline import connect, init_db
from argus.providers import FakeProvider, iso_utc
from argus.pegasus import init_pegasus_db
from argus.pegasus.compiler import compile_summary, get_summary
from argus.pegasus.pricer import compute_event_outcomes
from argus.pegasus.study import run_event_study
from argus.pegasus.universe import cache_universe


class DelistedProvider(FakeProvider):
    def price_on_or_after(self, ticker: str, as_of: str):
        if ticker.upper() == "DEAD":
            raise RuntimeError("delisted")
        return super().price_on_or_after(ticker, as_of)


class PegasusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "argus.sqlite3"
        init_db(self.db)
        self.conn = connect(self.db)
        init_pegasus_db(self.conn)

    def tearDown(self):
        self.conn.close(); self.tmp.cleanup()

    def add_event(self, ticker="AAPL", acc="acc", day=1):
        cur = self.conn.execute("INSERT INTO historical_events (ticker,event_type,event_date,source_url,accession_number) VALUES (?,?,?,?,?)", (ticker, "layoff", f"2020-01-{day:02d}T00:00:00Z", "https://www.sec.gov/example", acc))
        return int(cur.lastrowid)

    def test_duplicate_events_rejected(self):
        self.add_event(acc="dup")
        with self.assertRaises(sqlite3.IntegrityError):
            self.add_event(acc="dup")

    def test_signal_validity_none_when_fewer_than_10_events(self):
        provider = FakeProvider()
        for i in range(1, 4):
            eid = self.add_event(acc=f"few-{i}", day=i)
            compute_event_outcomes(self.conn, eid, horizons=[60], provider=provider)
        result = run_event_study(self.conn, "AAPL", "layoff", 60)
        self.assertEqual(result["n_events"], 3)
        self.assertIsNone(result["signal_validity"])

    def test_get_summary_returns_none_for_expired_summary(self):
        now = datetime.now(timezone.utc)
        self.conn.execute("INSERT INTO pegasus_summaries (ticker,computed_at,expires_at,summary_confidence) VALUES (?,?,?,?)", ("AAPL", iso_utc(now - timedelta(days=40)), iso_utc(now - timedelta(days=1)), "insufficient"))
        self.assertIsNone(get_summary(self.conn, "AAPL"))

    def test_full_pipeline_with_fake_data_produces_summary(self):
        cache_universe(self.conn, ["AAPL"])
        provider = FakeProvider()
        for i in range(1, 12):
            eid = self.add_event(acc=f"pipe-{i}", day=i)
            compute_event_outcomes(self.conn, eid, provider=provider)
        compile_summary(self.conn, "AAPL")
        summary = get_summary(self.conn, "AAPL")
        self.assertIsNotNone(summary)
        self.assertEqual(summary["n_layoff_events"], 11)
        self.assertIn(summary["summary_confidence"], {"low", "med", "high", "insufficient"})

    def test_compute_event_outcomes_handles_delisted_ticker(self):
        eid = self.add_event(ticker="DEAD", acc="dead")
        result = compute_event_outcomes(self.conn, eid, provider=DelistedProvider())
        self.assertEqual(result["computed"], 0)
        self.assertGreater(result["skipped"], 0)


if __name__ == "__main__":
    unittest.main()
