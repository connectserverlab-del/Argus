"""
Generate 100 synthetic historical events with realistic patterns for
testing Pegasus + Athena together. 

Design decisions:
- Concentrate events across fewer tickers so sector-level aggregation 
  has enough events (10+) to compute valid signal scores
- Bake in real patterns so Pegasus produces non-trivial output:
    large-cap tech layoff   -> slightly positive  (+1% to +4% excess)
    small-cap tech layoff   -> strongly negative  (-8% to -3% excess)  
    large-cap retail layoff -> mixed              (-2% to +2% excess)
    small-cap retail layoff -> strongly negative  (-12% to -4% excess)
    store closure           -> strongly negative  (-15% to -5% excess)
    hiring surge            -> moderately positive(+2% to +8% excess)
- Include 8 events with missing price data (delisted simulation)
- Spread dates 2015-2023 realistically
"""
import json
import random
import math
from datetime import datetime, timedelta, timezone

random.seed(42)

def iso(dt):
    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')

def rand_date(start_year=2015, end_year=2023):
    start = datetime(start_year, 1, 1, tzinfo=timezone.utc)
    end = datetime(end_year, 12, 31, tzinfo=timezone.utc)
    return start + timedelta(seconds=random.randint(0, int((end-start).total_seconds())))

def accession(cik, year, seq):
    return f"{cik:010d}-{str(year)[2:]}-{seq:06d}"

def source_url(cik, accn):
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn.replace('-','')}/"

def compute_outcome(event_type, sector, market_cap, horizon, missing=False):
    if missing:
        return {"horizon_days": horizon, "data_missing": True,
                "excess_return_pct": None, "asset_return_pct": None,
                "spy_return_pct": None, "entry_price": None, "exit_price": None}
    
    # Pattern table — baked in signal patterns
    patterns = {
        ("layoff",       "tech",   "large"): (1.0,  4.0),
        ("layoff",       "tech",   "small"): (-8.0, -3.0),
        ("layoff",       "retail", "large"): (-2.0,  2.0),
        ("layoff",       "retail", "small"): (-12.0,-4.0),
        ("layoff",       "energy", "large"): (-3.0,  1.0),
        ("layoff",       "energy", "small"): (-6.0, -2.0),
        ("layoff",       "health", "large"): (-1.0,  3.0),
        ("layoff",       "health", "small"): (-5.0, -1.0),
        ("layoff",       "finance","large"): (0.0,   3.0),
        ("layoff",       "finance","small"): (-4.0,  0.0),
        ("store_closure","retail", "large"): (-3.0, -1.0),
        ("store_closure","retail", "small"): (-15.0,-5.0),
        ("hiring_surge", "tech",   "large"): (2.0,   6.0),
        ("hiring_surge", "tech",   "small"): (1.0,   5.0),
        ("hiring_surge", "retail", "large"): (1.0,   4.0),
        ("hiring_surge", "retail", "small"): (0.5,   4.0),
        ("hiring_surge", "health", "large"): (1.5,   5.0),
        ("hiring_surge", "health", "small"): (1.0,   4.5),
    }
    key = (event_type, sector, market_cap)
    lo, hi = patterns.get(key, (-3.0, 3.0))
    
    # Scale effect with horizon — longer horizon = stronger signal
    scale = {10: 0.3, 30: 0.6, 60: 1.0, 90: 1.2}[horizon]
    excess = random.uniform(lo * scale, hi * scale)
    excess = round(excess + random.gauss(0, 1.5), 3)  # add noise
    
    entry = round(random.uniform(20, 400), 2)
    spy_ret = round(random.uniform(-3, 4), 3)
    asset_ret = round(spy_ret + excess, 3)
    exit_p = round(entry * (1 + asset_ret/100), 2)
    
    return {
        "horizon_days": horizon,
        "data_missing": False,
        "excess_return_pct": round(excess, 3),
        "asset_return_pct": round(asset_ret, 3),
        "spy_return_pct": round(spy_ret, 3),
        "entry_price": entry,
        "exit_price": exit_p,
    }

# Ticker universe — concentrated so sector aggregation has enough events
TICKERS = {
    "tech": {
        "large": [
            ("AAPL", 320193, "Apple Inc"),
            ("MSFT", 789019, "Microsoft Corp"),
            ("GOOGL",1652044,"Alphabet Inc"),
            ("META", 1326801,"Meta Platforms"),
        ],
        "small": [
            ("BIGC", 1626251,"BigCommerce"),
            ("APPN", 1441264,"Appian Corp"),
            ("TASK", 1797033,"TaskUs Inc"),
            ("HUBS", 1404655,"HubSpot Inc"),
        ]
    },
    "retail": {
        "large": [
            ("WMT",  104169, "Walmart Inc"),
            ("TGT",  27419,  "Target Corp"),
            ("HD",   354950, "Home Depot"),
            ("LOW",  60667,  "Lowes Companies"),
        ],
        "small": [
            ("PRTY", 1592058,"Party City"),
            ("TLRD", 884217, "Tailored Brands"),
            ("CATO", 18255,  "Cato Corp"),
            ("FIVE", 1177609,"Five Below"),
        ]
    },
    "health": {
        "large": [
            ("JNJ",  200406, "Johnson & Johnson"),
            ("PFE",  78003,  "Pfizer Inc"),
        ],
        "small": [
            ("SUPN", 1356093,"Supernus Pharma"),
            ("CHRS", 1372514,"Coherus BioSciences"),
        ]
    },
    "energy": {
        "large": [
            ("XOM",  34088,  "ExxonMobil"),
            ("CVX",  93410,  "Chevron Corp"),
        ],
        "small": [
            ("CDEV", 1389170,"Centennial Dev"),
            ("ESTE", 1628553,"Earthstone Energy"),
        ]
    },
    "finance": {
        "large": [
            ("JPM",  19617,  "JPMorgan Chase"),
            ("BAC",  70858,  "Bank of America"),
        ],
        "small": [
            ("ECPG", 1084201,"Encore Capital"),
            ("PFSI", 1464790,"PennyMac Financial"),
        ]
    }
}

