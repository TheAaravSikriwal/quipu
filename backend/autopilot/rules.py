"""The conditions a bot's entry is built from, and how each is read.

A bot's entry for a side (long or short) is a list of conditions and a
word, ALL or ANY. Each condition is a small dict with a `type` and its own
settings, read against the market as it stands, and returns whether it
is met and a sentence saying why -- so the page can show the working
rather than a bare yes.

The blocks:

  momentum    price moved N% within M minutes, on V times normal volume
  breakout    price crossed a level (fresh cross, not merely above it)
  rsi         RSI on 1- or 5-minute bars above / below a value
  vwap        price above / below / crossing today's VWAP
  fvg         a fair value gap on 5-minute bars, price back inside it
  price       price above / below a value
  day_change  today's move from yesterday's close above / below N%
  time        only between two times of day (Eastern)

Volume is IEX's share of the tape (Alpaca's free feed), so the ratios are
compared against IEX's own normal, never against consolidated volume.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median
from typing import Any, Callable, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

TYPES = ("momentum", "breakout", "rsi", "vwap", "fvg", "price", "day_change", "time")


# ---- the market, as the conditions read it --------------------------------

def _et(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(ET)


def session_bars(bars: List[Dict[str, Any]], day) -> List[Dict[str, Any]]:
    """Regular-session bars of one day."""
    out = []
    for b in bars:
        t = _et(b["t"])
        if t.date() == day and (t.hour, t.minute) >= (9, 30) and t.hour < 16:
            out.append(b)
    return out


def context(bars1: List[Dict[str, Any]], bars5: List[Dict[str, Any]],
            price: Optional[float], now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(ET)
    today = now.date()
    t1 = session_bars(bars1, today)
    # Only finished five-minute bars: a gap is three COMPLETE candles.
    t5 = [b for b in session_bars(bars5, today) if _et(b["t"]) + timedelta(minutes=5) <= now]
    before = [b for b in bars1 if _et(b["t"]).date() < today]
    prev_close = None
    if before:
        last_session = session_bars(before, _et(before[-1]["t"]).date())
        prev_close = (last_session or before)[-1]["c"]
    last = price or (t1[-1]["c"] if t1 else None)
    return {"now": now, "bars1": t1, "bars5": t5, "price": last, "prev_close": prev_close}


# ---- indicators ----------------------------------------------------------

def rsi(closes: List[float], period: int = 14) -> Optional[float]:
    """Wilder's RSI, the way every charting package computes it."""
    if len(closes) <= period:
        return None
    gains = [max(closes[i] - closes[i - 1], 0.0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0.0) for i in range(1, len(closes))]
    g = sum(gains[:period]) / period
    l = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        g = (g * (period - 1) + gains[i]) / period
        l = (l * (period - 1) + losses[i]) / period
    if l == 0:
        return 100.0
    return 100.0 - 100.0 / (1.0 + g / l)


def vwap(bars: List[Dict[str, Any]]) -> Optional[float]:
    vol = sum(b["v"] for b in bars)
    if not vol:
        return None
    return sum((b["h"] + b["l"] + b["c"]) / 3.0 * b["v"] for b in bars) / vol


