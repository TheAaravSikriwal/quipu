"""SEC EDGAR -- filings straight from the source. Free, official, no API key.

This is the highest-trust data in the whole app: it is what the company legally
told the regulator, not what a journalist wrote about it. An 8-K appearing here
before any outlet has covered it is exactly the kind of edge the app is for.

SEC requires a declared User-Agent with contact details. Set SEC_USER_AGENT to
your own "name email" string -- the default below is a placeholder and they can
and do rate-limit generic agents.
"""

from __future__ import annotations

import os
import threading
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import requests

UA = os.getenv("SEC_USER_AGENT", "quipu personal-research contact@example.com")
HEADERS = {"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}
TIMEOUT = 20

# What each form actually means, so the UI never shows a bare form number.
FORM_MEANING = {
    "8-K": "Material event -- something happened the market must know now",
    "10-Q": "Quarterly report",
    "10-K": "Annual report",
    "4": "Insider bought or sold shares",
    "3": "New insider declared a holding",
    "5": "Annual insider summary",
    "SC 13D": "Someone took an activist stake above 5%",
    "SC 13G": "Someone took a passive stake above 5%",
    "13F-HR": "Institution disclosed its quarterly holdings",
    "S-1": "Registration for a new share offering",
    "S-3": "Shelf registration -- may sell shares later",
    "424B5": "Pricing of a share offering",
    "DEF 14A": "Proxy statement -- pay, board, shareholder votes",
    "SC 13D/A": "Amendment to an activist stake",
    "6-K": "Foreign issuer interim report",
    "20-F": "Foreign issuer annual report",
}

_ticker_map: Optional[Dict[str, Dict[str, Any]]] = None
_map_lock = threading.Lock()


def _load_ticker_map() -> Dict[str, Dict[str, Any]]:
    """Ticker -> CIK. Fetched once per process; the file is ~1MB."""
    global _ticker_map
    with _map_lock:
        if _ticker_map is not None:
            return _ticker_map
        response = requests.get(
            "https://www.sec.gov/files/company_tickers.json",
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        _ticker_map = {
            row["ticker"].upper(): {
                "cik": str(row["cik_str"]).zfill(10),
                "name": row["title"],
            }
            for row in response.json().values()
        }
        return _ticker_map


def lookup_cik(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        return _load_ticker_map().get(symbol.upper())
    except Exception:
        return None


def fetch_filings(symbol: str, limit: int = 30) -> Dict[str, Any]:
    """Recent filings, newest first, each with a plain-English label."""
    company = lookup_cik(symbol)
    if not company:
        return {"available": False, "reason": f"{symbol} not found in EDGAR", "filings": []}

    cik = company["cik"]
    response = requests.get(
        f"https://data.sec.gov/submissions/CIK{cik}.json",
        headers=HEADERS,
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()

    recent = (payload.get("filings") or {}).get("recent") or {}
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    dates = recent.get("filingDate", [])
    docs = recent.get("primaryDocument", [])
    descriptions = recent.get("primaryDocDescription", [])

    today = datetime.now(timezone.utc).date()
    filings: List[Dict[str, Any]] = []

    for i in range(min(limit, len(forms))):
        accession = accessions[i].replace("-", "")
        filed = dates[i]
        try:
            age_days = (today - datetime.strptime(filed, "%Y-%m-%d").date()).days
        except Exception:
            age_days = None

        filings.append(
            {
                "form": forms[i],
                "means": FORM_MEANING.get(forms[i], "Regulatory filing"),
                "filed": filed,
                "age_days": age_days,
                "description": descriptions[i] if i < len(descriptions) else None,
                "url": (
                    f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                    f"{accession}/{docs[i]}"
                )
                if i < len(docs) and docs[i]
                else f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
            }
        )

    insider = [f for f in filings if f["form"] in ("3", "4", "5")]
    material = [f for f in filings if f["form"].startswith("8-K")]

    return {
        "available": True,
        "cik": cik,
        "name": payload.get("name") or company["name"],
        "sic_description": payload.get("sicDescription"),
        "fiscal_year_end": payload.get("fiscalYearEnd"),
        "filings": filings,
        "insider_count_recent": len(insider),
        "material_events_recent": len(material),
        # A burst of 8-Ks or Form 4s inside a week is worth a second look.
        "hot": any(f["age_days"] is not None and f["age_days"] <= 7 for f in material),
    }
