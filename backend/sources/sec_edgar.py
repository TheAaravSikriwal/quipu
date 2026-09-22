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
from datetime import date, datetime, timedelta, timezone
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


#: What an 8-K item number actually means, and how much it matters.
#:
#: An 8-K is how a company tells the market something happened between
#: scheduled reports, and the item number says what. It is the single
#: most informative field EDGAR publishes and it is a two-digit code:
#: "2.02" is the earnings release, "4.02" is the company saying its own
#: past accounts cannot be relied on. Both arrive as an 8-K, and without
#: the code they look identical in a list.
ITEM_MEANING = {
    "1.01": ("Signed a material agreement", 2),
    "1.02": ("Terminated a material agreement", 2),
    "1.03": ("Bankruptcy or receivership", 3),
    "2.01": ("Completed an acquisition or disposal", 3),
    "2.02": ("Earnings release", 3),
    "2.03": ("Took on a material financial obligation", 2),
    "2.04": ("An obligation has been accelerated", 3),
    "2.05": ("Restructuring or exit costs", 2),
    "2.06": ("Wrote down assets", 3),
    "3.01": ("Delisting notice or listing-rule failure", 3),
    "3.02": ("Sold shares without registering them", 2),
    "3.03": ("Changed shareholder rights", 2),
    "4.01": ("Changed auditor", 3),
    "4.02": ("Past accounts cannot be relied on", 3),
    "5.01": ("Change of control", 3),
    "5.02": ("Director or officer came or went", 2),
    "5.03": ("Amended its articles or bylaws", 1),
    "5.07": ("Shareholder vote results", 1),
    "5.08": ("Shareholder nomination deadline", 1),
    "7.01": ("Disclosure to the market (Reg FD)", 1),
    "8.01": ("Other events", 1),
    "9.01": ("Financial statements and exhibits", 0),
}

#: How long after a period ends the report is legally due. The bracket a
#: company sits in is published in its own submissions file, so this is a
#: real deadline rather than an estimate of one -- the only forward date
#: on the page that is a legal obligation instead of a habit.
DEADLINES = {
    "large accelerated filer": {"10-K": 60, "10-Q": 40},
    "accelerated filer": {"10-K": 75, "10-Q": 40},
}
DEADLINE_DEFAULT = {"10-K": 90, "10-Q": 45}


def _items(raw: str) -> List[Dict[str, Any]]:
    """Decode the comma-separated item list on an 8-K."""
    out = []
    for code in (raw or "").split(","):
        code = code.strip()
        if not code:
            continue
        label, weight = ITEM_MEANING.get(code, (None, 1))
        out.append({"code": code,
                    "means": label or f"Item {code}",
                    "weight": weight,
                    "known": label is not None})
    return sorted(out, key=lambda i: -i["weight"])


def _market_holidays(year: int) -> set:
    """The holiday calendar already built for pricing."""
    try:
        from .options import market_holidays
        return set(market_holidays(year))
    except Exception:
        return set()


def _is_year_end(when: date, fye: Optional[str], slack: int = 8) -> bool:
    """Whether a date is effectively the company's financial year end.

    fye arrives as MMDD. Compared with a few days of slack because a
    52/53-week filer's year end moves around inside a fortnight.
    """
    if not fye or len(fye) != 4:
        return False
    try:
        month, day = int(fye[:2]), int(fye[2:])
    except ValueError:
        return False
    for year in (when.year - 1, when.year, when.year + 1):
        try:
            if abs((when - date(year, month, day)).days) <= slack:
                return True
        except ValueError:
            continue
    return False


