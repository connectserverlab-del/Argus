"""
Pegasus + Athena integration test using 100 synthetic data points.

What this does end to end:
  1. Loads synthetic_events.json into the database as historical_events
  2. Runs Pegasus event study engine across all sector/cap/type combinations
  3. Compiles pegasus_summaries for every ticker
  4. Runs Athena against 5 live ticker snapshots using those summaries
  5. Prints a full projection report showing what Pegasus found and
     how Athena would interpret each live signal

Run: python3 -m argus.test_integration
"""
from __future__ import annotations

import json
import math
import sqlite3
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── database ──────────────────────────────────────────────────────────────────

SCHEMA_EXTENSION = """
CREATE TABLE IF NOT EXISTS historical_events (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker           TEXT    NOT NULL,
    sector           TEXT    NOT NULL,
    market_cap       TEXT    NOT NULL,
    event_type       TEXT    NOT NULL,
    event_date       TEXT    NOT NULL,
    accession_number TEXT    NOT NULL,
    source_url       TEXT    NOT NULL,
    event_detail     TEXT,
    pct_workforce    REAL,
    created_at       TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(ticker, accession_number)
);

CREATE TABLE IF NOT EXISTS event_outcomes (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id          INTEGER NOT NULL REFERENCES historical_events(id),
    horizon_days      INTEGER NOT NULL,
    entry_price       REAL,
    exit_price        REAL,
    asset_return_pct  REAL,
    spy_return_pct    REAL,
    excess_return_pct REAL,
    data_missing      INTEGER NOT NULL DEFAULT 0,
    UNIQUE(event_id, horizon_days)
);

CREATE TABLE IF NOT EXISTS pegasus_summaries (
    id                                          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker                                      TEXT    NOT NULL,
    sector                                      TEXT,
    market_cap_bucket                           TEXT,
    computed_at                                 TEXT    NOT NULL,
    expires_at                                  TEXT    NOT NULL,

    layoff_signal_validity                      REAL,
    layoff_n_events                             INTEGER DEFAULT 0,
    layoff_mean_excess_60d                      REAL,
    layoff_median_excess_60d                    REAL,
    layoff_mean_excess_30d                      REAL,
    layoff_mean_excess_90d                      REAL,
    layoff_hit_rate                             REAL,
    layoff_t_statistic                          REAL,
    layoff_p_value                              REAL,

    store_closure_signal_validity               REAL,
    store_closure_n_events                      INTEGER DEFAULT 0,
    store_closure_mean_excess_60d               REAL,
    store_closure_median_excess_60d             REAL,
    store_closure_hit_rate                      REAL,

    hiring_surge_signal_validity                REAL,
    hiring_surge_n_events                       INTEGER DEFAULT 0,
    hiring_surge_mean_excess_60d                REAL,
    hiring_surge_median_excess_60d              REAL,
    hiring_surge_hit_rate                       REAL,

    summary_confidence                          TEXT,
    UNIQUE(ticker)
);

CREATE INDEX IF NOT EXISTS idx_he_ticker  ON historical_events(ticker);
CREATE INDEX IF NOT EXISTS idx_he_sector  ON historical_events(sector);
CREATE INDEX IF NOT EXISTS idx_he_type    ON historical_events(event_type);
CREATE INDEX IF NOT EXISTS idx_eo_event   ON event_outcomes(event_id);
CREATE INDEX IF NOT EXISTS idx_ps_ticker  ON pegasus_summaries(ticker);
"""


