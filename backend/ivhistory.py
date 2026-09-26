"""A year of this stock's options, rebuilt from what they actually traded at.

Three series, one point per session, each defined the same way every day
so that today can be ranked against them:

  IV30   Constant-maturity 30-day at-the-money implied volatility. On each
         session, the two standard monthly expiries either side of 30 days
         are found, the at-the-money call and put on each are solved for
         IV from their closing prices, and total variance is interpolated
         to exactly 30 calendar days. This is what "IV" means in IV Rank.

  RR25   The 25-delta risk reversal: IV of the 25-delta call minus IV of
         the 25-delta put, on the monthly nearest 30 days. Negative is
         normal for a stock; what is read is where today sits against it.

  PC     Put volume over call volume on the two front monthlies, strikes
         within 25% of the share price. A fixed definition rather than
         "everything listed", because the weeklies on offer changed over
         the year and a ratio over a changing set of contracts is not the
         same ratio twice.

Prices are Alpaca daily closes: the last trade of the session, not a
quote midpoint. On a liquid at-the-money contract those are the same
thing to within a few cents; a session where either contract did not
trade is skipped rather than filled.

The rate and dividend yield are today's, applied to every past day. The
error that introduces is a fraction of a vol point, far inside the range
IV Rank is measuring.
"""

from __future__ import annotations

import json
import math
import threading
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sources import alpaca as A
from sources import options as O

CACHE = Path(__file__).resolve().parent / "cache" / "ivhist"
LOOKBACK = 252          # sessions in the ranking window
PC_LOOKBACK = 60        # sessions in the put/call average
TARGET_DAYS = 30        # constant maturity, calendar days
BAND = (0.75, 1.30)     # strike band listed around each session's price


# ---- the calendar ---------------------------------------------------------

def _third_friday(y: int, m: int) -> date:
    d = date(y, m, 15)
    d += timedelta(days=(4 - d.weekday()) % 7)
    # The market shut on the third Friday (Good Friday, in practice)
    # moves the expiry to the Thursday before it.
    return d - timedelta(days=1) if d in O.market_holidays(y) else d


def _monthlies(start: date, end: date) -> List[date]:
    out, y, m = [], start.year, start.month
    while date(y, m, 1) <= end:
        out.append(_third_friday(y, m))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return [d for d in out if start <= d <= end]


def _years(d: date, expiry: date) -> float:
    """Trading time, the convention every price in the app uses."""
    n = O.trading_days(datetime(d.year, d.month, d.day), datetime(expiry.year, expiry.month, expiry.day))
    return max(n, 1) / 252.0


def _pair(d: date, expiries: List[date]) -> List[date]:
    """The expiries either side of 30 days, or the one just past it when the
    nearer is too close to expiry to price sensibly."""
    later = [e for e in expiries if (e - d).days >= TARGET_DAYS]
    earlier = [e for e in expiries if 7 <= (e - d).days < TARGET_DAYS]
    if not later:
        return []
    return ([earlier[-1]] if earlier else []) + [later[0]]


# ---- the solve ------------------------------------------------------------

def _iv(price: Optional[float], spot: float, strike: float, t: float,
        rate: float, call: bool, q: float) -> Optional[float]:
    if not price or price <= 0:
        return None
    return O.implied_vol(price, spot, strike, t, rate, call, q)


def _delta(spot: float, strike: float, t: float, vol: float, rate: float,
           call: bool, q: float) -> float:
    d1 = (math.log(spot / strike) + (rate - q + 0.5 * vol * vol) * t) / (vol * math.sqrt(t))
    n = 0.5 * (1 + math.erf(d1 / math.sqrt(2)))
    return math.exp(-q * t) * (n if call else n - 1)


def _strike_at_delta(spot: float, t: float, vol: float, rate: float, q: float,
                     call: bool) -> float:
    """Where a 25-delta option would sit, from the at-the-money vol.

    Only a first guess -- the contract nearest it is then solved for its
    own IV and its own delta checked, since the smile means the true
    25-delta strike is not where a flat vol puts it.
    """
    z = 0.6745  # N^-1(0.75)
    drift = (rate - q + 0.5 * vol * vol) * t
    return spot * math.exp(drift + (z if call else -z) * vol * math.sqrt(t))