# Event type distribution per sector
EVENT_DIST = {
    "tech":    [("layoff",60),("hiring_surge",40)],
    "retail":  [("layoff",40),("store_closure",40),("hiring_surge",20)],
    "health":  [("layoff",60),("hiring_surge",40)],
    "energy":  [("layoff",70),("hiring_surge",30)],
    "finance": [("layoff",70),("hiring_surge",30)],
}

def pick_event_type(sector):
    dist = EVENT_DIST[sector]
    choices, weights = zip(*dist)
    return random.choices(choices, weights=weights)[0]

def pick_ticker(sector, cap):
    return random.choice(TICKERS[sector][cap])

# Generate events — target distribution:
# ~40 large cap, ~60 small cap
# ~60 layoff, ~20 store_closure, ~20 hiring_surge
# 8 with missing price data
TARGET = 100
MISSING_IDS = set(random.sample(range(TARGET), 8))

events = []
seq_counter = {}

# Force enough events per sector/cap combo for meaningful stats
# Large tech: 15, Small tech: 15, Large retail: 12, Small retail: 18
# Health: 12, Energy: 10, Finance: 8 = ~90, pad to 100
schedule = [
    ("tech",    "large", 15),
    ("tech",    "small", 15),
    ("retail",  "large", 12),
    ("retail",  "small", 20),
    ("health",  "large",  6),
    ("health",  "small",  6),
    ("energy",  "large",  5),
    ("energy",  "small",  5),
    ("finance", "large",  8),
    ("finance", "small",  8),
]

idx = 0
for sector, cap, n in schedule:
    for _ in range(n):
        ticker, cik, company = pick_ticker(sector, cap)
        event_type = pick_event_type(sector)
        
        # store_closure only makes sense for retail
        if event_type == "store_closure" and sector != "retail":
            event_type = "layoff"
        
        event_date = rand_date()
        seq = seq_counter.get(cik, 0) + 1
        seq_counter[cik] = seq
        accn = accession(cik, event_date.year, seq)
        
        is_missing = idx in MISSING_IDS
        
        outcomes = {}
        for h in [10, 30, 60, 90]:
            outcomes[str(h)] = compute_outcome(
                event_type, sector, cap, h, missing=is_missing
            )
        
        pct = round(random.uniform(3, 18), 1) if event_type == "layoff" else None
        
        detail_templates = {
            "layoff": f"The Company announced a reduction in force affecting approximately {pct}% of its global workforce as part of a restructuring initiative.",
            "store_closure": f"Management approved the closure of {random.randint(5,80)} underperforming store locations as part of its strategic optimization plan.",
            "hiring_surge": f"The Company announced plans to hire approximately {random.randint(200,5000)} employees over the next 12 months to support accelerating growth.",
        }
        
        events.append({
            "id": idx + 1,
            "ticker": ticker,
            "sector": sector,
            "market_cap": cap,
            "company_name": company,
            "event_type": event_type,
            "event_date": iso(event_date),
            "accession_number": accn,
            "source_url": source_url(cik, accn),
            "event_detail": detail_templates[event_type],
            "pct_workforce": pct,
            "outcomes": outcomes,
            "note": "SYNTHETIC DATA — for pipeline testing only"
        })
        idx += 1

random.shuffle(events)
for i, e in enumerate(events):
    e["id"] = i + 1

output = {
    "generated_at": iso(datetime.now(timezone.utc)),
    "n_events": len(events),
    "warning": "SYNTHETIC DATA — all prices, dates, tickers, and outcomes are fabricated for pipeline testing. Do not use for real investment decisions.",
    "signal_patterns_baked_in": {
        "large_cap_tech_layoff":    "slightly positive  (+1% to +4% excess at 60d)",
        "small_cap_tech_layoff":    "strongly negative  (-8% to -3% excess at 60d)",
        "large_cap_retail_layoff":  "mixed              (-2% to +2% excess at 60d)",
        "small_cap_retail_layoff":  "strongly negative  (-12% to -4% excess at 60d)",
        "store_closure_retail":     "strongly negative  (-15% to -5% excess at 60d)",
        "hiring_surge_all":         "moderately positive(+2% to +8% excess at 60d)",
        "missing_data_events":      "8 events simulate delisted/unavailable tickers",
    },
    "sector_distribution": {},
    "events": events
}

from collections import Counter
output["sector_distribution"] = dict(Counter(
    f"{e['sector']}/{e['market_cap']}/{e['event_type']}" for e in events
))

with open('argus/synthetic_events.json', 'w') as f:
    json.dump(output, f, indent=2)

print(f"Generated {len(events)} events")
print("Distribution:")
for k,v in sorted(output['sector_distribution'].items()):
    print(f"  {k}: {v}")
