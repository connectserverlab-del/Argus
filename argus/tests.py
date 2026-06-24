"""Offline proofs for Argus Phase 1 guarantees."""
from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from .pipeline import connect, due_briefs, init_db, log_outcome, store_brief, validation_report
from .providers import FakeProvider, assert_no_lookahead


class GuaranteesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.db = Path(self.tmp.name) / "argus.sqlite3"
        init_db(self.db)
        self.conn = connect(self.db)
        self.provider = FakeProvider()

    def tearDown(self) -> None:
        self.conn.close()
        self.tmp.cleanup()

    def create_brief(self, **kw) -> int:
        as_of = kw.pop("data_as_of", "2020-01-01T00:00:00Z")
        params = {
            "ticker": "AAPL",
            "data_as_of": as_of,
            "horizon_days": 30,
            "snapshot": self.provider.snapshot("AAPL", as_of),
            "thesis": "AAPL will beat SPY over the horizon.",
            "invalidation_condition": "AAPL fails to beat SPY over the same window.",
        }
        params.update(kw)
        return store_brief(self.conn, **params)

    def test_no_lookahead_snapshot_rejected(self) -> None:
        with self.assertRaises(ValueError):
            assert_no_lookahead({"data_as_of": "2020-01-02T00:00:00Z"}, "2020-01-01T00:00:00Z")

    def test_outcome_guard_in_app_and_trigger(self) -> None:
        brief_id = self.create_brief()
        with self.assertRaises(ValueError):
            log_outcome(self.conn, self.provider, brief_id, "2020-01-15T00:00:00Z")
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                """
                INSERT INTO outcomes
                (brief_id, logged_at, start_price, end_price, spy_start_price, spy_end_price, ticker_return, spy_return, excess_return, verdict)
                VALUES (?, ?, 1, 1, 1, 1, 0, 0, 0, 'TIED_SPY')
                """,
                (brief_id, "2020-01-15T00:00:00Z"),
            )

    def test_briefs_are_immutable(self) -> None:
        brief_id = self.create_brief()
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("UPDATE briefs SET thesis = 'changed' WHERE id = ?", (brief_id,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute("DELETE FROM briefs WHERE id = ?", (brief_id,))

    def test_invalidation_condition_required(self) -> None:
        with self.assertRaises(ValueError):
            self.create_brief(invalidation_condition="")

    def test_benchmark_relative_outcome_and_report_gate(self) -> None:
        brief_id = self.create_brief()
        self.assertEqual([r["id"] for r in due_briefs(self.conn, "2020-02-01T00:00:00Z")], [brief_id])
        log_outcome(self.conn, self.provider, brief_id, "2020-02-01T00:00:00Z")
        row = self.conn.execute("SELECT * FROM outcomes WHERE brief_id = ?", (brief_id,)).fetchone()
        self.assertIn(row["verdict"], {"BEAT_SPY", "LAGGED_SPY", "TIED_SPY"})
        self.assertAlmostEqual(row["excess_return"], row["ticker_return"] - row["spy_return"])
        self.assertEqual(validation_report(self.conn).verdict, "INSUFFICIENT DATA")


if __name__ == "__main__":
    unittest.main()