def connect(path=":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_EXTENSION)
    return conn


# ── step 1: ingest synthetic events ───────────────────────────────────────────

def ingest_synthetic(conn: sqlite3.Connection, path: str) -> int:
    data = json.loads(Path(path).read_text())
    events = data["events"]
    stored = 0
    for e in events:
        try:
            cur = conn.execute(
                """INSERT OR IGNORE INTO historical_events
                   (ticker, sector, market_cap, event_type, event_date,
                    accession_number, source_url, event_detail, pct_workforce)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (e["ticker"], e["sector"], e["market_cap"], e["event_type"],
                 e["event_date"], e["accession_number"], e["source_url"],
                 e["event_detail"], e.get("pct_workforce")),
            )
            if cur.lastrowid:
                event_id = cur.lastrowid
                for h_str, outcome in e["outcomes"].items():
                    conn.execute(
                        """INSERT OR IGNORE INTO event_outcomes
                           (event_id, horizon_days, entry_price, exit_price,
                            asset_return_pct, spy_return_pct, excess_return_pct,
                            data_missing)
                           VALUES (?,?,?,?,?,?,?,?)""",
                        (event_id, int(h_str),
                         outcome.get("entry_price"),
                         outcome.get("exit_price"),
                         outcome.get("asset_return_pct"),
                         outcome.get("spy_return_pct"),
                         outcome.get("excess_return_pct"),
                         int(outcome.get("data_missing", False))),
                    )
                stored += 1
        except sqlite3.IntegrityError:
            pass
    conn.commit()
    return stored


# ── step 2: event study engine ────────────────────────────────────────────────

def _t_test_one_sample(values: list[float], mu: float = 0.0):
    """One-sample t-test against mu. Returns (t_stat, p_value_approx)."""
    n = len(values)
    if n < 3:
        return None, None
    mean = statistics.mean(values)
    try:
        std = statistics.stdev(values)
    except statistics.StatisticsError:
        return None, None
    if std == 0:
        return None, None
    t = (mean - mu) / (std / math.sqrt(n))
    df = n - 1
    try:
        if df >= 30:
            p = 2 * (1 - _norm_cdf(abs(t)))
        else:
            p = 2 * (1 - _norm_cdf(abs(t) * math.sqrt(df / (df + 2))))
    except Exception:
        p = None
    return round(t, 3), round(p, 4) if p is not None else None


def _norm_cdf(x: float) -> float:
    """Abramowitz & Stegun approximation of normal CDF."""
    t = 1.0 / (1.0 + 0.2316419 * abs(x))
    poly = t * (0.319381530
                + t * (-0.356563782
                       + t * (1.781477937
                              + t * (-1.821255978
                                     + t * 1.330274429))))
    pdf = math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)
    cdf = 1.0 - pdf * poly
    return cdf if x >= 0 else 1.0 - cdf


def run_event_study(conn: sqlite3.Connection, sector: str, market_cap: str,
                    event_type: str, horizon: int = 60) -> dict:
    """
    Compute excess return statistics for a sector/cap/event_type combination.
    Uses sector-level aggregation so we get enough events for valid statistics.
    """
    rows = conn.execute(
        """SELECT eo.excess_return_pct
           FROM event_outcomes eo
           JOIN historical_events he ON he.id = eo.event_id
           WHERE he.sector = ?
             AND he.market_cap = ?
             AND he.event_type = ?
             AND eo.horizon_days = ?
             AND eo.data_missing = 0
             AND eo.excess_return_pct IS NOT NULL""",
        (sector, market_cap, event_type, horizon)
    ).fetchall()

    values = [r[0] for r in rows]
    n = len(values)

    if n < 5:
        return {"n": n, "validity": None, "insufficient": True}

    mean_excess = statistics.mean(values)
    median_excess = statistics.median(values)

    # Hit rate: fraction where excess moved in "expected" direction
    # For layoff/store_closure: expected = negative excess (bearish)
    # For hiring_surge: expected = positive excess (bullish)
    bearish_signals = {"layoff", "store_closure"}
    if event_type in bearish_signals:
        hit_rate = sum(1 for v in values if v < 0) / n
    else:
        hit_rate = sum(1 for v in values if v > 0) / n

    t_stat, p_value = _t_test_one_sample(values)

    # Signal validity: 0 if not significant, else hit_rate scaled by significance
    if p_value is None or p_value > 0.10:
        validity = 0.0
    else:
        validity = round(hit_rate * (1 - p_value), 3)

    return {
        "n": n,
        "mean_excess": round(mean_excess, 3),
        "median_excess": round(median_excess, 3),
        "hit_rate": round(hit_rate, 3),
        "t_statistic": t_stat,
        "p_value": p_value,
        "validity": validity,
        "insufficient": False,
    }


# ── step 3: compile per-ticker summaries ──────────────────────────────────────

def _confidence(n_total: int) -> str:
    if n_total == 0:
        return "insufficient"
    if n_total < 5:
        return "low"
    if n_total < 15:
        return "med"
    return "high"


def compile_summary(conn: sqlite3.Connection, ticker: str) -> None:
    """
    Compile a Pegasus summary for one ticker.
    Uses sector-level event study results (not ticker-level, which would
    have too few events) but stores them keyed to the ticker for Athena lookup.
    """
    row = conn.execute(
        "SELECT sector, market_cap FROM historical_events WHERE ticker=? LIMIT 1",
        (ticker,)
    ).fetchone()

    if row is None:
        # Ticker has no events — store a minimal summary so Athena knows
        sector, cap = "unknown", "unknown"
    else:
        sector, cap = row["sector"], row["market_cap"]

    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=30)
    fmt = "%Y-%m-%dT%H:%M:%SZ"

    # Run studies at multiple horizons
    layoff   = {h: run_event_study(conn, sector, cap, "layoff", h)
                for h in [30, 60, 90]}
    closure  = {h: run_event_study(conn, sector, cap, "store_closure", h)
                for h in [60]}
    hiring   = {h: run_event_study(conn, sector, cap, "hiring_surge", h)
                for h in [60]}

    l60 = layoff[60]
    c60 = closure[60]
    h60 = hiring[60]

    total_n = (l60.get("n", 0) + c60.get("n", 0) + h60.get("n", 0))

    conn.execute(
        """INSERT OR REPLACE INTO pegasus_summaries (
               ticker, sector, market_cap_bucket, computed_at, expires_at,
               layoff_signal_validity, layoff_n_events,
               layoff_mean_excess_60d, layoff_median_excess_60d,
               layoff_mean_excess_30d, layoff_mean_excess_90d,
               layoff_hit_rate, layoff_t_statistic, layoff_p_value,
               store_closure_signal_validity, store_closure_n_events,
               store_closure_mean_excess_60d, store_closure_median_excess_60d,
               store_closure_hit_rate,
               hiring_surge_signal_validity, hiring_surge_n_events,
               hiring_surge_mean_excess_60d, hiring_surge_median_excess_60d,
               hiring_surge_hit_rate,
               summary_confidence)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            ticker, sector, cap,
            now.strftime(fmt), expires.strftime(fmt),
            # layoff
            l60.get("validity"), l60.get("n", 0),
            l60.get("mean_excess"), l60.get("median_excess"),
            layoff[30].get("mean_excess"), layoff[90].get("mean_excess"),
            l60.get("hit_rate"), l60.get("t_statistic"), l60.get("p_value"),
            # store closure
            c60.get("validity"), c60.get("n", 0),
            c60.get("mean_excess"), c60.get("median_excess"),
            c60.get("hit_rate"),
            # hiring surge
            h60.get("validity"), h60.get("n", 0),
            h60.get("mean_excess"), h60.get("median_excess"),
            h60.get("hit_rate"),
            # confidence
            _confidence(total_n),
        )
    )
    conn.commit()


