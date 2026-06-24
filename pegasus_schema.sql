CREATE TABLE IF NOT EXISTS ticker_universe (
    ticker      TEXT PRIMARY KEY,
    loaded_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS historical_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker              TEXT NOT NULL,
    event_type          TEXT NOT NULL,
    event_date          TEXT NOT NULL,
    source_url          TEXT NOT NULL,
    accession_number    TEXT NOT NULL,
    event_detail        TEXT,
    pct_workforce       REAL,
    created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(ticker, accession_number)
);

CREATE TABLE IF NOT EXISTS event_outcomes (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id            INTEGER NOT NULL REFERENCES historical_events(id),
    horizon_days        INTEGER NOT NULL,
    entry_price         REAL,
    exit_price          REAL,
    asset_return_pct    REAL,
    spy_entry_price     REAL,
    spy_exit_price      REAL,
    spy_return_pct      REAL,
    excess_return_pct   REAL,
    computed_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE(event_id, horizon_days)
);

CREATE TABLE IF NOT EXISTS pegasus_summaries (
    id                                          INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker                                      TEXT NOT NULL,
    computed_at                                 TEXT NOT NULL,
    expires_at                                  TEXT NOT NULL,
    sector                                      TEXT,
    market_cap_bucket                           TEXT CHECK (market_cap_bucket IN ('small','mid','large')),
    layoff_signal_validity                      REAL,
    median_excess_return_post_layoff_10d        REAL,
    median_excess_return_post_layoff_30d        REAL,
    median_excess_return_post_layoff_60d        REAL,
    median_excess_return_post_layoff_90d        REAL,
    n_layoff_events                             INTEGER DEFAULT 0,
    layoff_mean_excess_60d                      REAL,
    layoff_t_statistic                          REAL,
    layoff_p_value                              REAL,
    summary_confidence                          TEXT CHECK (summary_confidence IN ('low','med','high','insufficient')),
    UNIQUE(ticker)
);

CREATE INDEX IF NOT EXISTS idx_historical_events_ticker ON historical_events(ticker);
CREATE INDEX IF NOT EXISTS idx_historical_events_type   ON historical_events(event_type);
CREATE INDEX IF NOT EXISTS idx_event_outcomes_event     ON event_outcomes(event_id);
CREATE INDEX IF NOT EXISTS idx_pegasus_ticker           ON pegasus_summaries(ticker);
CREATE INDEX IF NOT EXISTS idx_pegasus_expires          ON pegasus_summaries(expires_at);