def _five(bars1: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """1-minute bars rolled into 5-minute ones, when the page asks for RSI
    on five minutes and only the 1-minute series is at hand."""
    out: List[Dict[str, Any]] = []
    for b in bars1:
        t = _et(b["t"])
        slot = t.replace(minute=t.minute - t.minute % 5, second=0, microsecond=0)
        if out and out[-1]["slot"] == slot:
            o = out[-1]
            o["h"], o["l"], o["c"], o["v"] = max(o["h"], b["h"]), min(o["l"], b["l"]), b["c"], o["v"] + b["v"]
        else:
            out.append({"slot": slot, "t": b["t"], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"]})
    return out


# ---- the blocks --------------------------------------------------------------

def _num(c: Dict[str, Any], key: str, default: float) -> float:
    try:
        return float(c.get(key, default))
    except (TypeError, ValueError):
        return default


def _momentum(c, x) -> Tuple[bool, str]:
    mins = max(1, int(_num(c, "minutes", 5)))
    want, vol_x = _num(c, "pct", 0.6), _num(c, "vol_x", 0)
    b, p = x["bars1"], x["price"]
    if len(b) < mins + 2 or not p:
        return False, f"needs {mins + 2} minutes of today's bars"
    ref = b[-1 - mins]["c"]
    move = (p / ref - 1) * 100
    up = c.get("dir", "up") == "up"
    ok = move >= want if up else move <= -want
    say = f"{move:+.2f}% in {mins} min (wants {'+' if up else '-'}{want:g}%)"
    if vol_x > 0:
        recent = [v["v"] for v in b[-mins:]]
        base = [v["v"] for v in b[:-mins] if v["v"] > 0]
        normal = median(base) if base else 0
        ratio = (sum(recent) / len(recent)) / normal if normal else 0
        ok = ok and ratio >= vol_x
        say += f", volume {ratio:.1f}x normal (wants {vol_x:g}x)"
    return ok, say


def _breakout(c, x) -> Tuple[bool, str]:
    level = _num(c, "level", 0)
    b, p = x["bars1"], x["price"]
    if not level or len(b) < 2 or not p:
        return False, "set a level" if not level else "waiting for bars"
    above = c.get("dir", "above") == "above"
    prev = b[-2]["c"]
    # A cross, not a state: a bot started with the price already past the
    # level would otherwise buy the instant it was switched on.
    crossed = (prev <= level < p) if above else (prev >= level > p)
    say = f"{p:.2f} vs {level:.2f}, a minute ago {prev:.2f}"
    vol_x = _num(c, "vol_x", 0)
    if vol_x > 0 and len(b) > 5:
        normal = median([v["v"] for v in b[:-1] if v["v"] > 0] or [0])
        ratio = b[-1]["v"] / normal if normal else 0
        crossed = crossed and ratio >= vol_x
        say += f", volume {ratio:.1f}x (wants {vol_x:g}x)"
    return crossed, ("crossed " + ("above: " if above else "below: ") + say) if crossed else say


def _rsi(c, x) -> Tuple[bool, str]:
    period = max(2, int(_num(c, "period", 14)))
    bars = x["bars1"] if c.get("timeframe", "1Min") == "1Min" else _five(x["bars1"])
    closes = [b["c"] for b in bars]
    if x["price"] and closes:
        closes[-1] = x["price"]
    r = rsi(closes, period)
    if r is None:
        return False, f"needs {period + 1} bars"
    value = _num(c, "value", 30)
    below = c.get("op", "below") == "below"
    ok = r < value if below else r > value
    return ok, f"RSI {r:.1f} ({'wants below' if below else 'wants above'} {value:g})"


def _vwap(c, x) -> Tuple[bool, str]:
    v, p, b = vwap(x["bars1"]), x["price"], x["bars1"]
    if not v or not p:
        return False, "waiting for bars"
    op = c.get("op", "above")
    if op in ("cross_above", "cross_below"):
        if len(b) < 2:
            return False, "waiting for bars"
        prev = b[-2]["c"]
        ok = (prev <= v < p) if op == "cross_above" else (prev >= v > p)
    else:
        ok = p > v if op == "above" else p < v
    return ok, f"price {p:.2f}, VWAP {v:.2f} ({op.replace('_', ' ')})"


def _fvg(c, x) -> Tuple[bool, str]:
    b, p = x["bars5"], x["price"]
    if len(b) < 3 or not p:
        return False, "needs three finished 5-minute bars"
    a, _, z = b[-3], b[-2], b[-1]
    bull = c.get("dir", "bull") == "bull"
    if bull and a["h"] < z["l"]:
        lo, hi = a["h"], z["l"]
    elif not bull and a["l"] > z["h"]:
        lo, hi = z["h"], a["l"]
    else:
        return False, "no gap in the last three 5-minute bars"
    mid = (lo + hi) / 2
    # Back into the gap as far as its middle -- where algotrader rested its
    # limit order -- but not through the far side, which voids the gap.
    ok = (lo <= p <= mid) if bull else (mid <= p <= hi)
    return ok, f"{'bullish' if bull else 'bearish'} gap {lo:.2f}-{hi:.2f}, price {p:.2f}" + \
        ("" if ok else f" (wants {'back to' if bull else 'up to'} {mid:.2f})")


def _price(c, x) -> Tuple[bool, str]:
    p, v = x["price"], _num(c, "value", 0)
    if not p or not v:
        return False, "set a value"
    above = c.get("op", "above") == "above"
    return (p > v if above else p < v), f"{p:.2f} ({'above' if above else 'below'} {v:.2f}?)"


def _day_change(c, x) -> Tuple[bool, str]:
    p, pc = x["price"], x["prev_close"]
    if not p or not pc:
        return False, "no previous close"
    move = (p / pc - 1) * 100
    want = _num(c, "pct", 0)
    above = c.get("op", "above") == "above"
    return (move > want if above else move < want), f"day {move:+.2f}% ({'above' if above else 'below'} {want:+g}%?)"


def _hm(s: str, default: str) -> Tuple[int, int]:
    try:
        h, m = str(s or default).split(":")
        return int(h), int(m)
    except ValueError:
        h, m = default.split(":")
        return int(h), int(m)


def _time(c, x) -> Tuple[bool, str]:
    now = x["now"]
    a, b = _hm(c.get("from"), "09:45"), _hm(c.get("to"), "15:30")
    ok = a <= (now.hour, now.minute) < b
    return ok, f"{now:%H:%M} ET, window {a[0]:02d}:{a[1]:02d}-{b[0]:02d}:{b[1]:02d}"


READ: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Tuple[bool, str]]] = {
    "momentum": _momentum, "breakout": _breakout, "rsi": _rsi, "vwap": _vwap,
    "fvg": _fvg, "price": _price, "day_change": _day_change, "time": _time,
}


def check(rules: Dict[str, Any], x: Dict[str, Any]) -> Tuple[bool, List[Dict[str, Any]]]:
    """Every condition read, and whether the side's entry is met."""
    conds = [c for c in (rules or {}).get("conditions") or [] if c.get("type") in READ]
    out = []
    for c in conds:
        try:
            ok, say = READ[c["type"]](c, x)
        except Exception as exc:                            # noqa: BLE001
            ok, say = False, f"could not read: {exc}"
        out.append({"type": c["type"], "met": ok, "say": say})
    if not out:
        return False, out
    met = any(r["met"] for r in out) if rules.get("match") == "any" else all(r["met"] for r in out)
    return met, out


# ---- starting points -----------------------------------------------------

def _side(conds: List[Dict[str, Any]], match: str = "all", enabled: bool = True) -> Dict[str, Any]:
    return {"enabled": enabled, "match": match, "conditions": conds}


TEMPLATES: Dict[str, Dict[str, Any]] = {
    "momentum": {
        "label": "Momentum scalp",
        "say": "Rides a burst: price up fast on a volume surge. Small target, tight stop.",
        "long": _side([{"type": "momentum", "dir": "up", "pct": 0.6, "minutes": 5, "vol_x": 2},
                       {"type": "time", "from": "09:45", "to": "15:30"}]),
        "short": _side([{"type": "momentum", "dir": "down", "pct": 0.6, "minutes": 5, "vol_x": 2},
                        {"type": "time", "from": "09:45", "to": "15:30"}], enabled=False),
        "exits": {"take_profit_pct": 0.8, "stop_loss_pct": 0.4, "trail_pct": 0, "max_minutes": 30},
    },
    "breakout": {
        "label": "Breakout",
        "say": "Buys the first cross of a level you set, with volume behind it.",
        "long": _side([{"type": "breakout", "dir": "above", "level": 0, "vol_x": 1.5}]),
        "short": _side([{"type": "breakout", "dir": "below", "level": 0, "vol_x": 1.5}], enabled=False),
        "exits": {"take_profit_pct": 1.5, "stop_loss_pct": 0.7, "trail_pct": 0.6, "max_minutes": 0},
    },
    "dip": {
        "label": "Dip buy",
        "say": "Buys a sharp 1-minute pullback below VWAP, expecting a bounce.",
        "long": _side([{"type": "rsi", "op": "below", "value": 28, "period": 14, "timeframe": "1Min"},
                       {"type": "vwap", "op": "below"},
                       {"type": "time", "from": "10:00", "to": "15:30"}]),
        "short": _side([{"type": "rsi", "op": "above", "value": 72, "period": 14, "timeframe": "1Min"},
                        {"type": "vwap", "op": "above"},
                        {"type": "time", "from": "10:00", "to": "15:30"}], enabled=False),
        "exits": {"take_profit_pct": 0.6, "stop_loss_pct": 0.5, "trail_pct": 0, "max_minutes": 45},
    },
    "fvg": {
        "label": "Fair value gap",
        "say": "algotrader's rule: a 3-candle gap on 5-minute bars, bought on the pullback to its middle.",
        "long": _side([{"type": "fvg", "dir": "bull"}, {"type": "time", "from": "10:30", "to": "15:30"}]),
        "short": _side([{"type": "fvg", "dir": "bear"}, {"type": "time", "from": "10:30", "to": "15:30"}],
                       enabled=False),
        "exits": {"take_profit_pct": 1.0, "stop_loss_pct": 0.5, "trail_pct": 0, "max_minutes": 0},
    },
}
