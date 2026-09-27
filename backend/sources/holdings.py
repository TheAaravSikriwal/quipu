"""What is actually inside a fund.

Searching an ETF and being shown a price is close to useless. An ETF is
a basket, the basket is the thing you are buying, and the question is
always the same: what is in it, and how much of it is one name?

WHERE THE LIST COMES FROM, AND HOW COMPLETE EACH ONE IS

  The issuer   State Street publishes a daily holdings file for every
               SPDR fund at a URL that differs only by ticker, so the
               whole family -- SPY, DIA, MDY and the sector funds --
               gives up its FULL list. 503 names for SPY, not ten.

  Yahoo        Everything else. It carries the top ten holdings and
               nothing beyond them, which for a broad fund is about a
               third of the money and for a concentrated one can be
               most of it. Either way the panel says which it is
               showing and what share of the fund that covers, because
               "the top ten" and "all of it" are different claims and
               a reader cannot tell them apart from a list alone.

No attempt is made to scrape the issuers that do not publish a
machine-readable file. Invesco refuses automated requests outright and
Vanguard serves a page rather than data; guessing at their holdings
from somewhere else would be inventing a number with an authoritative
look to it.
"""

from __future__ import annotations

import io
import json
import os
import time
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/125 Safari/537.36",
}
TIMEOUT = 25

#: One URL, one substitution, the entire SPDR family.
SSGA = ("https://www.ssga.com/us/en/intermediary/library-content/products/"
        "fund-data/etfs/us/holdings-daily-us-en-{t}.xlsx")

import paths

CACHE_DIR = str(paths.CACHE / "holdings")
TTL = 86400 * 0.5        # the files are daily; half a day is plenty

#: Bumped whenever the shape of a cached record changes.
#:
#: A record written by an older version is missing whatever was added
#: since, and a reader that trusts it gets a KeyError or, worse, a
#: silently absent field. Cheaper to throw the file away than to make
#: every caller defensive about which version wrote it.
SCHEMA = 2


def _cached(symbol: str):
    path = os.path.join(CACHE_DIR, f"{symbol.upper()}.json")
    try:
        if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < TTL:
            with open(path, encoding="utf-8") as fh:
                hit = json.load(fh)
            if hit.get("schema") == SCHEMA:
                return hit
    except Exception:
        pass
    return None


