PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS briefs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ticker TEXT NOT NULL,
  data_as_of TEXT NOT NULL,
  horizon_days INTEGER NOT NULL CHECK (horizon_days > 0),
  snapshot_json TEXT NOT NULL,
  thesis TEXT NOT NULL CHECK (length(trim(thesis)) > 0),
  invalidation_condition TEXT NOT NULL CHECK (length(trim(invalidation_condition)) > 0),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TABLE IF NOT EXISTS outcomes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  brief_id INTEGER NOT NULL UNIQUE REFERENCES briefs(id),
  logged_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  start_price REAL NOT NULL CHECK (start_price > 0),
  end_price REAL NOT NULL CHECK (end_price > 0),
  spy_start_price REAL NOT NULL CHECK (spy_start_price > 0),
  spy_end_price REAL NOT NULL CHECK (spy_end_price > 0),
  ticker_return REAL NOT NULL,
  spy_return REAL NOT NULL,
  excess_return REAL NOT NULL,
  verdict TEXT NOT NULL CHECK (verdict IN ('BEAT_SPY','LAGGED_SPY','TIED_SPY')),
  notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS rule_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event TEXT NOT NULL,
  detail TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

CREATE TRIGGER IF NOT EXISTS briefs_no_update
BEFORE UPDATE ON briefs
BEGIN
  SELECT RAISE(ABORT, 'immutable brief: updates are forbidden');
END;

CREATE TRIGGER IF NOT EXISTS briefs_no_delete
BEFORE DELETE ON briefs
BEGIN
  SELECT RAISE(ABORT, 'immutable brief: deletes are forbidden');
END;

CREATE TRIGGER IF NOT EXISTS outcomes_not_before_horizon
BEFORE INSERT ON outcomes
BEGIN
  SELECT CASE
    WHEN julianday(NEW.logged_at) < julianday((SELECT data_as_of FROM briefs WHERE id = NEW.brief_id), '+' || (SELECT horizon_days FROM briefs WHERE id = NEW.brief_id) || ' days')
    THEN RAISE(ABORT, 'outcome before horizon is forbidden')
  END;
END;
