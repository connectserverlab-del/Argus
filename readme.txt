# Argus Capital Lab — Phase 1: The Research Log

Phase 1 stores immutable, falsifiable point-in-time research briefs and later
logs benchmark-relative outcomes versus SPY. It intentionally has no scores,
rankings, or trading workflow.

## Run it

```bash
python3 -m argus.tests
python3 -m argus.cli init
python3 -m argus.cli brief AAPL --provider yfinance
python3 -m argus.cli due
python3 -m argus.cli outcome 1 --provider yfinance
python3 -m argus.cli report
```

`YFinanceProvider` is price-only and not suitable for point-in-time fundamentals.
Use a true point-in-time data vendor before trusting validation results.