def _next_due(category: Optional[str], form: str, last_period: Optional[str],
              fye: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """When the next report of this kind is due, from the last one filed."""
    if not last_period:
        return None
    try:
        end = datetime.strptime(last_period, "%Y-%m-%d").date()
    except ValueError:
        return None

    table = DEADLINES.get((category or "").strip().lower(), DEADLINE_DEFAULT)
    days = table.get(form, DEADLINE_DEFAULT[form])

    # The next period ends about a quarter after the last one. Stepping in
    # quarters rather than adding a fixed 91 days keeps a 52/53-week filer
    # from drifting a week out over a year.
    step = 365 if form == "10-K" else 91
    nxt = end + timedelta(days=step)
    today = date.today()

    for _ in range(12):
        # There is no fourth-quarter 10-Q: that period is reported inside
        # the annual accounts. Apple's next quarter lands on its year end,
        # and projecting a 10-Q there invented a filing that is never made
        # and buried the 10-K that actually is.
        if form == "10-Q" and _is_year_end(nxt, fye):
            nxt += timedelta(days=step)
            continue
        if nxt + timedelta(days=days) < today:
            nxt += timedelta(days=step)
            continue
        break

    # Exchange Act Rule 0-3: a due date that lands on a Saturday, Sunday
    # or federal holiday rolls to the next business day. Without this the
    # panel printed "10-Q due Sunday 8 November", which is not a date
    # anything is ever due on.
    due = nxt + timedelta(days=days)
    while due.weekday() > 4 or due in _market_holidays(due.year):
        due += timedelta(days=1)

    return {"period_end": nxt.isoformat(),
            "due": due.isoformat(),
            "window_days": days,
            "form": form,
            "category": category or "filer"}


def fetch_calendar(symbol: str) -> Dict[str, Any]:
    """What the company has filed lately, and what it owes next.

    Two things the rest of the app could not see. What just happened --
    an 8-K's item codes say whether it was the quarterly numbers, a
    departing chief executive or an admission that last year's accounts
    were wrong. And what is owed -- a company in a known filer bracket
    has a statutory deadline for its next 10-Q, which is the only
    forward date in this app that is a legal obligation rather than a
    pattern someone has noticed.
    """
    company = lookup_cik(symbol)
    if not company:
        return {"available": False, "reason": f"{symbol} not found in EDGAR"}

    cik = company["cik"]
    res = requests.get(f"https://data.sec.gov/submissions/CIK{cik}.json",
                       headers=HEADERS, timeout=TIMEOUT)
    res.raise_for_status()
    payload = res.json()
    rec = (payload.get("filings") or {}).get("recent") or {}

    forms = rec.get("form", [])
    n = len(forms)

    def col(name):
        v = rec.get(name, [])
        return v + [None] * (n - len(v))

    filed, period = col("filingDate"), col("reportDate")
    items, accn = col("items"), col("accessionNumber")
    doc = col("primaryDocument")

    def url(i):
        if not accn[i]:
            return None
        plain = accn[i].replace("-", "")
        if doc[i]:
            return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{plain}/{doc[i]}"
        return f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/{plain}/{accn[i]}-index.htm"

    today = date.today()
    recent: List[Dict[str, Any]] = []
    last_q = last_k = last_earnings = None

    for i in range(n):
        form = forms[i]
        if form in ("10-Q", "10-K") and period[i]:
            if form == "10-Q" and not last_q:
                last_q = period[i]
            if form == "10-K" and not last_k:
                last_k = period[i]

        if form.startswith("8-K"):
            decoded = _items(items[i])
            if any(d["code"] == "2.02" for d in decoded) and not last_earnings:
                last_earnings = filed[i]

        if form not in ("8-K", "8-K/A", "10-Q", "10-K", "S-1", "S-3", "424B5", "SC 13D"):
            continue
        try:
            age = (today - datetime.strptime(filed[i], "%Y-%m-%d").date()).days
        except Exception:
            age = None
        if age is None or age > 180:
            continue

        decoded = _items(items[i]) if form.startswith("8-K") else []
        headline = (decoded[0]["means"] if decoded
                    else FORM_MEANING.get(form, "Regulatory filing"))
        recent.append({
            "form": form, "filed": filed[i], "period": period[i],
            "age_days": age, "items": decoded, "headline": headline,
            "weight": max([d["weight"] for d in decoded], default=1),
            "url": url(i),
        })
        if len(recent) >= 12:
            break

    category = payload.get("category")
    fye = payload.get("fiscalYearEnd")
    q_due = _next_due(category, "10-Q", last_q, fye)
    k_due = _next_due(category, "10-K", last_k, fye)

    # Whichever is owed first is the one that matters; a reader does not
    # need two deadlines to work out which comes next.
    due = [d for d in (q_due, k_due) if d]
    next_report = min(due, key=lambda d: d["due"]) if due else None

    return {
        "available": True,
        "cik": cik,
        "category": category,
        "fiscal_year_end": fye,
        "recent": recent,
        "last_earnings_8k": last_earnings,
        "next_10q": q_due,
        "next_10k": k_due,
        "next_report": next_report,
        "source_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}",
    }


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
