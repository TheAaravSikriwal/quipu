"""Everything the four steps read, fetched once and shared.

Each step is arithmetic on these inputs and nothing else, so what a
step says can always be traced back to one of them -- and a source that
is down turns into a named gap on the page instead of a crash.
"""

from __future__ import annotations

import json
import math
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yfinance as yf

from sources import options as O

import paths

CACHE = paths.CACHE
_MEMO: Dict[str, Any] = {}
_LOCK = threading.Lock()


def _memo(key: str, ttl: float, build: Callable[[], Any]) -> Any:
    now = time.time()
    with _LOCK:
        hit = _MEMO.get(key)
        if hit and now - hit[0] < ttl:
            return hit[1]
    value = build()
    with _LOCK:
        _MEMO[key] = (now, value)
    return value


# ---- prices ----------------------------------------------------------------

def daily(symbol: str) -> Optional[Dict[str, List]]:
    """Two years of daily bars: enough for a 200-day average a year back."""
    def build():
        f = yf.Ticker(symbol).history(period="2y", interval="1d", auto_adjust=True)
        if f is None or f.empty:
            return None
        f = f.dropna(subset=["Close"])
        return {
            "date": [d.strftime("%Y-%m-%d") for d in f.index],
            "open": [float(v) for v in f["Open"]],
            "high": [float(v) for v in f["High"]],
            "low": [float(v) for v in f["Low"]],
            "close": [float(v) for v in f["Close"]],
            "volume": [float(v) if v == v else 0.0 for v in f["Volume"]],
        }
    return _memo(f"daily:{symbol}", 900, build)


def info(symbol: str) -> Dict[str, Any]:
    return _memo(f"info:{symbol}", 3600, lambda: yf.Ticker(symbol).info or {})


def eps_trend(symbol: str) -> Optional[Dict[str, Dict[str, float]]]:
    """Consensus EPS now and 7/30/60/90 days ago, per period."""
    def build():
        try:
            f = yf.Ticker(symbol).eps_trend
        except Exception:                                    # noqa: BLE001
            return None
        if f is None or f.empty:
            return None
        out = {}
        for period, row in f.iterrows():
            out[str(period)] = {k: (float(v) if v == v else None)
                                for k, v in row.items() if k != "currency"}
        return out
    return _memo(f"eps:{symbol}", 3600, build)


# ---- peers, for relative valuation ---------------------------------------

def peers(symbol: str) -> Dict[str, Any]:
    """Forward P/E across the stock's industry, from Yahoo's list of the
    industry's largest companies. Cached on disk for a day: fifteen quote
    pages is slow, and an industry's median does not move by the hour."""
    key = info(symbol).get("industryKey")
    if not key:
        return {"industry": None, "peers": []}
    path = CACHE / "peers" / f"{key}.json"
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
        if saved.get("on") == date.today().isoformat():
            return saved
    except (OSError, ValueError):
        pass
    try:
        names = list(yf.Industry(key).top_companies.index[:16])
    except Exception:                                        # noqa: BLE001
        names = []

    def one(t: str) -> Optional[Dict[str, Any]]:
        try:
            i = yf.Ticker(t).info or {}
        except Exception:                                    # noqa: BLE001
            return None
        return {"symbol": t, "name": i.get("shortName"),
                "forward_pe": i.get("forwardPE"), "trailing_pe": i.get("trailingPE")}

    with ThreadPoolExecutor(max_workers=8) as pool:
        rows = [r for r in pool.map(one, names) if r]
    label = info(symbol).get("industry") or key
    # An industry whose largest names are mostly small or loss-making has
    # too few forward P/Es to take a median of (Apple's is "consumer
    # electronics"). The sector's largest companies stand in, and the
    # label says so.
    valid = lambda rs: [r for r in rs if isinstance(r.get("forward_pe"), (int, float)) and r["forward_pe"] > 0]
    sector = info(symbol).get("sectorKey")
    if len(valid(rows)) < 5 and sector:
        try:
            more = list(yf.Sector(sector).top_companies.index[:16])
        except Exception:                                    # noqa: BLE001
            more = []
        with ThreadPoolExecutor(max_workers=8) as pool:
            rows = [r for r in pool.map(one, [m for m in more if m != symbol]) if r]
        label = f"{info(symbol).get('sector') or sector} sector (too few in {label})"
    out = {"industry": label, "key": key,
           "peers": rows, "on": date.today().isoformat()}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out), encoding="utf-8")
    except OSError:
        pass
    return out


# ---- the option board ------------------------------------------------------

def expiries(symbol: str, div: float) -> List[str]:
    b = _memo(f"all_exp:{symbol}", 900,
              lambda: O.fetch_options(symbol, max_expiries=1, div_yield=div))
    return list(b.get("all_expiries") or []) if b.get("available") else []


def board(symbol: str, expiry: str, div: float,
          dividends: Optional[List[Dict]] = None) -> Optional[Dict[str, Any]]:
    """One expiry, priced, with its spot."""
    def build():
        b = O.fetch_options(symbol, max_expiries=1, div_yield=div, only=expiry,
                            dividends=dividends)
        if not b.get("available") or not b.get("expiries"):
            return None
        e = b["expiries"][0]
        return {**e, "spot": b["spot"], "rate": b.get("risk_free_rate"),
                "div_yield": b.get("dividend_yield")}
    return _memo(f"board:{symbol}:{expiry}", 120, build)


def days_to(expiry: str) -> int:
    return (date.fromisoformat(expiry) - O.market_now().date()).days


def expiry_near(all_exp: List[str], days: int, at_least: int = 0) -> Optional[str]:
    """The listed expiry closest to `days` calendar days out."""
    ok = [e for e in all_exp if days_to(e) >= max(at_least, 1)]
    if not ok:
        return None
    return min(ok, key=lambda e: abs(days_to(e) - days))


def expiry_after(all_exp: List[str], days: int) -> Optional[str]:
    """The first listed expiry at least `days` calendar days out."""
    ok = [e for e in all_exp if days_to(e) >= days]
    return ok[0] if ok else None


# ---- the market, for relative strength ------------------------------------

def scan_frame():
    try:
        from screener import store
        return store.frame()
    except Exception:                                        # noqa: BLE001
        return None


# ---- small statistics used by more than one step ---------------------------

def log_returns(closes: List[float]) -> List[float]:
    return [math.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0 and b > 0]


def stdev(xs: List[float]) -> Optional[float]:
    if len(xs) < 2:
        return None
    m = sum(xs) / len(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (len(xs) - 1))


def sma(xs: List[float], n: int, end: Optional[int] = None) -> Optional[float]:
    end = len(xs) if end is None else end
    if end < n:
        return None
    return sum(xs[end - n:end]) / n


def norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))