def build(symbol: str, rate: float, div_yield: float = 0.0,
          today: Optional[date] = None) -> Dict[str, Any]:
    symbol = symbol.upper()
    q = div_yield or 0.0
    today = today or O.market_now().date()
    start = today - timedelta(days=400)

    spots = A.stock_bars(symbol, (start - timedelta(days=7)).isoformat(), today.isoformat())
    sessions = sorted(date.fromisoformat(k) for k in spots)
    sessions = [d for d in sessions if d >= start][-LOOKBACK:]
    if len(sessions) < 40:
        return {"symbol": symbol, "status": "unavailable",
                "why": "not enough share-price history on Alpaca"}
    spot = {d: spots[d.isoformat()] for d in sessions}

    # Which monthly each session needs, and the band of strikes around the
    # price while it needed it.
    candidates = _monthlies(sessions[0], today + timedelta(days=90))
    listed: Dict[date, List[Dict[str, Any]]] = {}

    def listing(e: date, lo: float, hi: float) -> List[Dict[str, Any]]:
        if e not in listed:
            listed[e] = A.contracts(symbol, e.isoformat(), lo, hi)
        return listed[e]

    need: Dict[date, List[date]] = {}
    for d in sessions:
        need[d] = _pair(d, candidates)
    used: Dict[date, List[date]] = {}
    for d, es in need.items():
        for e in es:
            used.setdefault(e, []).append(d)
    for e, ds in used.items():
        px = [spot[d] for d in ds]
        listing(e, min(px) * BAND[0], max(px) * BAND[1])
    # A monthly with nothing listed (an underlying on a quarterly cycle,
    # say) is dropped and the pairing redone without it.
    real = [e for e in candidates if listed.get(e)]
    for d in sessions:
        need[d] = [e for e in _pair(d, real)]

    def strikes(e: date) -> Dict[float, Dict[str, str]]:
        by: Dict[float, Dict[str, str]] = {}
        for c in listed.get(e, []):
            by.setdefault(c["strike"], {})[c["type"]] = c["symbol"]
        return by

    book = {e: strikes(e) for e in real}

    # ---- pass 1: at the money ------------------------------------------
    #
    # The nearest strike is not always one that trades. Half strikes are
    # listed late and trade rarely -- AAPL's $257.50 November call had a
    # single bar in the month it sat at the money -- so the four strikes
    # nearest the price are all fetched, and each session uses the
    # closest one that actually traded that day.
    near: Dict[Tuple[date, date], List[float]] = {}
    for d in sessions:
        for e in need[d]:
            both = [k for k, v in book[e].items() if "call" in v and "put" in v]
            if both:
                near[(d, e)] = sorted(both, key=lambda s: abs(s - spot[d]))[:4]

    syms = sorted({book[e][k][t] for (d, e), ks in near.items() for k in ks for t in ("call", "put")})
    bars = A.option_bars(syms, sessions[0].isoformat(), today.isoformat()) if syms else {}

    def close(sym: str, d: date) -> Optional[float]:
        b = bars.get(sym, {}).get(d.isoformat())
        return b["close"] if b else None

    atm_pick: Dict[Tuple[date, date], Tuple[float, str, str]] = {}
    for (d, e), ks in near.items():
        for k in ks:
            c, p = book[e][k]["call"], book[e][k]["put"]
            if close(c, d) is not None and close(p, d) is not None:
                atm_pick[(d, e)] = (k, c, p)
                break

    iv30: Dict[date, float] = {}
    atm_iv: Dict[Tuple[date, date], float] = {}
    for (d, e), (k, c, p) in atm_pick.items():
        t = _years(d, e)
        vals = [v for v in (_iv(close(c, d), spot[d], k, t, rate, True, q),
                            _iv(close(p, d), spot[d], k, t, rate, False, q)) if v]
        if vals:
            atm_iv[(d, e)] = sum(vals) / len(vals)

    for d in sessions:
        es = [e for e in need[d] if (d, e) in atm_iv]
        if len(es) == 2:
            (e1, e2) = es
            t1, t2 = (e1 - d).days, (e2 - d).days
            w1, w2 = atm_iv[(d, e1)] ** 2 * t1, atm_iv[(d, e2)] ** 2 * t2
            w = w1 + (w2 - w1) * (TARGET_DAYS - t1) / (t2 - t1)
            if w > 0:
                iv30[d] = math.sqrt(w / TARGET_DAYS)
        elif len(es) == 1 and len(need[d]) == 1:
            iv30[d] = atm_iv[(d, es[0])]

    # ---- pass 2: the 25-delta wings ------------------------------------
    # The same lesson as at the money, only more so: out-of-the-money
    # strikes trade less, so a handful around the first guess are fetched
    # and the one that traded with a delta nearest 25 is used.
    wings: Dict[date, Tuple[date, List[float], List[float]]] = {}
    for d in sessions:
        es = [e for e in need[d] if (d, e) in atm_iv]
        if not es:
            continue
        e = min(es, key=lambda x: abs((x - d).days - TARGET_DAYS))
        t, v = _years(d, e), atm_iv[(d, e)]
        calls = [k for k, x in book[e].items() if "call" in x]
        puts = [k for k, x in book[e].items() if "put" in x]
        if not calls or not puts:
            continue
        gc = _strike_at_delta(spot[d], t, v, rate, q, True)
        gp = _strike_at_delta(spot[d], t, v, rate, q, False)
        wings[d] = (e, sorted(calls, key=lambda s: abs(s - gc))[:4],
                    sorted(puts, key=lambda s: abs(s - gp))[:4])

    more = sorted({book[e][k][side] for e, kcs, kps in wings.values()
                   for side, ks in (("call", kcs), ("put", kps)) for k in ks} - set(bars))
    if more:
        bars.update(A.option_bars(more, sessions[0].isoformat(), today.isoformat()))

    def wing(d: date, e: date, ks: List[float], call: bool) -> Optional[float]:
        """IV of the traded strike whose own delta is nearest 25."""
        t, best = _years(d, e), None
        for k in ks:
            sym = book[e][k]["call" if call else "put"]
            iv = _iv(close(sym, d), spot[d], k, t, rate, call, q)
            if not iv:
                continue
            dl = abs(_delta(spot[d], k, t, iv, rate, call, q))
            # Nearest listed can still be a long way from 25 delta on a
            # thinly listed chain; only a genuine wing counts.
            if 0.15 <= dl <= 0.35 and (best is None or abs(dl - 0.25) < best[0]):
                best = (abs(dl - 0.25), iv)
        return best[1] if best else None

    rr25: Dict[date, float] = {}
    for d, (e, kcs, kps) in wings.items():
        ivc, ivp = wing(d, e, kcs, True), wing(d, e, kps, False)
        if ivc and ivp:
            rr25[d] = ivc - ivp

    # ---- put/call on a fixed definition --------------------------------
    pc: Dict[date, float] = {}
    recent = sessions[-PC_LOOKBACK:]
    fronts: Dict[date, List[date]] = {}
    for d in recent:
        fronts[d] = [e for e in real if e >= d][:2]
    pc_exp = sorted({e for es in fronts.values() for e in es})
    for e in pc_exp:
        px = [spot[d] for d in recent if e in fronts[d]]
        if e not in listed or not listed[e]:
            continue
        # The pass-1 listing may have used a narrower band; widen if needed.
        lo, hi = min(px) * 0.75, max(px) * 1.25
        have = [c["strike"] for c in listed[e]]
        if min(have) > lo or max(have) < hi:
            listed[e] = A.contracts(symbol, e.isoformat(), lo, hi)
    pc_syms = sorted({c["symbol"] for e in pc_exp for c in listed.get(e, [])} - set(bars))
    if pc_syms:
        bars.update(A.option_bars(pc_syms, recent[0].isoformat(), today.isoformat()))
    for d in recent:
        put_v = call_v = 0.0
        for e in fronts[d]:
            for c in listed.get(e, []):
                if not (0.75 * spot[d] <= c["strike"] <= 1.25 * spot[d]):
                    continue
                b = bars.get(c["symbol"], {}).get(d.isoformat())
                if b:
                    if c["type"] == "put":
                        put_v += b["volume"]
                    else:
                        call_v += b["volume"]
        if call_v > 0:
            pc[d] = put_v / call_v

    iso = lambda m: [{"date": d.isoformat(), "value": round(v, 5)} for d, v in sorted(m.items())]
    return {
        "symbol": symbol, "status": "ready", "built": today.isoformat(),
        "sessions": len(sessions), "from": sessions[0].isoformat(), "to": sessions[-1].isoformat(),
        "rate": rate, "div_yield": q,
        "iv30": iso(iv30), "rr25": iso(rr25), "pc": iso(pc),
        "contracts_read": len(bars),
    }


