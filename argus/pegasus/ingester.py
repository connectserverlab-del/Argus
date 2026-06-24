"""SEC EDGAR layoff-event ingester for Pegasus."""
from __future__ import annotations

import json, re, sqlite3, time
from datetime import date
from urllib.parse import quote_plus
from urllib.request import Request, urlopen

from argus.pegasus import init_pegasus_db

USER_AGENT = "Argus Capital Lab research@argus.com"
SEC_BASE = "https://efts.sec.gov/LATEST/search-index"
PHRASES = ['"reduction in force" "layoff"', '"workforce reduction"', '"reduction in workforce"', '"eliminate positions"']
_last_request = 0.0


def sec_get_json(url: str) -> dict:
    global _last_request
    wait = max(0.0, 0.11 - (time.monotonic() - _last_request))
    if wait:
        time.sleep(wait)
    with urlopen(Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"}), timeout=30) as resp:
        data = resp.read().decode("utf-8", errors="replace")
    _last_request = time.monotonic()
    return json.loads(data)


def _source_url(hit: dict) -> str:
    src = hit.get("_source", hit)
    if src.get("linkToFilingDetails"):
        return "https://www.sec.gov" + src["linkToFilingDetails"]
    cik = str(src.get("ciks", [src.get("cik", "")])[0]).lstrip("0")
    adsh = (src.get("adsh") or src.get("accessionNo") or "").replace("-", "")
    acc = src.get("adsh") or src.get("accessionNo") or ""
    doc = src.get("fileName") or "index.htm"
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{adsh}/{doc or acc + '-index.htm'}"


def search_layoff_filings(start_date: str | date, end_date: str | date) -> list[dict]:
    found: dict[str, dict] = {}
    for phrase in PHRASES:
        url = f"{SEC_BASE}?q={quote_plus(phrase)}&forms=8-K&dateRange=custom&startdt={start_date}&enddt={end_date}"
        data = sec_get_json(url)
        hits = data.get("hits", {}).get("hits", []) if isinstance(data.get("hits"), dict) else data.get("hits", [])
        print(f"  Searched: {phrase} -> {len(hits):,} filings")
        for hit in hits:
            src = hit.get("_source", hit)
            acc = src.get("adsh") or src.get("accessionNo") or src.get("accession_number")
            if acc:
                found[str(acc)] = {"raw": src, "accession_number": str(acc), "source_url": _source_url(src), "cik": str((src.get("ciks") or [src.get("cik", "")])[0]), "event_date": src.get("file_date") or src.get("filedAt") or src.get("period_ending")}
    return list(found.values())


def resolve_ticker(cik: str, conn: sqlite3.Connection) -> str | None:
    init_pegasus_db(conn)
    data = sec_get_json("https://www.sec.gov/files/company_tickers.json")
    target = str(cik).lstrip("0")
    for item in data.values():
        if str(item.get("cik_str", "")).lstrip("0") == target:
            return str(item.get("ticker", "")).upper() or None
    return None


def extract_pct_workforce(text: str) -> float | None:
    pattern = re.compile(r"(?:layoff|workforce|reduction|positions).{0,80}?(\d+(?:\.\d+)?)\s*%|(?:\d+(?:\.\d+)?)\s*%.{0,80}?(?:layoff|workforce|reduction|positions)", re.I | re.S)
    m = pattern.search(text or "")
    if not m:
        return None
    nums = re.findall(r"\d+(?:\.\d+)?", m.group(0))
    return float(nums[0]) if nums else None


def ingest_events(conn: sqlite3.Connection, start_date: str, end_date: str) -> dict[str, int]:
    init_pegasus_db(conn)
    filings = search_layoff_filings(start_date, end_date)
    resolved = existed = stored = 0
    for f in filings:
        ticker = resolve_ticker(f["cik"], conn)
        if not ticker or not f.get("source_url"):
            continue
        resolved += 1
        detail = json.dumps(f.get("raw", {}))[:1000]
        cur = conn.execute("INSERT OR IGNORE INTO historical_events (ticker,event_type,event_date,source_url,accession_number,event_detail,pct_workforce) VALUES (?,?,?,?,?,?,?)", (ticker, "layoff", f.get("event_date") or start_date, f["source_url"], f["accession_number"], detail, extract_pct_workforce(detail)))
        if cur.rowcount:
            stored += 1
        else:
            existed += 1
    print(f"  Resolved to tickers: {resolved:,} events\n  Already existed: {existed:,}\n  New events stored: {stored:,}")
    return {"filings": len(filings), "resolved": resolved, "existed": existed, "stored": stored}