def compile_all(conn: sqlite3.Connection, tickers: list[str]) -> None:
    for t in tickers:
        compile_summary(conn, t)


# ── step 4: athena projection ─────────────────────────────────────────────────

@dataclass
class LiveSignal:
    """What Athena detects in the live snapshot."""
    ticker: str
    sector: str
    market_cap: str
    detected_event: str        # layoff / store_closure / hiring_surge / none
    event_detail: str
    current_price: float
    momentum_30d_pct: float    # price momentum vs SPY


def athena_projection(conn: sqlite3.Connection, signal: LiveSignal) -> dict:
    """
    Athena reads the Pegasus summary and produces a calibrated projection.
    This is the logic that would normally be inside the LLM prompt context.
    Here we make it explicit so we can read the reasoning directly.
    """
    ps = conn.execute(
        "SELECT * FROM pegasus_summaries WHERE ticker=?", (signal.ticker,)
    ).fetchone()

    proj = {
        "ticker": signal.ticker,
        "sector": signal.sector,
        "market_cap": signal.market_cap,
        "detected_event": signal.detected_event,
        "current_price": signal.current_price,
        "momentum_30d_pct": signal.momentum_30d_pct,
        "pegasus_available": ps is not None,
        "thesis_direction": None,
        "thesis_confidence": None,
        "projected_excess_return_60d": None,
        "signal_validity": None,
        "historical_n_events": None,
        "athena_reasoning": [],
        "invalidation_condition": None,
        "recommended_horizon_days": 60,
    }

    reasoning = proj["athena_reasoning"]

    if ps is None:
        reasoning.append("No Pegasus summary available. Thesis confidence capped at LOW.")
        proj["thesis_confidence"] = "low"
        proj["thesis_direction"] = "flat"
        return proj

    # Route to the right signal
    event = signal.detected_event
    if event == "layoff":
        validity    = ps["layoff_signal_validity"]
        n           = ps["layoff_n_events"]
        mean_60d    = ps["layoff_mean_excess_60d"]
        median_60d  = ps["layoff_median_excess_60d"]
        hit_rate    = ps["layoff_hit_rate"]
        p_value     = ps["layoff_p_value"]
        expected_dir = "down"
    elif event == "store_closure":
        validity    = ps["store_closure_signal_validity"]
        n           = ps["store_closure_n_events"]
        mean_60d    = ps["store_closure_mean_excess_60d"]
        median_60d  = ps["store_closure_median_excess_60d"]
        hit_rate    = ps["store_closure_hit_rate"]
        p_value     = None
        expected_dir = "down"
    elif event == "hiring_surge":
        validity    = ps["hiring_surge_signal_validity"]
        n           = ps["hiring_surge_n_events"]
        mean_60d    = ps["hiring_surge_mean_excess_60d"]
        median_60d  = ps["hiring_surge_median_excess_60d"]
        hit_rate    = ps["hiring_surge_hit_rate"]
        p_value     = None
        expected_dir = "up"
    else:
        reasoning.append("No live signal detected. No directional thesis.")
        proj["thesis_direction"] = "flat"
        proj["thesis_confidence"] = "low"
        return proj

    proj["signal_validity"]        = validity
    proj["historical_n_events"]    = n
    proj["projected_excess_return_60d"] = median_60d

    # Reasoning chain — this is what the LLM would receive as context
    reasoning.append(
        f"Detected signal: {event} in {signal.market_cap}-cap {signal.sector}."
    )
    mean_str   = f"{mean_60d:+.1f}%" if mean_60d   is not None else "n/a"
    median_str = f"{median_60d:+.1f}%" if median_60d is not None else "n/a"
    hr_str     = f"{hit_rate:.0%}" if hit_rate is not None else "n/a"
    reasoning.append(
        f"Pegasus historical base ({n} events): "
        f"mean excess={mean_str}, median={median_str}, "
        f"hit_rate={hr_str} at 60 days."
    )

    if validity is None or n < 5:
        reasoning.append(
            f"Insufficient historical data (n={n}). "
            "Cannot compute valid signal score. Confidence capped at LOW."
        )
        proj["thesis_direction"]  = expected_dir
        proj["thesis_confidence"] = "low"

    elif validity == 0.0:
        reasoning.append(
            f"Signal validity=0.0 — historically indistinguishable from noise "
            f"(p={p_value}). Market likely prices this in immediately. "
            "Confidence: LOW, direction uncertain."
        )
        proj["thesis_direction"]  = "flat"
        proj["thesis_confidence"] = "low"

    elif validity < 0.4:
        reasoning.append(
            f"Signal validity={validity:.2f} — weak historical signal. "
            f"Hit rate {hit_rate:.0%} with modest statistical support. "
            "Proceed with LOW-MED confidence only."
        )
        proj["thesis_direction"]  = expected_dir
        proj["thesis_confidence"] = "low"

    elif validity < 0.65:
        reasoning.append(
            f"Signal validity={validity:.2f} — moderate historical signal. "
            f"Hit rate {hit_rate:.0%}. Market tends to underreact to this "
            f"event type in this sector. Confidence: MED."
        )
        proj["thesis_direction"]  = expected_dir
        proj["thesis_confidence"] = "med"

    else:
        reasoning.append(
            f"Signal validity={validity:.2f} — strong historical signal. "
            f"Hit rate {hit_rate:.0%} with strong statistical support. "
            f"Historical median excess return {median_60d:+.1f}% at 60 days. "
            "Confidence: HIGH."
        )
        proj["thesis_direction"]  = expected_dir
        proj["thesis_confidence"] = "high"

    # Momentum cross-check
    if signal.momentum_30d_pct < -5 and expected_dir == "down":
        reasoning.append(
            f"Momentum confirmation: stock already down {signal.momentum_30d_pct:.1f}% "
            "vs SPY in past 30 days. Price action consistent with thesis — "
            "market may be partially pricing signal in already."
        )
    elif signal.momentum_30d_pct > 5 and expected_dir == "down":
        reasoning.append(
            f"Momentum contradiction: stock up {signal.momentum_30d_pct:.1f}% "
            "vs SPY while bearish signal detected. Market disagrees with thesis. "
            "Reduce confidence by one level."
        )
        levels = {"high": "med", "med": "low", "low": "low"}
        proj["thesis_confidence"] = levels.get(proj["thesis_confidence"], "low")

    # Invalidation condition
    inv = {
        "layoff":        "Company announces hiring resumption, strategic buyer, or "
                         "raises forward guidance within 45 days.",
        "store_closure": "Company announces net new store openings, financing, "
                         "or same-store sales acceleration within 45 days.",
        "hiring_surge":  "Company reverses hiring plan, announces freeze, or "
                         "misses next earnings estimate.",
    }
    proj["invalidation_condition"] = inv.get(event, "Thesis conditions reverse.")

    return proj


