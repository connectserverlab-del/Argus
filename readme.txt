# Argus Capital Lab — Phase 1: The Research Log

Phase 1 stores immutable, falsifiable point-in-time research briefs and later
logs benchmark-relative outcomes versus SPY. It intentionally has no scores,
rankings, or trading workflow.

## Run it

```bash
python -m argus.tests
python -m argus.cli init
python -m argus.cli brief AAPL --provider yfinance
python -m argus.cli due
python -m argus.cli outcome 1 --provider yfinance
python -m argus.cli report
```

`YFinanceProvider` is price-only and not suitable for point-in-time fundamentals.
Use a true point-in-time data vendor before trusting validation results.
