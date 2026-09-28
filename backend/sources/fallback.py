"""Where the quote and the chain come from when Yahoo's quote summary won't.

Yahoo's crumb-gated endpoints are the only place the app used to ask, so
one refusal blanked the quote, the options, the greeks and everything
written from them, while the chart -- a different Yahoo endpoint, no crumb
-- carried on as if nothing had happened. These are the other doors, each
free and keyless, tried in order:

  quote  Yahoo's chart metadata, then Nasdaq, then Cboe
  chain  Cboe's delayed board: every listed contract in one request,
         already in the rows the pricing code reads

Each answer says which source gave it, so the panel names the one that
actually spoke.
"""

from __future__ import annotations

import re
import threading
import time
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import requests

BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "application/json",
}
TIMEOUT = 12

_LOCK = threading.Lock()
_KEPT: Dict[str, tuple] = {}


def _kept(key: str, ttl: float, make):
    """A few seconds of memory, so the page load and the refresh that
    follows it do not both pull a megabyte from Cboe."""
    hit = _KEPT.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    value = make()
    with _LOCK:
        _KEPT[key] = (time.time(), value)
    return value


def _money(text: Any) -> Optional[float]:
    if text is None:
        return None
    s = str(text).replace("$", "").replace(",", "").replace("%", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def _pair(text: Any) -> tuple:
    """'$351.28/$66.62' or '66.62 - 351.28' -> (low, high)."""
    nums = [_money(p) for p in re.split(r"\s*[/-]\s*(?=\$?\d)", str(text or "")) if p.strip()]
    nums = [n for n in nums if n is not None]
    return (min(nums), max(nums)) if len(nums) == 2 else (None, None)


def _blank(symbol: str) -> Dict[str, Any]:
    return {k: None for k in (
        "exchange", "price", "previous_close", "change", "change_pct", "day_low",
        "day_high", "year_low", "year_high", "volume", "avg_volume", "market_cap",
        "beta", "sector", "industry", "employees", "website", "summary")} | {
        "symbol": symbol.upper(), "name": symbol.upper(), "currency": "USD"}


def _finish(q: Dict[str, Any], source: str) -> Dict[str, Any]:
    price, prev = q.get("price"), q.get("previous_close")
    if price and prev and q.get("change") is None:
        q["change"] = round(price - prev, 4)
        q["change_pct"] = round((price - prev) / prev * 100, 3)
    q["source"] = source
    return q


# ---- quote -----------------------------------------------------------------

def yahoo_chart(symbol: str) -> Optional[Dict[str, Any]]:
    """Yahoo's chart endpoint carries a quote in its metadata and asks for
    no crumb, which is why the chart kept working when nothing else did."""
    r = requests.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                     params={"range": "1d", "interval": "1d"}, headers=BROWSER, timeout=TIMEOUT)
    r.raise_for_status()
    meta = ((r.json().get("chart") or {}).get("result") or [{}])[0].get("meta") or {}
    if not meta.get("regularMarketPrice"):
        return None
    q = _blank(symbol)
    q.update({
        "name": meta.get("longName") or meta.get("shortName") or symbol.upper(),
        "exchange": meta.get("fullExchangeName") or meta.get("exchangeName"),
        "currency": meta.get("currency") or "USD",
        "price": meta.get("regularMarketPrice"),
        "previous_close": meta.get("chartPreviousClose") or meta.get("previousClose"),
        "day_low": meta.get("regularMarketDayLow"),
        "day_high": meta.get("regularMarketDayHigh"),
        "year_low": meta.get("fiftyTwoWeekLow"),
        "year_high": meta.get("fiftyTwoWeekHigh"),
        "volume": meta.get("regularMarketVolume"),
    })
    return _finish(q, "Yahoo Finance chart")


def _nasdaq(symbol: str, what: str) -> Optional[Dict[str, Any]]:
    # Nasdaq files a fund under a different asset class and answers the
    # wrong one with an empty body rather than an error.
    for klass in ("stocks", "etf"):
        r = requests.get(f"https://api.nasdaq.com/api/quote/{symbol}/{what}",
                         params={"assetclass": klass}, headers=BROWSER, timeout=TIMEOUT)
        if r.status_code != 200:
            continue
        data = (r.json() or {}).get("data")
        if data:
            return data
    return None


def nasdaq_extras(symbol: str) -> Dict[str, Any]:
    """Market cap, average volume, sector and a one-year target: what the
    chart metadata leaves out, from Nasdaq's summary. Kept five minutes."""
    def make():
        data = _nasdaq(symbol, "summary") or {}
        s = data.get("summaryData") or {}
        val = lambda k: (s.get(k) or {}).get("value")
        return {
            "market_cap": _money(val("MarketCap")),
            "avg_volume": _money(val("AverageVolume")),
            "sector": val("Sector"),
            "industry": val("Industry"),
            "target": _money(val("OneYrTarget")),
            "previous_close": _money(val("PreviousClose")),
        }
    try:
        return _kept(f"nq-sum:{symbol}", 300, make)
    except Exception:                                       # noqa: BLE001
        return {}