def _store(symbol: str, data: Dict) -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(os.path.join(CACHE_DIR, f"{symbol.upper()}.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({**data, "schema": SCHEMA}, fh)
    except Exception:
        pass


def _num(v) -> Optional[float]:
    try:
        f = float(str(v).replace(",", "").replace("%", ""))
        return None if f != f else f                # NaN
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# the issuer's own file
# --------------------------------------------------------------------------

def _from_ssga(symbol: str) -> Optional[Dict[str, Any]]:
    """The complete list, if State Street publishes one for this ticker."""
    res = requests.get(SSGA.format(t=symbol.lower()), headers=BROWSER, timeout=TIMEOUT)
    if res.status_code != 200 or len(res.content) < 2000:
        return None

    raw = pd.read_excel(io.BytesIO(res.content), header=None)

    # The sheet opens with a few metadata rows, then the real header. Find
    # it by looking for the row that has both a Name and a Ticker column
    # rather than by assuming a fixed offset -- the metadata block has
    # grown a row before now.
    header, asof = None, None
    for i in range(min(15, len(raw))):
        cells = [str(x).strip() for x in raw.iloc[i].tolist()]
        if "Ticker" in cells and "Name" in cells:
            header = i
            break
        if cells and cells[0].startswith("Holdings:"):
            asof = cells[1].replace("As of", "").strip() if len(cells) > 1 else None
    if header is None:
        return None

    df = pd.read_excel(io.BytesIO(res.content), header=header)
    df = df.dropna(how="all")
    if "Ticker" not in df.columns or "Name" not in df.columns:
        return None

    rows: List[Dict[str, Any]] = []
    for _, r in df.iterrows():
        ticker = str(r.get("Ticker", "")).strip()
        name = str(r.get("Name", "")).strip()
        if not ticker or ticker in ("-", "nan") or name in ("", "nan"):
            continue
        weight = _num(r.get("Weight"))
        rows.append({
            "symbol": ticker.replace(".", "-"),     # BRK.B -> BRK-B, as elsewhere
            "name": name,
            "weight": round(weight, 4) if weight is not None else None,
            "sector": (str(r.get("Sector")).strip()
                       if str(r.get("Sector", "")).strip() not in ("-", "nan", "") else None),
        })
    if not rows:
        return None

    rows.sort(key=lambda x: -(x["weight"] or 0))
    return {
        "holdings": rows,
        "count": len(rows),
        "complete": True,
        "as_of": asof,
        "source": "State Street, daily holdings file",
        "source_url": SSGA.format(t=symbol.lower()),
    }


# --------------------------------------------------------------------------
# the fallback
# --------------------------------------------------------------------------

def _from_yahoo(ticker) -> Optional[Dict[str, Any]]:
    """The top ten, which is all Yahoo carries."""
    try:
        fd = ticker.funds_data
        top = fd.top_holdings
    except Exception:
        return None
    if top is None or top.empty:
        return None

    rows = []
    for sym, r in top.iterrows():
        w = _num(r.get("Holding Percent"))
        rows.append({
            "symbol": str(sym).strip().replace(".", "-"),
            "name": str(r.get("Name", "")).strip(),
            # Yahoo gives a fraction; the issuer files give a percentage.
            # One unit for both, or the two sources cannot share a column.
            "weight": round(w * 100, 4) if w is not None else None,
            "sector": None,
        })
    rows.sort(key=lambda x: -(x["weight"] or 0))
    return {
        "holdings": rows,
        "count": len(rows),
        "complete": False,
        "as_of": None,
        "source": "Yahoo Finance",
        "source_url": None,
    }


def _sectors(ticker) -> List[Dict[str, Any]]:
    try:
        sw = ticker.funds_data.sector_weightings or {}
    except Exception:
        return []
    out = []
    for k, v in sw.items():
        f = _num(v)
        if not f:
            continue
        out.append({"sector": str(k).replace("_", " "), "weight": round(f * 100, 2)})
    out.sort(key=lambda x: -x["weight"])
    return out


# --------------------------------------------------------------------------

def fetch(symbol: str, ticker=None) -> Dict[str, Any]:
    """Everything inside one fund, or a flat answer that it is not one."""
    symbol = symbol.strip().upper()
    hit = _cached(symbol)
    if hit is not None:
        return hit

    import yfinance as yf
    ticker = ticker or yf.Ticker(symbol)
    info = {}
    try:
        info = ticker.info or {}
    except Exception:
        pass

    kind = str(info.get("quoteType") or "").upper()
    if kind not in ("ETF", "MUTUALFUND"):
        out = {"available": False, "is_fund": False}
        _store(symbol, out)
        return out

    out: Dict[str, Any] = {
        "available": False,
        "is_fund": True,
        "kind": kind,
        "name": info.get("longName") or info.get("shortName") or symbol,
        "sectors": _sectors(ticker),
        "holdings": [],
        "count": 0,
        "complete": False,
        "covered": None,
        # Always present, so a caller never has to guess whether the
        # keys exist. A commodity trust is a fund that holds bullion
        # rather than companies: there is nothing to list, and that is
        # a fact about the fund rather than a gap in the data.
        "source": None,
        "source_url": None,
        "as_of": None,
        "reason": None,
    }

    found = None
    try:
        found = _from_ssga(symbol)
    except Exception:
        found = None
    if found is None:
        try:
            found = _from_yahoo(ticker)
        except Exception:
            found = None

    if not found:
        out["reason"] = (
            "No list of companies is published for this one in a form we can "
            "read. Commodity and currency funds hold no shares at all; for the "
            "rest, the issuer does not put the file anywhere machine-readable.")
    if found:
        out.update(found)
        out["available"] = True
        # How much of the fund the list actually accounts for. On a
        # complete file this is ~100 and says so; on the top ten it is
        # the honest headline -- ten names covering a third of SPY is a
        # different object from ten names covering all of a sector fund.
        covered = sum(h["weight"] or 0 for h in found["holdings"])
        out["covered"] = round(covered, 2)

    _store(symbol, out)
    return out
