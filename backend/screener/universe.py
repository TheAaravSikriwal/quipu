"""The tradeable universe of US listings.

Straight from the horse's mouth: Nasdaq publishes the official list of every
symbol traded on a US exchange, updated daily, as a pipe-delimited file. No
key, no rate limit, no scraping a web page that will change its markup next
month. About 13,000 rows.

Most of those rows are not things a person trades options on. This module's
job is the filtering: strip the test issues, the warrants, units, rights and
preferred shares, and keep the common stock and the ETFs. What survives is
roughly 8,000 symbols, which is the pool the screener then ranks.
"""

from __future__ import annotations

import csv
import io
import json
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List

SOURCE = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"
CACHE = Path(__file__).resolve().parent.parent / "cache" / "universe.json"
MAX_AGE_S = 24 * 3600          # the file is republished once a day

EXCHANGES = {
    "N": "NYSE",
    "A": "NYSE American",
    "P": "NYSE Arca",
    "Q": "Nasdaq",
    "Z": "Cboe BZX",
    "V": "IEX",
}

# Suffixes Nasdaq appends for share classes that are not ordinary equity.
# A warrant is not a company, it is a claim on one, and it has no options
# chain -- listing them would pad the universe with thousands of dead rows.
JUNK_WORDS = (
    "warrant", "right", " unit", "units", "preferred", "depositary",
    "when issued", "when-issued", "notes due", "%", "convertible",
)

# Geared and inverse products. They are real listings and some are heavily
# traded, but they are a multiple of something else's return, so they win
# every momentum and volatility ranking by construction and tell you nothing
# you could not have read off the underlying. Flagged, and off by default.
GEARED_WORDS = (
    "2x", "3x", "-1x", "1.5x", "ultra", "ultrapro", "leveraged", "bull ",
    "bear ", "inverse", "short ", "daily target",
)


def _looks_tradeable(row: Dict[str, str]) -> bool:
    symbol = (row.get("NASDAQ Symbol") or row.get("Symbol") or "").strip()
    name = (row.get("Security Name") or "").lower()

    if not symbol or row.get("Test Issue") == "Y":
        return False
    # '$' marks preferreds and similar; '.' marks warrant/unit classes in this
    # file. Ordinary class shares (BRK.B) arrive as BRK-B already.
    if "$" in symbol or "." in symbol:
        return False
    if len(symbol) > 5:
        return False
    if any(word in name for word in JUNK_WORDS):
        return False
    return True


def fetch(force: bool = False) -> List[Dict[str, Any]]:
    """The filtered universe, cached on disk for a day."""
    if not force and CACHE.exists():
        try:
            blob = json.loads(CACHE.read_text(encoding="utf-8"))
            if time.time() - blob.get("fetched_at", 0) < MAX_AGE_S:
                return blob["symbols"]
        except Exception:
            pass                      # a corrupt cache is not worth a crash

    req = urllib.request.Request(SOURCE, headers={"User-Agent": "quipu/0.1"})
    raw = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")

    # The last line is a "File Creation Time" footer, not a record.
    body = "\n".join(l for l in raw.splitlines() if l and "File Creation Time" not in l)
    rows = list(csv.DictReader(io.StringIO(body), delimiter="|"))

    out: List[Dict[str, Any]] = []
    for row in rows:
        if not _looks_tradeable(row):
            continue
        symbol = (row.get("NASDAQ Symbol") or row["Symbol"]).strip()
        name = (row.get("Security Name") or "").lower()
        out.append({
            "symbol": symbol,
            "name": (row.get("Security Name") or "").split(" - ")[0].strip(),
            "exchange": EXCHANGES.get((row.get("Listing Exchange") or "").strip(), "?"),
            "etf": row.get("ETF") == "Y",
            "geared": any(w in name for w in GEARED_WORDS),
        })

    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(
        json.dumps({"fetched_at": time.time(), "symbols": out}), encoding="utf-8")
    return out


def symbols(include_etfs: bool = True, include_geared: bool = False) -> List[str]:
    return [s["symbol"] for s in fetch()
            if (include_etfs or not s["etf"])
            and (include_geared or not s["geared"])]


def index() -> Dict[str, Dict[str, Any]]:
    """symbol -> {name, exchange, etf}, for decorating scan results."""
    return {s["symbol"]: s for s in fetch()}


if __name__ == "__main__":
    t = time.time()
    rows = fetch(force=True)
    etfs = sum(1 for r in rows if r["etf"])
    geared = sum(1 for r in rows if r["geared"])
    print(f"{len(rows)} symbols in {time.time() - t:.1f}s  "
          f"({etfs} ETFs, {geared} geared/inverse)")
    print(f"default universe: {len(symbols())}")
    for r in rows[:5]:
        print(" ", r)