# ---- cached, built in the background --------------------------------------

_BUILDING: Dict[str, threading.Thread] = {}
_GUARD = threading.Lock()


def _path(symbol: str) -> Path:
    return CACHE / f"{symbol.upper()}.json"


def _load(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        return json.loads(_path(symbol).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _save(data: Dict[str, Any]) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    _path(data["symbol"]).write_text(json.dumps(data), encoding="utf-8")


def _run(symbol: str, rate: float, q: float) -> None:
    try:
        _save(build(symbol, rate, q))
    except Exception as exc:                                  # noqa: BLE001
        _save({"symbol": symbol.upper(), "status": "failed", "why": str(exc)[:200],
               "built": O.market_now().date().isoformat()})
    finally:
        with _GUARD:
            _BUILDING.pop(symbol.upper(), None)


def get(symbol: str, rate: float, div_yield: float = 0.0,
        wait: float = 0.0) -> Dict[str, Any]:
    """The history, from disk if it is today's; otherwise (re)built.

    A first build takes a few seconds and runs in the background, so
    the page is never held up by it: until it lands, this says it is
    building, and whatever was cached before is served meanwhile.
    """
    st = A.status()
    if not st["enabled"]:
        return {"symbol": symbol.upper(), "status": "off", "why": st["why"]}
    sym = symbol.upper()
    cached = _load(sym)
    fresh = cached and cached.get("built") == O.market_now().date().isoformat()
    if fresh:
        return cached
    with _GUARD:
        t = _BUILDING.get(sym)
        if t is None:
            t = threading.Thread(target=_run, args=(sym, rate, div_yield), daemon=True)
            _BUILDING[sym] = t
            t.start()
    if wait:
        t.join(wait)
        again = _load(sym)
        if again and again.get("built") == O.market_now().date().isoformat():
            return again
    if cached and cached.get("status") == "ready":
        return {**cached, "stale": True}
    return {"symbol": sym, "status": "building"}


# ---- what the curriculum reads off it --------------------------------------

def rank(series: List[Dict[str, Any]], current: Optional[float] = None
         ) -> Optional[Dict[str, Any]]:
    """IV Rank and IV Percentile, Lesson 1.2, against the series given.

    `current` defaults to the series' own last point, so rank is of the
    latest completed session against the year before it.
    """
    vals = [p["value"] for p in series]
    if len(vals) < 60:
        return None
    cur = vals[-1] if current is None else current
    lo, hi = min(vals), max(vals)
    below = sum(1 for v in vals[:-1] if v < cur) if current is None else sum(1 for v in vals if v < cur)
    total = len(vals) - 1 if current is None else len(vals)
    return {
        "current": cur, "low": lo, "high": hi,
        "low_on": series[vals.index(lo)]["date"], "high_on": series[vals.index(hi)]["date"],
        "rank": (cur - lo) / (hi - lo) * 100 if hi > lo else None,
        "percentile": below / total * 100 if total else None,
        "below": below, "days": total,
    }


def zscore(series: List[Dict[str, Any]], window: int = PC_LOOKBACK
           ) -> Optional[Dict[str, Any]]:
    """Today against the average of the sessions before it."""
    vals = [p["value"] for p in series][-(window + 1):]
    if len(vals) < 21:
        return None
    cur, past = vals[-1], vals[:-1]
    mean = sum(past) / len(past)
    sd = math.sqrt(sum((v - mean) ** 2 for v in past) / (len(past) - 1)) if len(past) > 1 else 0
    return {"current": cur, "mean": mean, "sd": sd, "days": len(past),
            "z": (cur - mean) / sd if sd > 0 else None}
