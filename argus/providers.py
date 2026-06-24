"""Market data providers for Argus Phase 1."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


def parse_utc(value: str) -> datetime:
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class PricePoint:
    ticker: str
    as_of: str
    close: float


class Provider(Protocol):
    def snapshot(self, ticker: str, as_of: str) -> dict[str, Any]: ...
    def price_on_or_after(self, ticker: str, as_of: str) -> PricePoint: ...


def assert_no_lookahead(snapshot: dict[str, Any], as_of: str) -> None:
    """Reject snapshots containing explicit timestamps after the brief as_of."""
    cutoff = parse_utc(as_of)

    def walk(obj: Any, path: str = "snapshot") -> None:
        if isinstance(obj, dict):
            for key, value in obj.items():
                next_path = f"{path}.{key}"
                if key.endswith(("_as_of", "_at", "date", "timestamp")) and isinstance(value, str):
                    try:
                        if parse_utc(value) > cutoff:
                            raise ValueError(f"lookahead datum at {next_path}: {value} > {as_of}")
                    except ValueError as exc:
                        if "lookahead datum" in str(exc):
                            raise
                walk(value, next_path)
        elif isinstance(obj, list):
            for i, value in enumerate(obj):
                walk(value, f"{path}[{i}]")

    walk(snapshot)


class FakeProvider:
    """Deterministic offline provider used by tests."""

    def __init__(self) -> None:
        self.prices = {
            "AAPL": 100.0,
            "MSFT": 200.0,
            "SPY": 400.0,
        }

    def snapshot(self, ticker: str, as_of: str) -> dict[str, Any]:
        return {
            "ticker": ticker.upper(),
            "data_as_of": as_of,
            "price": self.prices.get(ticker.upper(), 50.0),
            "provider": "fake",
        }

    def price_on_or_after(self, ticker: str, as_of: str) -> PricePoint:
        dt = parse_utc(as_of)
        base = self.prices.get(ticker.upper(), 50.0)
        drift = max(0, (dt - parse_utc("2020-01-01T00:00:00Z")).days) / 36500
        if ticker.upper() == "SPY":
            drift /= 2
        return PricePoint(ticker.upper(), iso_utc(dt), round(base * (1 + drift), 4))


class YFinanceProvider:
    """Price-only yfinance provider.

    WARNING: yfinance fundamentals are today's restated numbers, not reliable
    point-in-time data. This provider intentionally omits fundamentals.
    """

    def _yf(self):
        import yfinance as yf
        return yf

    def snapshot(self, ticker: str, as_of: str) -> dict[str, Any]:
        point = self.price_on_or_after(ticker, as_of)
        return {
            "ticker": ticker.upper(),
            "data_as_of": as_of,
            "price": point.close,
            "price_as_of": point.as_of,
            "provider": "yfinance",
            "warning": "price-only; yfinance fundamentals are not point-in-time and are omitted",
        }

    def price_on_or_after(self, ticker: str, as_of: str) -> PricePoint:
        yf = self._yf()
        start = parse_utc(as_of).date().isoformat()
        hist = yf.Ticker(ticker).history(start=start, period="10d", auto_adjust=True)
        if hist.empty:
            raise RuntimeError(f"no yfinance price for {ticker} on or after {as_of}")
        row = hist.iloc[0]
        idx = hist.index[0].to_pydatetime()
        return PricePoint(ticker.upper(), iso_utc(idx), float(row["Close"]))


def provider_by_name(name: str) -> Provider:
    if name == "fake":
        return FakeProvider()
    if name == "yfinance":
        return YFinanceProvider()
    raise ValueError(f"unknown provider: {name}")