# ── step 5: print report ──────────────────────────────────────────────────────

def print_report(conn: sqlite3.Connection, projections: list[dict]) -> None:
    sep = "─" * 72

    print("\n" + "═" * 72)
    print("  PEGASUS + ATHENA INTEGRATION REPORT")
    print("  Synthetic dataset — 100 historical events")
    print("═" * 72)

    # Pegasus summary stats
    summaries = conn.execute("SELECT * FROM pegasus_summaries").fetchall()
    events_total = conn.execute("SELECT COUNT(*) FROM historical_events").fetchone()[0]
    outcomes_total = conn.execute(
        "SELECT COUNT(*) FROM event_outcomes WHERE data_missing=0"
    ).fetchone()[0]
    missing_total = conn.execute(
        "SELECT COUNT(*) FROM event_outcomes WHERE data_missing=1"
    ).fetchone()[0]

    print(f"\nPEGASUS DATASET SUMMARY")
    print(sep)
    print(f"  Historical events ingested : {events_total}")
    print(f"  Price outcomes computed    : {outcomes_total}")
    print(f"  Missing data (delisted)    : {missing_total}")
    print(f"  Ticker summaries compiled  : {len(summaries)}")

    # Sector-level signal study results
    print(f"\nPEGASUS SIGNAL STUDY — SECTOR/CAP AGGREGATES (60-day horizon)")
    print(sep)
    print(f"  {'Sector/Cap/Signal':<36} {'N':>4} {'Mean Excess':>12} "
          f"{'Hit Rate':>10} {'Validity':>10}")
    print(f"  {'-'*36} {'----':>4} {'----------':>12} {'--------':>10} {'--------':>10}")

    combos = [
        ("tech",    "large", "layoff"),
        ("tech",    "small", "layoff"),
        ("tech",    "large", "hiring_surge"),
        ("tech",    "small", "hiring_surge"),
        ("retail",  "large", "layoff"),
        ("retail",  "small", "layoff"),
        ("retail",  "large", "store_closure"),
        ("retail",  "small", "store_closure"),
        ("retail",  "large", "hiring_surge"),
        ("retail",  "small", "hiring_surge"),
        ("health",  "large", "layoff"),
        ("health",  "small", "layoff"),
        ("energy",  "large", "layoff"),
        ("energy",  "small", "layoff"),
        ("finance", "large", "layoff"),
        ("finance", "small", "layoff"),
    ]

    for sector, cap, etype in combos:
        s = run_event_study(conn, sector, cap, etype, 60)
        label = f"{sector}/{cap}/{etype}"
        if s.get("insufficient") or s["n"] < 3:
            print(f"  {label:<36} {'<3':>4} {'insufficient':>12}")
        else:
            val_str = f"{s['validity']:.2f}" if s['validity'] is not None else "NULL"
            print(f"  {label:<36} {s['n']:>4} "
                  f"{s['mean_excess']:>+11.2f}% "
                  f"{s['hit_rate']:>9.0%}  "
                  f"{val_str:>9}")

    # Athena projections
    print(f"\nATHENA PROJECTIONS — 5 LIVE TICKER SCENARIOS")
    print(sep)

    for i, p in enumerate(projections, 1):
        conf_icons = {"high": "▲▲▲", "med": "▲▲ ", "low": "▲  "}
        dir_icons  = {"up": "↑ BULLISH", "down": "↓ BEARISH", "flat": "→ NEUTRAL"}

        print(f"\n  [{i}] {p['ticker']}  |  "
              f"{p['market_cap'].upper()}-CAP {p['sector'].upper()}  |  "
              f"Price: ${p['current_price']:.2f}")
        print(f"      Signal detected : {p['detected_event'].upper()}")
        print(f"      Direction        : {dir_icons.get(p['thesis_direction'], p['thesis_direction'])}")
        print(f"      Confidence       : {conf_icons.get(p['thesis_confidence'], '?')} "
              f"{p['thesis_confidence'].upper()}")

        if p["projected_excess_return_60d"] is not None:
            print(f"      Projected excess : {p['projected_excess_return_60d']:+.1f}% vs SPY at 60d "
                  f"(historical median)")
        if p["signal_validity"] is not None:
            print(f"      Signal validity  : {p['signal_validity']:.2f}  "
                  f"(from {p['historical_n_events']} historical events)")
        if p["invalidation_condition"]:
            print(f"      Invalidation     : {p['invalidation_condition']}")

        print(f"      Pegasus reasoning:")
        for line in p["athena_reasoning"]:
            # word wrap at 65 chars
            words = line.split()
            current = "        > "
            for w in words:
                if len(current) + len(w) > 75:
                    print(current)
                    current = "          " + w + " "
                else:
                    current += w + " "
            print(current.rstrip())

    # Validation summary
    print(f"\nVALIDATION GATE STATUS")
    print(sep)
    n_outcomes = conn.execute(
        "SELECT COUNT(*) FROM event_outcomes WHERE data_missing=0"
    ).fetchone()[0]
    print(f"  Outcomes available         : {n_outcomes}")
    print(f"  Minimum for Phase 2 gate   : 50")
    print(f"  Gate status                : "
          f"{'OPEN — sufficient data' if n_outcomes >= 50 else 'LOCKED — need more outcomes'}")
    print(f"\n  NOTE: These are SYNTHETIC outcomes. Gate passage on synthetic data")
    print(f"  does not authorize Phase 2. Real forward-tested outcomes required.")
    print("\n" + "═" * 72 + "\n")


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    print("Initializing database...")
    conn = connect(":memory:")

    print("Ingesting 100 synthetic events...")
    data_path = Path(__file__).parent / "synthetic_events.json"
    n = ingest_synthetic(conn, str(data_path))
    print(f"  Stored {n} new events")

    # Get all unique tickers
    tickers = [r[0] for r in conn.execute(
        "SELECT DISTINCT ticker FROM historical_events"
    ).fetchall()]
    print(f"  Unique tickers: {len(tickers)}")

    print("Compiling Pegasus summaries...")
    compile_all(conn, tickers)
    print(f"  Compiled {len(tickers)} summaries")

    # 5 live ticker scenarios for Athena
    # Each represents a different signal type and sector/cap combination
    # so we can see how Pegasus context changes the thesis calibration
    live_signals = [
        LiveSignal(
            ticker="PRTY", sector="retail", market_cap="small",
            detected_event="store_closure",
            event_detail="Party City announced closure of 45 underperforming locations.",
            current_price=4.20,
            momentum_30d_pct=-12.3,    # already selling off — confirms thesis
        ),
        LiveSignal(
            ticker="MSFT", sector="tech", market_cap="large",
            detected_event="layoff",
            event_detail="Microsoft announced 5% global workforce reduction.",
            current_price=415.80,
            momentum_30d_pct=+3.1,     # momentum contradicts bearish thesis
        ),
        LiveSignal(
            ticker="BIGC", sector="tech", market_cap="small",
            detected_event="layoff",
            event_detail="BigCommerce reduces headcount by 9% amid slowing growth.",
            current_price=6.40,
            momentum_30d_pct=-8.7,     # confirms bearish thesis
        ),
        LiveSignal(
            ticker="HUBS", sector="tech", market_cap="small",
            detected_event="hiring_surge",
            event_detail="HubSpot announces 800 new hires in product and engineering.",
            current_price=512.00,
            momentum_30d_pct=+6.2,     # momentum confirms bullish thesis
        ),
        LiveSignal(
            ticker="XOM", sector="energy", market_cap="large",
            detected_event="layoff",
            event_detail="ExxonMobil announces workforce reduction of 8% following asset divestitures.",
            current_price=108.50,
            momentum_30d_pct=-1.4,     # neutral momentum
        ),
    ]

    print("Running Athena projections...")
    projections = [athena_projection(conn, s) for s in live_signals]

    print_report(conn, projections)


if __name__ == "__main__":
    main()