def nasdaq_quote(symbol: str) -> Optional[Dict[str, Any]]:
    data = _nasdaq(symbol, "info")
    if not data:
        return None
    p = data.get("primaryData") or {}
    price = _money(p.get("lastSalePrice"))
    if not price:
        return None
    stats = data.get("keyStats") or {}
    q = _blank(symbol)
    ylo, yhi = _pair((stats.get("fiftyTwoWeekHighLow") or {}).get("value"))
    dlo, dhi = _pair((stats.get("dayrange") or {}).get("value"))
    change = _money(p.get("netChange"))
    q.update({
        "name": data.get("companyName") or symbol.upper(),
        "exchange": data.get("exchange"),
        "price": price,
        "change": change,
        "change_pct": _money(p.get("percentageChange")),
        "previous_close": round(price - change, 4) if change is not None else None,
        "day_low": dlo, "day_high": dhi, "year_low": ylo, "year_high": yhi,
        "volume": _money(p.get("volume")),
    })
    return _finish(q, "Nasdaq")


def _cboe_symbol(symbol: str) -> str:
    # Cboe writes class shares with a dot and indexes with an underscore.
    return ("_" + symbol[1:]) if symbol.startswith("^") else symbol.replace("-", ".")


def _cboe_board(symbol: str) -> Optional[Dict[str, Any]]:
    def make():
        r = requests.get("https://cdn.cboe.com/api/global/delayed_quotes/options/"
                         f"{_cboe_symbol(symbol)}.json", headers=BROWSER, timeout=25)
        if r.status_code != 200:
            return None
        return r.json().get("data")
    return _kept(f"cboe:{symbol}", 20, make)


def cboe_quote(symbol: str) -> Optional[Dict[str, Any]]:
    d = _cboe_board(symbol)
    if not d or not d.get("current_price"):
        return None
    q = _blank(symbol)
    q.update({
        "price": d.get("current_price"),
        "previous_close": d.get("prev_day_close"),
        "change": d.get("price_change"),
        "change_pct": d.get("price_change_percent"),
        "day_low": d.get("low"), "day_high": d.get("high"),
        "volume": d.get("volume"),
    })
    return _finish(q, "Cboe")


def quote(symbol: str) -> Optional[Dict[str, Any]]:
    """The first of the backups that has a price, topped up from Nasdaq's
    summary with what it left out. One refresh asks for the quote twice
    (once for itself, once for the dividend yield), so it is kept briefly."""
    return _kept(f"quote:{symbol}", 10, lambda: _quote(symbol))


def _quote(symbol: str) -> Optional[Dict[str, Any]]:
    for fetch in (yahoo_chart, nasdaq_quote, cboe_quote):
        try:
            q = fetch(symbol)
        except Exception:                                   # noqa: BLE001
            q = None
        if q and q.get("price"):
            break
    else:
        return None
    extra = nasdaq_extras(symbol)
    for k in ("market_cap", "avg_volume", "sector", "industry", "previous_close"):
        if q.get(k) is None and extra.get(k) is not None:
            q[k] = extra[k]
    return _finish(q, q["source"])


# ---- chains ------------------------------------------------------------------

_OCC = re.compile(r"^(.+?)(\d{6})([CP])(\d{8})$")


def cboe_chains(symbol: str) -> Optional[Dict[str, Any]]:
    """Every expiry Cboe lists, as the calls/puts frames yfinance would
    have handed over, so the pricing code cannot tell the difference."""
    import pandas as pd

    d = _cboe_board(symbol)
    if not d or not d.get("options"):
        return None
    spot = d.get("current_price") or 0.0
    by_expiry: Dict[str, Dict[str, List[Dict[str, Any]]]] = {}
    for o in d["options"]:
        m = _OCC.match(o.get("option") or "")
        if not m:
            continue
        ymd, side, strike = m.group(2), m.group(3), int(m.group(4)) / 1000.0
        expiry = f"20{ymd[:2]}-{ymd[2:4]}-{ymd[4:]}"
        is_call = side == "C"
        iv = o.get("iv") or None
        by_expiry.setdefault(expiry, {"calls": [], "puts": []})["calls" if is_call else "puts"].append({
            "contractSymbol": o.get("option"),
            "strike": strike,
            "bid": o.get("bid"),
            "ask": o.get("ask"),
            "lastPrice": o.get("last_trade_price"),
            "volume": o.get("volume"),
            "openInterest": o.get("open_interest"),
            "impliedVolatility": iv,
            "inTheMoney": (spot > strike) if is_call else (spot < strike),
        })
    if not by_expiry:
        return None
    chains = {
        e: SimpleNamespace(
            calls=pd.DataFrame(sorted(v["calls"], key=lambda r: r["strike"])),
            puts=pd.DataFrame(sorted(v["puts"], key=lambda r: r["strike"])))
        for e, v in by_expiry.items()
    }
    return {"spot": spot, "expiries": sorted(chains), "chains": chains}
