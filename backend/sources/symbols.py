"""Find a ticker from a company name.

Nobody remembers that Alphabet is GOOGL and Meta is META but Berkshire is
BRK-B. Yahoo's search endpoint resolves plain names, is free and needs no key.
"""

from __future__ import annotations

from typing import Any, Dict, List

import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) quipu/0.1"
TIMEOUT = 10

# Equities and funds only -- currencies and futures would just be noise here.
WANTED = {"EQUITY", "ETF", "MUTUALFUND", "INDEX"}


def search(query: str, limit: int = 8) -> List[Dict[str, Any]]:
    """Resolve a name or partial ticker to candidate symbols, best first."""
    query = (query or "").strip()
    if not query:
        return []

    response = requests.get(
        "https://query2.finance.yahoo.com/v1/finance/search",
        params={
            "q": query,
            "quotesCount": limit * 2,
            "newsCount": 0,
            "listsCount": 0,
        },
        headers={"User-Agent": UA},
        timeout=TIMEOUT,
    )
    response.raise_for_status()

    out: List[Dict[str, Any]] = []
    for row in response.json().get("quotes", []):
        kind = (row.get("quoteType") or "").upper()
        symbol = row.get("symbol")
        if not symbol or kind not in WANTED:
            continue
        out.append(
            {
                "symbol": symbol,
                "name": row.get("longname") or row.get("shortname") or symbol,
                "exchange": row.get("exchDisp") or row.get("exchange"),
                "type": kind.title(),
                # An exact ticker match should always win over a name match.
                "exact": symbol.upper() == query.upper(),
            }
        )

    out.sort(key=lambda r: (not r["exact"], r["type"] != "Equity"))
    return out[:limit]
