"""Statistical event studies for Pegasus."""
from __future__ import annotations

import math, sqlite3, statistics
from argus.pegasus import init_pegasus_db


def _p_value_two_tailed(t: float, n: int) -> float:
    try:
        from scipy import stats
        return float(stats.t.sf(abs(t), df=n - 1) * 2)
    except Exception:
        return max(0.0, min(1.0, math.erfc(abs(t) / math.sqrt(2))))


def _study(rows: list[sqlite3.Row]) -> dict:
    vals = [float(r["excess_return_pct"]) for r in rows if r["excess_return_pct"] is not None]
    n = len(vals)
    mean = statistics.fmean(vals) if vals else None
    median = statistics.median(vals) if vals else None
    hit_rate = (sum(1 for v in vals if v < 0) / n) if n else None
    t = p = None
    if n >= 2:
        sd = statistics.stdev(vals)
        t = 0.0 if sd == 0 else mean / (sd / math.sqrt(n))
        p = _p_value_two_tailed(t, n)
    validity = None
    if n >= 10:
        validity = 0.0 if p is None or p > 0.05 else float(hit_rate * (1 - p))
    return {"n_events": n, "mean_excess_return": mean, "median_excess_return": median, "hit_rate": hit_rate, "t_statistic": t, "p_value": p, "signal_validity": validity}


def run_event_study(conn: sqlite3.Connection, ticker: str, event_type: str, horizon_days: int) -> dict:
    init_pegasus_db(conn)
    rows = conn.execute("SELECT eo.excess_return_pct FROM event_outcomes eo JOIN historical_events he ON he.id=eo.event_id WHERE he.ticker=? AND he.event_type=? AND eo.horizon_days=?", (ticker.upper(), event_type, horizon_days)).fetchall()
    return _study(rows)


def run_sector_study(conn: sqlite3.Connection, sector: str, event_type: str, horizon_days: int) -> dict:
    init_pegasus_db(conn)
    rows = conn.execute("SELECT eo.excess_return_pct FROM event_outcomes eo JOIN historical_events he ON he.id=eo.event_id JOIN pegasus_summaries ps ON ps.ticker=he.ticker WHERE ps.sector=? AND he.event_type=? AND eo.horizon_days=?", (sector, event_type, horizon_days)).fetchall()
    return _study(rows)
