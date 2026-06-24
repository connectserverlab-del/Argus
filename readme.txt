# Argus Capital Lab — Phase 1: The Research Log

Phase 1 stores immutable, falsifiable point-in-time research briefs and later
logs benchmark-relative outcomes versus SPY. It intentionally has no scores,
rankings, or trading workflow.

## Run it

```bash
python3 -m argus.tests
python3 -m argus.cli init
python3 -m argus.cli brief AAPL --provider fake
python3 -m argus.cli due
python3 -m argus.cli outcome 1 --provider fake
python3 -m argus.cli report
```

The default quick start uses `--provider fake` so it runs offline. To try the optional yfinance plumbing, first install it with `python3 -m pip install yfinance`, then use `--provider yfinance`.

`YFinanceProvider` is price-only and not suitable for point-in-time fundamentals. Use a true point-in-time data vendor before trusting validation results.
