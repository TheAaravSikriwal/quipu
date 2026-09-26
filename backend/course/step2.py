"""Step 2 -- Determine direction (Lessons 2.1 to 2.10).

The question: which way is it likely to move, how confident am I, over
what time, to what target, and at what price am I wrong?

Nine signals, in the curriculum's order -- technical lean, fundamental
lean, confirmation, then what the options crowd thinks -- each scored
+1, 0 or -1 by the curriculum's own table and weighted by its 2.10
template. Every rule used to turn a reading into a score is written on
the metric, so a score can be disagreed with rather than trusted.
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Dict, List, Optional, Tuple

from . import data as D
from .read import (BEAR, BULL, NEUTRAL, first_hit, fmt, line, metric, missing,
                   money, pct, row, sum_of, table, term)

WEIGHTS = {"trend": 3, "levels": 2, "pattern": 1, "catalyst": 2, "fundamentals": 2,
           "rs": 2, "rsi": 1, "pc": 1, "skew": 1}
MAX_SCORE = sum(WEIGHTS.values())            # 15

_DIR = {1: BULL, -1: BEAR, 0: NEUTRAL}


def _completed(d: Dict[str, List]) -> int:
    """Index of the last COMPLETED session. During market hours Yahoo's last
    bar is the session so far, and its volume is a fraction of a day's."""
    from sources import options as O
    now = O.market_now()
    live = now.weekday() < 5 and (9, 30) <= (now.hour, now.minute) < (16, 0) \
        and d["date"][-1] == now.date().isoformat()
    return len(d["close"]) - (2 if live else 1)


# ---- 2.1 trend ----------------------------------------------------------------

def trend(d: Dict[str, List]) -> Dict[str, Any]:
    c = d["close"]
    n = len(c)
    if n < 215:
        return missing("trend", "2.1", "Trend", "Fewer than 215 sessions of history.", WEIGHTS["trend"])
    p = c[-1]
    m20, m50, m200 = D.sma(c, 20), D.sma(c, 50), D.sma(c, 200)
    m50_then, m200_then = D.sma(c, 50, n - 10), D.sma(c, 200, n - 10)
    up50, up200 = m50 > m50_then, m200 > m200_then
    above50 = (p - m50) / m50 * 100

    # The last time the 50 crossed the 200, within the year.
    cross = None
    for i in range(n - 1, max(n - 253, 201), -1):
        a, b = D.sma(c, 50, i) - D.sma(c, 200, i), D.sma(c, 50, i - 1) - D.sma(c, 200, i - 1)
        if (a > 0) != (b > 0):
            cross = {"kind": "golden" if a > 0 else "death", "date": d["date"][i - 1],
                     "ago": n - i}
            break

    if p > m50 > m200 and up50 and up200:
        score, hit = 1, 0
    elif p < m50 < m200 and not up50 and not up200:
        score, hit = -1, 1
    else:
        score, hit = 0, 2
    stretched = above50 > 15
    shape = ["Uptrend: price above a rising 50-day, above a rising 200-day",
             "Downtrend: price below a falling 50-day, below a falling 200-day",
             "No clean trend: the averages are not stacked and sloping the same way"][hit]
    return metric(
        "trend", "2.1", "Trend (20 / 50 / 200-day averages)", above50, pct(above50, 1, True) + " vs 50-day",
        working=sum_of(above50, [line("", term("price", p)), line("-", term("50-day average", m50)),
                                 line("/", term("50-day average", m50)),
                                 line("x", term("as a percent", 100, 0))], unit="%"),
        formula="SMA_N = (P1 + ... + PN) / N;  % above MA = (price - MA) / MA x 100",
        against=table([row("Price > 50 > 200, both rising", "Uptrend", BULL),
                       row("Price < 50 < 200, both falling", "Downtrend", BEAR),
                       row("Averages flat or tangled", "No trend -- avoid directional trades", NEUTRAL)], hit),
        compare=[{"label": "20-day", "show": money(m20), "reads": BULL if p > m20 else BEAR},
                 {"label": "50-day", "show": f"{money(m50)} ({'rising' if up50 else 'falling'})",
                  "reads": BULL if p > m50 else BEAR},
                 {"label": "200-day", "show": f"{money(m200)} ({'rising' if up200 else 'falling'})",
                  "reads": BULL if p > m200 else BEAR},
                 {"label": "vs 200-day", "show": pct((p - m200) / m200 * 100, 1, True)}]
        + ([{"label": f"{cross['kind']} cross", "show": f"{cross['date']} ({cross['ago']} sessions ago)",
             "reads": BULL if cross["kind"] == "golden" else BEAR}] if cross else []),
        reads=_DIR[score], score=score, weight=WEIGHTS["trend"],
        means=shape + "." + (" But it is more than 15% above the 50-day: stretched trends often "
                             "pause or pull back to the average before continuing." if stretched else
                             " Trading with it has the better base odds; fighting it needs a specific catalyst."
                             if score else ""),
        extra={"sma": {"20": m20, "50": m50, "200": m200}, "cross": cross, "stretched": stretched},
    )


# ---- 2.2 support and resistance ------------------------------------------------

def _swings(values: List[float], window: int, highs: bool) -> List[int]:
    out = []
    for i in range(window, len(values) - window):
        seg = values[i - window:i + window + 1]
        if values[i] == (max(seg) if highs else min(seg)):
            out.append(i)
    return out


def _cluster(prices: List[Tuple[float, str]], tol: float = 0.015) -> List[Dict[str, Any]]:
    """Swing points within 1.5% of each other are one level, touched N times."""
    out: List[Dict[str, Any]] = []
    for p, when in sorted(prices):
        if out and abs(p - out[-1]["price"]) / out[-1]["price"] <= tol:
            g = out[-1]
            g["points"].append((p, when))
            g["price"] = sum(x for x, _ in g["points"]) / len(g["points"])
        else:
            out.append({"price": p, "points": [(p, when)]})
    for g in out:
        g["touches"] = len(g["points"])
        g["last"] = max(w for _, w in g["points"])
    return out


def pivots(d: Dict[str, List], kind: str) -> Optional[Dict[str, float]]:
    """Classic pivots off the last completed week or month."""
    key = (lambda s: date.fromisoformat(s).isocalendar()[:2]) if kind == "week" \
        else (lambda s: s[:7])
    groups: Dict[Any, List[int]] = {}
    for i, s in enumerate(d["date"]):
        groups.setdefault(key(s), []).append(i)
    ks = list(groups)
    if len(ks) < 2:
        return None
    idx = groups[ks[-2]]                     # the last one that is over
    h = max(d["high"][i] for i in idx)
    lo = min(d["low"][i] for i in idx)
    c = d["close"][idx[-1]]
    p = (h + lo + c) / 3
    return {"H": h, "L": lo, "C": c, "P": p, "R1": 2 * p - lo, "S1": 2 * p - h,
            "R2": p + (h - lo), "S2": p - (h - lo)}


def levels(d: Dict[str, List], em: float, day: float = 0.0) -> Dict[str, Any]:
    """`day` is one normal day's move in dollars. A level closer than that
    is not somewhere the price is going -- it is where the price is, being
    tested right now -- so it is noted and the next level is the target."""
    c, hi, lo = d["close"], d["high"], d["low"]
    p = c[-1]
    look = 126
    base = len(c) - look
    sh = [(hi[i], d["date"][i]) for i in _swings(hi, 5, True) if i >= base]
    sl = [(lo[i], d["date"][i]) for i in _swings(lo, 5, False) if i >= base]
    lv = _cluster(sh + sl)

    gap = max(day, p * 0.005)
    testing = [g for g in lv if abs(g["price"] - p) <= gap]

    def pick(above: bool) -> Tuple[Optional[Dict[str, Any]], str]:
        side = [g for g in lv if (g["price"] > p + gap if above else g["price"] < p - gap)]
        strong = [g for g in side if g["touches"] >= 2]
        pool = strong or side
        if pool:
            g = min(pool, key=lambda g: abs(g["price"] - p))
            return g, ("tested %d times" % g["touches"]) if g["touches"] >= 2 else "one prior swing"
        return None, ""

    res, rwhy = pick(True)
    sup, swhy = pick(False)
    # A stock at its highs has no overhead level to aim at; the market's
    # own expected move stands in, and says that is what it is.
    r_price = res["price"] if res else p + em
    s_price = sup["price"] if sup else p - em
    if not res:
        rwhy = "no swing high above -- one expected move up stands in"
    if not sup:
        swhy = "no swing low below -- one expected move down stands in"

    up = (r_price - p) / p * 100
    down = (p - s_price) / p * 100
    rr = up / down if down > 0 else None
    score = 1 if rr and rr >= 2 else -1 if rr is not None and rr <= 0.5 else 0
    wk, mo = pivots(d, "week"), pivots(d, "month")

    comp = [{"label": "resistance", "show": f"{money(r_price)} -- {rwhy}", "reads": BULL},
            {"label": "support", "show": f"{money(s_price)} -- {swhy}", "reads": BEAR},
            {"label": "upside room", "show": pct(up),
             "working": sum_of(up, [line("", term("resistance", r_price)), line("-", term("price", p)),
                                    line("/", term("price", p)), line("x", term("as a percent", 100, 0))], unit="%")},
            {"label": "downside to support", "show": pct(down),
             "working": sum_of(down, [line("", term("price", p)), line("-", term("support", s_price)),
                                      line("/", term("price", p)), line("x", term("as a percent", 100, 0))], unit="%")}]
    for g in testing:
        comp.append({"label": "being tested now",
                     "show": f"{money(g['price'])}, touched {g['touches']} time{'s' if g['touches'] > 1 else ''} -- "
                             "closer than a normal day's move, so not the target",
                     "reads": BULL if g["price"] > p else BEAR})
    for name, pv in (("last week", wk), ("last month", mo)):
        if pv:
            comp.append({"label": f"pivots off {name}",
                         "show": f"S2 {money(pv['S2'])}  S1 {money(pv['S1'])}  P {money(pv['P'])}  "
                                 f"R1 {money(pv['R1'])}  R2 {money(pv['R2'])}",
                         "working": sum_of(pv["P"], [line("", term("high", pv["H"])), line("+", term("low", pv["L"])),
                                                     line("+", term("close", pv["C"])),
                                                     line("/", term("three", 3, 0))])})
    return metric(
        "levels", "2.2", "Support, resistance and room to run", rr, fmt(rr, 2) + " reward/risk" if rr else "--",
        working=sum_of(rr or 0, [line("", term("upside room %", up)), line("/", term("downside risk %", down))], unit=""),
        formula="Reward/risk = (resistance - price) / (price - support)",
        against=table([row("2 or more", "Room to run -- more upside than downside to the levels", BULL),
                       row("0.5 to 2", "Balanced", NEUTRAL),
                       row("0.5 or less", "More room down than up", BEAR)],
                      first_hit([bool(rr and rr >= 2), bool(rr and rr > 0.5), True])),
        compare=comp, reads=_DIR[score], score=score, weight=WEIGHTS["levels"],
        means=("These two prices are the ones every later step needs: the target and the "
               "point at which you are wrong. Two touches make a level, three a strong one; "
               "once broken, old resistance often becomes support."),
        extra={"resistance": r_price, "support": s_price, "up_pct": up, "down_pct": down,
               "levels": [{"price": g["price"], "touches": g["touches"], "last": g["last"]} for g in lv]},
    )


# ---- 2.3 pattern and volume --------------------------------------------------

def pattern(d: Dict[str, List]) -> Dict[str, Any]:
    last = _completed(d)
    c, v, hi, lo = d["close"], d["volume"], d["high"], d["low"]
    avg20 = sum(v[last - 20:last]) / 20
    rvol = v[last] / avg20 if avg20 else None

    # A consolidation is the 20 sessions before the last five; a breakout
    # is a close outside it within those five.
    box = range(last - 25, last - 4)
    top, bot = max(hi[i] for i in box), min(lo[i] for i in box)
    height = top - bot
    brk = None
    for i in range(last - 4, last + 1):
        if c[i] > top:
            brk = ("up", i)
            break
        if c[i] < bot:
            brk = ("down", i)
            break
    b_rvol = None
    if brk:
        i = brk[1]
        base = sum(v[i - 20:i]) / 20
        b_rvol = v[i] / base if base else None

    score = 0
    if brk and b_rvol and b_rvol >= 1.5:
        score = 1 if brk[0] == "up" else -1
    hit = first_hit([rvol is not None and rvol < 1.0, rvol is not None and rvol < 1.5,
                     rvol is not None and rvol < 2.0, True])
    comp = [{"label": "20-session range", "show": f"{money(bot)} to {money(top)} (height {money(height)})"}]
    if brk:
        tgt = top + height if brk[0] == "up" else bot - height
        comp.append({"label": f"broke {'out' if brk[0] == 'up' else 'down'} on {d['date'][brk[1]]}",
                     "show": f"at {fmt(b_rvol, 1)}x normal volume", "reads": BULL if brk[0] == "up" else BEAR})
        comp.append({"label": "measured-move target", "show": money(tgt),
                     "working": sum_of(tgt, [line("", term("breakout level" if brk[0] == "up" else "breakdown level",
                                                           top if brk[0] == "up" else bot)),
                                             line("+" if brk[0] == "up" else "-", term("pattern height", height))])})
    return metric(
        "pattern", "2.3", f"Volume ({d['date'][last]}) and breakouts", rvol, (fmt(rvol, 2) + "x RVOL") if rvol else "--",
        working=sum_of(rvol or 0, [line("", term(f"volume {d['date'][last]}", v[last], 0)),
                                   line("/", term("20-session average", avg20, 0))], unit=""),
        formula="RVOL = volume / 20-day average;  measured move = breakout + pattern height",
        against=table([row("under 1.0", "Weak -- a move on this is prone to fail"),
                       row("1.0 to 1.5", "Ordinary"), row("1.5 to 2.0", "Decent confirmation"),
                       row("2.0 or more", "Strong confirmation")], hit),
        compare=comp, reads=_DIR[score], score=score, weight=WEIGHTS["pattern"],
        means=(("A breakout on real volume: buyers are behind it." if score == 1 else
                "A breakdown on real volume: sellers are behind it." if score == -1 else
                "A break on light volume -- the kind that fails." if brk else
                "No break out of its recent range; nothing here to time an entry on.")
               + " Named chart patterns (flags, triangles) are not auto-detected; the range and "
                 "volume are the objective part of them."),
        extra={"rvol": rvol, "breakout": brk[0] if brk else None},
    )


# ---- 2.4 catalysts and earnings -------------------------------------------------

def _reactions(d: Dict[str, List], history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Close before the report to close after it -- a two-session window,
    so it holds whether the report came before the open or after the close."""
    idx = {s: i for i, s in enumerate(d["date"])}
    out = []
    for h in history:
        dt = h["date"][:10]
        after = next((i for s, i in idx.items() if s > dt), None)
        before = next((i for s, i in reversed(list(idx.items())) if s < dt), None)
        if after is None or before is None:
            continue
        move = d["close"][after] / d["close"][before] - 1
        out.append({"date": dt, "move_pct": move * 100, "surprise_pct": h.get("surprise_pct")})
    return out


def catalyst(d: Dict[str, List], earnings: Dict[str, Any], implied: Optional[Dict[str, Any]],
             window: int) -> Dict[str, Any]:
    nxt = earnings.get("next_date")
    days = D.days_to(nxt) if nxt else None
    rs = _reactions(d, earnings.get("history") or [])
    if not rs:
        return missing("catalyst", "2.4", "Earnings history", "No past earnings dates to measure.",
                       WEIGHTS["catalyst"])
    ups = sum(1 for r in rs if r["move_pct"] > 0)
    n = len(rs)
    inside = days is not None and 0 <= days <= window
    imp = implied["pct"] if implied else None
    beats = sum(1 for r in rs if imp is not None and abs(r["move_pct"]) > imp)
    rate = beats / n * 100 if imp is not None else None

    # Direction from history only when the event is actually inside the
    # trade, and only when the history is one-sided.
    score = 0
    if inside and ups >= math.ceil(0.75 * n):
        score = 1
    elif inside and n - ups >= math.ceil(0.75 * n):
        score = -1
    comp = [{"label": r["date"], "show": pct(r["move_pct"], 1, True)
             + (f" (EPS surprise {pct(r['surprise_pct'], 1, True)})" if r.get("surprise_pct") is not None else ""),
             "reads": BULL if r["move_pct"] > 0 else BEAR} for r in rs]
    if implied:
        comp.insert(0, {"label": f"implied move for {nxt}", "show": pct(imp, 1),
                        "working": implied.get("working")})
    return metric(
        "catalyst", "2.4", "Earnings: how it has reacted, against what is priced now",
        rate, (f"{beats} of {n} beat the implied move" if rate is not None else f"{ups} of {n} up"),
        working=(sum_of(rate, [line("", term("reactions bigger than the implied move", beats, 0)),
                               line("/", term("reports measured", n, 0)),
                               line("x", term("as a percent", 100, 0))], unit="%") if rate is not None else None),
        formula="Beat rate = times actual move > implied move / events",
        against=table([row("beat rate under 50%", "Rarely exceeds what is priced -- lean against buying volatility into it"),
                       row("50% or more", "Has tended to move more than priced -- buying the event has paid")],
                      (0 if rate < 50 else 1) if rate is not None else None),
        compare=[{"label": "next report", "show": f"{nxt} ({days} days)" if nxt else "not confirmed"},
                 {"label": "reactions up", "show": f"{ups} of {n}"}] + comp,
        reads=_DIR[score], score=score, weight=WEIGHTS["catalyst"],
        means=((f"The report is {days} days out: inside the life of any trade built here "
                f"(up to {window} days), so it is the catalyst. " if inside else
                f"No report in the next {window} days, so it scores nothing for direction. ")
               + (f"{ups} of the last {n} reactions were up" + (" -- one-sided enough to lean on."
                  if score else ", which is not one-sided enough to lean on.") if inside else "")
               + (" It has beaten the implied move less than half the time: sell the event rather than buy it."
                  if rate is not None and rate < 50 else "")),
        extra={"inside": inside, "days": days, "beat_rate": rate, "reactions": rs},
    )


def implied_event(pre: Optional[Dict[str, Any]], post: Optional[Dict[str, Any]],
                  pick) -> Optional[Dict[str, Any]]:
    """The move priced for the report itself.

    Variances add: the expiry after the report carries a normal
    stretch of days PLUS the event, the one before it carries only the
    normal days. The difference in total variance is the event's. (The
    curriculum's shorthand subtracts days x a daily move, which is the
    same idea done in the wrong units: moves do not add, variances do.)
    Reported as 0.8 of the event's standard deviation -- the expected
    size of the move, the same thing a straddle measures.
    """
    if not post:
        return None
    a2 = pick(post)
    if not a2:
        return None
    iv2, t2 = (a2["call"]["iv"] + a2["put"]["iv"]) / 200, post["days_to_expiry"] / 365
    if pre and pick(pre):
        a1 = pick(pre)
        iv1 = (a1["call"]["iv"] + a1["put"]["iv"]) / 200
        ev = iv2 ** 2 * t2 - iv1 ** 2 * t2
        if ev > 0:
            sd = math.sqrt(ev)
            p = 0.8 * sd * 100
            return {"pct": p, "working": sum_of(p, [
                line("", term("standard deviation of the event move", sd, 4,
                              note=(f"sqrt of the event's variance, {ev:.5f} = "
                                    f"{iv2:.4f}^2 x {t2:.4f} years (IV to {post['expiry']}, after the report) "
                                    f"- {iv1:.4f}^2 x {t2:.4f} (IV to {pre['expiry']}, before it)"))),
                line("x", term("sqrt(2/pi): the expected size of a move", 0.8, 2)),
                line("x", term("as a percent", 100, 0)),
            ], unit="%", note="Variances add; moves do not. The later expiry carries the report, the earlier does not.")}
    st = a2["call"]["mark"] + a2["put"]["mark"]
    p = st / post["spot"] * 100
    return {"pct": p, "working": sum_of(p, [line("", term(f"straddle, {post['expiry']}", st)),
                                           line("/", term("share price", post["spot"])),
                                           line("x", term("as a percent", 100, 0))], unit="%",
                                   note="No expiry before the report to strip out the normal days, so this "
                                        "is the whole straddle: an upper bound on the event's move.")}


# ---- 2.5 revisions and valuation -------------------------------------------------

def fundamentals(price: float, info: Dict[str, Any], eps: Optional[Dict[str, Dict]],
                 peer: Dict[str, Any], symbol: str) -> Dict[str, Any]:
    nxt = (eps or {}).get("+1y") or {}
    now, ago = nxt.get("current"), nxt.get("90daysAgo")
    rev = (now - ago) / abs(ago) * 100 if now and ago else None
    fpe = price / now if now and now > 0 else None
    ps = [p["forward_pe"] for p in peer.get("peers", [])
          if p["symbol"] != symbol and isinstance(p.get("forward_pe"), (int, float)) and 0 < p["forward_pe"] < 300]
    ps.sort()
    med = (ps[len(ps) // 2] if len(ps) % 2 else (ps[len(ps) // 2 - 1] + ps[len(ps) // 2]) / 2) if len(ps) >= 5 else None
    rel = fpe / med if fpe and med else None

    if rev is None and rel is None:
        return missing("fundamentals", "2.5", "Estimate revisions and valuation",
                       "No consensus estimate trend or peer valuations from Yahoo.", WEIGHTS["fundamentals"])
    if rev is not None and rel is not None:
        score = 1 if rev > 1 and rel <= 1.1 else -1 if rev < -1 and rel >= 1.0 else 0
    else:
        score = (1 if rev > 2 else -1 if rev < -2 else 0) if rev is not None else 0
    hit = {1: 0, -1: 1, 0: 2}[score]

    comp = []
    if rev is not None:
        comp.append({"label": "next-year EPS estimate", "show": f"{money(ago)} 90 days ago, {money(now)} now",
                     "reads": BULL if rev > 0 else BEAR,
                     "working": sum_of(rev, [line("", term("estimate now", now)), line("-", term("90 days ago", ago)),
                                             line("/", term("90 days ago", ago)), line("x", term("as a percent", 100, 0))], unit="%")})
    if fpe:
        comp.append({"label": "forward P/E", "show": fmt(fpe, 1),
                     "working": sum_of(fpe, [line("", term("price", price)), line("/", term("next-year EPS estimate", now))], unit="")})
    if med:
        comp.append({"label": f"{peer.get('industry')} median forward P/E ({len(ps)} peers)", "show": fmt(med, 1)})
    if rel:
        comp.append({"label": "relative P/E", "show": fmt(rel, 2), "reads": BULL if rel <= 1 else BEAR,
                     "working": sum_of(rel, [line("", term("forward P/E", fpe)), line("/", term("peer median", med))], unit="")})
    for k, lab in (("pegRatio", "PEG"), ("trailingPegRatio", "PEG (trailing)"),
                   ("priceToSalesTrailing12Months", "P/S"), ("enterpriseToEbitda", "EV/EBITDA"),
                   ("trailingPE", "trailing P/E")):
        v = info.get(k)
        if isinstance(v, (int, float)):
            comp.append({"label": lab, "show": fmt(v, 2)})
    return metric(
        "fundamentals", "2.5", "Estimate revisions and valuation", rev,
        (pct(rev, 1, True) + " revision") if rev is not None else "--",
        working=comp[0]["working"] if rev is not None else None,
        formula="Revision % = (estimate now - 90 days ago) / 90 days ago x 100;  relative P/E = forward P/E / peer median",
        against=table([row("Estimates rising + valuation at or below peers", "Supports bullish", BULL),
                       row("Estimates falling + valuation above peers", "Supports bearish / vulnerable", BEAR),
                       row("Mixed", "Lowers conviction", NEUTRAL)], hit),
        compare=comp, reads=_DIR[score], score=score, weight=WEIGHTS["fundamentals"],
        means=("Whether the business supports the chart. Rising estimates tend to support rising "
               "prices; paying above peers for falling estimates is how a stock becomes vulnerable."
               + ("" if rel is not None else " (No peer median, so this scores on the revision alone.)")),
        extra={"revision": rev, "forward_pe": fpe, "peer_median": med, "relative_pe": rel},
    )


# ---- 2.6 relative strength, beta, alpha -----------------------------------------

def _aligned(a: Dict[str, List], b: Dict[str, List]) -> Tuple[List[str], List[float], List[float]]:
    bi = {s: i for i, s in enumerate(b["date"])}
    ds, x, y = [], [], []
    for i, s in enumerate(a["date"]):
        j = bi.get(s)
        if j is not None:
            ds.append(s)
            x.append(a["close"][i])
            y.append(b["close"][j])
    return ds, x, y


def rs_rating(symbol: str, d: Dict[str, List], frame) -> Optional[Dict[str, Any]]:
    """IBD-style: 0.4 x 3m + 0.2 x 6m + 0.2 x 9m + 0.2 x 12m, ranked across the market."""
    if frame is None or len(frame) < 500:
        return None
    c = d["close"]
    def ret(n): return (c[-1] / c[-1 - n] - 1) * 100 if len(c) > n else None
    has9 = "ret_9m" in frame.columns and frame["ret_9m"].notna().sum() > 500
    w = ((0.4, 63), (0.2, 126), (0.2, 189), (0.2, 252)) if has9 else ((0.4, 63), (0.3, 126), (0.3, 252))
    cols = {63: "ret_3m", 126: "ret_6m", 189: "ret_9m", 252: "ret_12m"}
    mine = [ret(n) for _, n in w]
    if any(v is None for v in mine):
        return None
    score = sum(k * v for (k, _), v in zip(w, mine))
    market = sum(k * frame[cols[n]] for k, n in w).dropna()
    rating = max(1, min(99, round((market < score).mean() * 100)))
    return {"rating": rating, "score": score, "n": int(len(market)), "has9": has9,
            "terms": [(k, n, v) for (k, n), v in zip(w, mine)]}


def relative(symbol: str, d: Dict[str, List], spy: Dict[str, List], rate: float, frame) -> Dict[str, Any]:
    ds, s, m = _aligned(d, spy)
    if len(ds) < 260:
        return missing("rs", "2.6", "Relative strength vs the S&P 500", "Not enough overlapping history with SPY.",
                       WEIGHTS["rs"])
    rs_now, rs_then = s[-1] / m[-1], s[-31] / m[-31]
    rs_chg = (rs_now / rs_then - 1) * 100
    rising = rs_chg > 0

    rsx, rmx = D.log_returns(s[-253:]), D.log_returns(m[-253:])
    mx, my = sum(rsx) / len(rsx), sum(rmx) / len(rmx)
    cov = sum((a - mx) * (b - my) for a, b in zip(rsx, rmx)) / (len(rsx) - 1)
    var = sum((b - my) ** 2 for b in rmx) / (len(rmx) - 1)
    beta = cov / var
    rho = cov / (D.stdev(rsx) * D.stdev(rmx))
    r6 = (s[-1] / s[-127] - 1) * 100
    m6 = (m[-1] / m[-127] - 1) * 100
    rf = rate * 100 * 0.5
    expected = rf + beta * (m6 - rf)
    alpha = r6 - expected

    score = 1 if rising and alpha > 0 else -1 if not rising and alpha < 0 else 0
    rat = rs_rating(symbol, d, frame)
    comp = [{"label": "RS line (stock / SPY), 6 weeks", "show": pct(rs_chg, 1, True),
             "reads": BULL if rising else BEAR,
             "working": sum_of(rs_chg, [line("", term("RS now", rs_now, 5)), line("/", term("RS 30 sessions ago", rs_then, 5)),
                                        line("-", term("one", 1, 0)), line("x", term("as a percent", 100, 0))], unit="%")},
            {"label": "beta, one year of daily returns", "show": fmt(beta, 2),
             "working": sum_of(beta, [line("", term("covariance with SPY", cov, 7)), line("/", term("variance of SPY", var, 7))], unit="")},
            {"label": "R-squared (share of its moves the market explains)", "show": pct(rho * rho * 100, 0)},
            {"label": "6-month return, stock / SPY", "show": f"{pct(r6, 1, True)} / {pct(m6, 1, True)}"},
            {"label": "CAPM expected, 6 months", "show": pct(expected, 2, True),
             "working": sum_of(expected, [line("", term("risk-free, 6 months", rf)),
                                          line("+", term("beta", beta, 2), term("SPY return - risk-free", m6 - rf))], unit="%")}]
    if rat:
        comp.insert(1, {"label": f"RS Rating (1-99, against {rat['n']:,} stocks)", "show": str(rat["rating"]),
                        "reads": BULL if rat["rating"] >= 80 else BEAR if rat["rating"] < 50 else NEUTRAL,
                        "working": sum_of(rat["score"], [line("+" if i else "", term(f"{n // 21} months x {k}", v, 1), term("weight", k, 1))
                                                         for i, (k, n, v) in enumerate(rat["terms"])], unit="%",
                                          note=("Weighted score, then ranked as a percentile across the finder's scan."
                                                + ("" if rat["has9"] else " The scan has no 9-month return yet, so 3/6/12 are "
                                                   "weighted 0.4/0.3/0.3 until the next scan adds it.")))})
    return metric(
        "rs", "2.6", "Relative strength, beta and alpha vs the S&P 500", alpha, pct(alpha, 2, True) + " alpha",
        working=sum_of(alpha, [line("", term("6-month return", r6)), line("-", term("CAPM expected", expected))], unit="%"),
        formula="RS = stock / index;  beta = cov / var;  alpha = actual - (Rf + beta x (Rm - Rf))",
        against=table([row("RS line rising and alpha above zero", "Leading, beyond what beta explains", BULL),
                       row("RS line falling and alpha below zero", "Lagging", BEAR),
                       row("Mixed", "No confirmation either way", NEUTRAL)], {1: 0, -1: 1, 0: 2}[score]),
        compare=comp, reads=_DIR[score], score=score, weight=WEIGHTS["rs"],
        means=("Confirmation, not a thesis. Leaders tend to keep leading in a healthy market; a falling "
               "RS line under a rising price is hidden weakness. Beta is a sensitivity, not a forecast: "
               f"a 1% move in the S&P has come with about {fmt(beta, 1)}% in this stock."),
        extra={"beta": beta, "alpha": alpha, "rs_change": rs_chg, "rating": rat["rating"] if rat else None},
    )


# ---- 2.7 RSI ------------------------------------------------------------------------

def rsi_series(c: List[float], n: int = 14) -> Tuple[List[Optional[float]], float, float]:
    out: List[Optional[float]] = [None] * len(c)
    ch = [b - a for a, b in zip(c, c[1:])]
    g = [max(x, 0) for x in ch]
    l = [max(-x, 0) for x in ch]
    if len(ch) < n:
        return out, 0.0, 0.0
    rsi_of = lambda ag, al: 100 - 100 / (1 + ag / al) if al else 100.0
    # The first reading sits on the 15th close, from plain averages of the
    # first 14 changes; each change after that is folded in by Wilder's
    # smoothing. (The first version skipped the 15th change entirely and
    # never produced the first reading -- the StockCharts reference series
    # in verify caught both.)
    ag, al = sum(g[:n]) / n, sum(l[:n]) / n
    out[n] = rsi_of(ag, al)
    for i in range(n, len(ch)):
        ag = (ag * (n - 1) + g[i]) / n
        al = (al * (n - 1) + l[i]) / n
        out[i + 1] = rsi_of(ag, al)
    return out, ag, al


def rsi(d: Dict[str, List]) -> Dict[str, Any]:
    c = d["close"]
    ser, ag, al = rsi_series(c)
    v = ser[-1]
    rs = ag / al if al else None
    # Divergence over the last 40 sessions: two swing highs (or lows) in
    # price, and whether RSI agrees with the second one.
    div = None
    tail = len(c) - 40
    hs = [i for i in _swings(c, 3, True) if i >= tail]
    ls = [i for i in _swings(c, 3, False) if i >= tail]
    if len(hs) >= 2 and c[hs[-1]] > c[hs[-2]] and ser[hs[-1]] < ser[hs[-2]]:
        div = ("bearish", d["date"][hs[-2]], d["date"][hs[-1]])
    elif len(ls) >= 2 and c[ls[-1]] < c[ls[-2]] and ser[ls[-1]] > ser[ls[-2]]:
        div = ("bullish", d["date"][ls[-2]], d["date"][ls[-1]])

    hit = first_hit([v > 70, v >= 50, v >= 30, True])
    score = [0, 1, -1, 0][hit]
    if div and div[0] == "bearish" and score == 1:
        score = 0
    if div and div[0] == "bullish" and score == -1:
        score = 0
    return metric(
        "rsi", "2.7", "RSI (14, Wilder)", v, fmt(v, 1),
        working=sum_of(v, [line("", term("100", 100, 0)),
                           line("-", term("100 / (1 + RS), where RS = avg gain / avg loss", 100 / (1 + rs) if rs is not None else 0, 2))], unit="",
                       note=f"Average gain {fmt(ag, 3)}, average loss {fmt(al, 3)}, so RS = {fmt(rs, 3)}. "
                            "Wilder smoothing: each new average = (previous x 13 + today) / 14."),
        formula="RSI = 100 - 100 / (1 + AvgGain / AvgLoss)",
        against=table([row("over 70", "Overbought / stretched (can stay there in strong uptrends)", NEUTRAL),
                       row("50 to 70", "Bullish momentum", BULL), row("30 to 50", "Bearish momentum", BEAR),
                       row("under 30", "Oversold", NEUTRAL)], hit),
        compare=[{"label": "RSI 5 sessions ago", "show": fmt(ser[-6], 1)}]
        + ([{"label": f"{div[0]} divergence", "show": f"price and RSI disagree between {div[1]} and {div[2]}",
             "reads": BULL if div[0] == "bullish" else BEAR}] if div else []),
        reads=_DIR[score], score=score, weight=WEIGHTS["rsi"],
        means=("Timing within a thesis, never the thesis. "
               + ("Momentum is fading under a new high -- the most useful RSI signal, and it "
                  "cancels the bullish reading." if div and div[0] == "bearish" else
                  "Selling is losing force under a new low." if div and div[0] == "bullish" else
                  ["Stretched; not an automatic short, but a poor place to chase.",
                   "Bullish momentum with room before it is stretched.",
                   "Momentum is on the sellers' side.",
                   "Oversold; not an automatic buy."][hit])),
        extra={"divergence": div[0] if div else None},
    )


# ---- 2.8 put/call, 2.9 skew -----------------------------------------------------

def put_call(ivh: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
    z = ivh.get("pc_norm") if ivh.get("status") == "ready" else None
    st = board.get("stats") or {}
    today = st.get("put_call_volume_ratio")
    if not z or z.get("z") is None:
        why = "the stock's own put/call history needs Alpaca" + (f" ({ivh.get('why')})" if ivh.get("why") else "")
        m = missing("pc", "2.8", "Put/call against its own normal", why, WEIGHTS["pc"],
                    formula="z = (P/C today - 60-day average) / 60-day stdev")
        if today is not None:
            m["compare"] = [{"label": f"today, {board['expiry']}", "show": fmt(today, 2)},
                            {"label": "typical for a single stock", "show": "about 0.6 to 0.8"}]
        return m
    zz = z["z"]
    score = -1 if zz > 2 else 1 if zz < -2 else 0
    hit = first_hit([zz > 2, zz < -2, True])
    return metric(
        "pc", "2.8", "Put/call against its own normal", zz, f"z {zz:+.2f}",
        working=sum_of(zz, [line("", term(f"P/C, {ivh.get('to')}", z["current"], 3)),
                            line("-", term(f"{z['days']}-session average", z["mean"], 3)),
                            line("/", term("its stdev", z["sd"], 3))], unit=""),
        formula="z = (P/C today - 60-day average) / 60-day stdev",
        against=table([row("z above +2", "Heavy put buying: bearish positioning or hedging (at extremes, a possible contrarian bottom)", BEAR),
                       row("z below -2", "Heavy call buying: crowded (at extremes, a possible top)", BULL),
                       row("near its average", "Neutral -- not crowded", NEUTRAL)], hit),
        compare=[{"label": "today / its normal", "show": f"{fmt(z['current'], 2)} / {fmt(z['mean'], 2)}"},
                 {"label": "Yahoo, this expiry, live", "show": fmt(today, 2) if today is not None else "--"}],
        reads=_DIR[score], score=score, weight=WEIGHTS["pc"],
        source="Front two monthlies, strikes within 25% of the price, from Alpaca daily volume",
        means="A crowd check, late, as a gut check -- never the thesis.",
    )


def _rr_today(board: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    c = [r for r in board["calls"] if r.get("delta") and r.get("iv")]
    p = [r for r in board["puts"] if r.get("delta") and r.get("iv")]
    if not c or not p:
        return None
    kc = min(c, key=lambda r: abs(r["delta"] - 0.25))
    kp = min(p, key=lambda r: abs(r["delta"] + 0.25))
    return {"call": kc, "put": kp, "rr": kc["iv"] - kp["iv"]}


def skew(ivh: Dict[str, Any], board: Dict[str, Any]) -> Dict[str, Any]:
    t = _rr_today(board)
    norm = ivh.get("rr25_norm") if ivh.get("status") == "ready" else None
    comp = []
    if t:
        comp.append({"label": f"live, {board['expiry']}",
                     "show": f"{fmt(t['rr'], 1)} pts (${fmt(t['call']['strike'])} call {pct(t['call']['iv'])}, "
                             f"${fmt(t['put']['strike'])} put {pct(t['put']['iv'])})"})
    if not norm or norm.get("z") is None:
        why = "where skew normally sits for this stock needs Alpaca" + (f" ({ivh.get('why')})" if ivh.get("why") else "")
        m = missing("skew", "2.9", "25-delta skew against its normal", why, WEIGHTS["skew"],
                    formula="25-delta risk reversal = IV(25d call) - IV(25d put)")
        m["compare"] = comp
        return m
    cur, mean, zz = norm["current"] * 100, norm["mean"] * 100, norm["z"]
    score = 1 if zz > 1.5 else -1 if zz < -1.5 else 0
    hit = first_hit([zz < -1.5, zz > 1.5, True])
    return metric(
        "skew", "2.9", "25-delta skew against its normal", cur - mean, f"{cur - mean:+.1f} pts vs normal",
        working=sum_of(cur - mean, [line("", term(f"risk reversal, {ivh.get('to')}", cur, 2)),
                                    line("-", term("its average over the year", mean, 2))], unit=""),
        formula="25-delta risk reversal = IV(25d call) - IV(25d put); read as its change from normal",
        against=table([row("more negative than usual", "Fear: downside protection in demand", BEAR),
                       row("less negative than usual, or positive", "Upside speculation rising", BULL),
                       row("about its usual level", "No signal", NEUTRAL)], hit),
        compare=[{"label": "today / normal", "show": f"{cur:+.1f} / {mean:+.1f} pts"},
                 {"label": "how unusual", "show": f"z {zz:+.2f}"}] + comp,
        reads=_DIR[score], score=score, weight=WEIGHTS["skew"],
        source="Rebuilt from Alpaca option closes",
        means=("Puts costing more than calls is the normal state, not a bearish one; the signal is "
               "the change from normal. The final 'does the options market agree with me?' check."),
    )


# ---- 2.10 the scorecard --------------------------------------------------------

LABELS = [(0.60, "Strong", "Can use more directional delta"),
          (0.30, "Moderate", "Spreads, defined risk"),
          (0.0, "Weak", "No directional trade, or a neutral strategy")]


def scorecard(signals: List[Dict[str, Any]], step1: Dict[str, Any]) -> Dict[str, Any]:
    pts = [(m, (m.get("score") or 0) * (m.get("weight") or 0)) for m in signals]
    total = sum(p for _, p in pts)
    conv = abs(total) / MAX_SCORE
    label, feeds = next((l, f) for t, l, f in LABELS if conv >= t)
    direction = BULL if total > 0 else BEAR if total < 0 else NEUTRAL
    if label == "Weak":
        direction_call = NEUTRAL
    else:
        direction_call = direction
    # The curriculum's own override: rich options and a report inside the
    # window push a strong reading down to defined risk.
    out1 = step1.get("output") or {}
    rich = (out1.get("iv_column") or {}).get("column") == "high"
    event = bool((out1.get("earnings") or {}).get("inside"))
    tempered = label == "Strong" and (rich or event)
    shown = "Moderate-to-strong" if tempered else label
    missing_n = sum(1 for m in signals if not m.get("available"))
    return {
        "rows": [{"id": m["id"], "lesson": m["lesson"], "label": m["label"], "score": m.get("score") or 0,
                  "weight": m.get("weight"), "points": p, "available": m.get("available"),
                  "reads": m.get("reads")} for m, p in pts],
        "total": total, "max": MAX_SCORE, "conviction": conv,
        "label": shown, "feeds": "Spreads, defined risk" if tempered else feeds,
        "direction": direction_call, "leaning": direction,
        "tempered": ("Options are rich" if rich else "") + (" and " if rich and event else "")
                    + ("earnings are inside the window" if event else "") if tempered else None,
        "working": sum_of(conv, [line("", term("direction score", total, 0)),
                                 line("/", term("the most it can be", MAX_SCORE, 0))], unit="",
                          note="Score each signal +1 / 0 / -1, multiply by its weight, add them up."),
        "missing": missing_n,
    }


def verdict(card: Dict[str, Any], lv: Dict[str, Any], spot: float, iv_pct: float,
            step1: Dict[str, Any]) -> Dict[str, Any]:
    d = card["direction"]
    res, sup = lv.get("resistance"), lv.get("support")
    if d == BULL:
        target, invalid = res, sup
        inv_text = f"a daily close below {money(sup)}"
    elif d == BEAR:
        target, invalid = sup, res
        inv_text = f"a daily close above {money(res)}"
    else:
        target, invalid = None, None
        inv_text = f"a daily close outside {money(sup)} to {money(res)}"
    # How long the market's own volatility takes to make the target a
    # one-standard-deviation move: t = (ln(target / price) / IV)^2.
    tf = None
    if target and iv_pct:
        yrs = (math.log(target / spot) / (iv_pct / 100)) ** 2
        days = yrs * 365
        tf = {"days": days, "low": max(7, round(days * 0.75)), "high": min(120, max(14, round(days * 1.5))),
              "working": sum_of(days, [line("", term("ln(target / price)", math.log(target / spot), 4)),
                                       line("/", term("IV", iv_pct / 100, 4)),
                                       line("x", term("itself (squared)", math.log(target / spot) / (iv_pct / 100), 4)),
                                       line("x", term("days in a year", 365, 0))], unit="",
                                note="The number of days until the target is a one-standard-deviation move "
                                     "at today's IV. The range around it is the timeframe.")}
    out1 = step1.get("output") or {}
    ev = out1.get("earnings")
    words = {BULL: "Bullish", BEAR: "Bearish", NEUTRAL: "Neutral"}[d]
    sentence = (f"{words}, {card['label'].lower()} conviction"
                + (f", {tf['low']}-{tf['high']} day timeframe" if tf else "")
                + (f", target {money(target)}" if target else f", range {money(sup)} to {money(res)}")
                + f", invalidation on {inv_text}."
                + (f" Earnings in {ev['days']} days." if ev and ev.get("days") is not None else "")
                + f" Options {'rich' if out1.get('iv_column', {}).get('column') == 'high' else 'cheap' if out1.get('iv_column', {}).get('column') == 'low' else 'fairly priced'}.")
    return {"direction": d, "target": target, "invalidation": invalid, "invalidation_text": inv_text,
            "support": sup, "resistance": res, "timeframe": tf, "sentence": sentence}


def build(ctx: Dict[str, Any], step1: Dict[str, Any]) -> Dict[str, Any]:
    d, board = ctx["daily"], ctx["board30"]
    spot = board["spot"]
    em = (step1.get("output") or {}).get("expected_move") or spot * 0.05
    from .step1 import atm_pair
    t = trend(d)
    a0 = atm_pair(board)
    day = spot * ((a0["call"]["iv"] + a0["put"]["iv"]) / 200) / 16 if a0 else 0.0
    lv = levels(d, em, day)
    pt = pattern(d)
    ca = catalyst(d, ctx["earnings"], ctx.get("implied_event"), window=max(45, board["days_to_expiry"]))
    fu = fundamentals(spot, ctx["info"], ctx["eps"], ctx["peers"], ctx["symbol"])
    rs = relative(ctx["symbol"], d, ctx["spy"], ctx["rate"], ctx["scan"]) if ctx.get("spy") else \
        missing("rs", "2.6", "Relative strength vs the S&P 500", "No SPY history.", WEIGHTS["rs"])
    ri = rsi(d)
    pc = put_call(ctx["ivh"], board)
    sk = skew(ctx["ivh"], board)
    signals = [t, lv, pt, ca, fu, rs, ri, pc, sk]
    card = scorecard(signals, step1)
    a = atm_pair(board)
    iv = (a["call"]["iv"] + a["put"]["iv"]) / 2 if a else None
    v = verdict(card, lv, spot, iv, step1)
    return {
        "available": True,
        "question": "Which way, how confident, over what time, to what target -- and where am I wrong?",
        "sections": [
            {"lesson": "2.1-2.3", "title": "Technical lean", "metrics": [t, lv, pt]},
            {"lesson": "2.4-2.5", "title": "Fundamental lean", "metrics": [ca, fu]},
            {"lesson": "2.6-2.7", "title": "Confirmation", "metrics": [rs, ri]},
            {"lesson": "2.8-2.9", "title": "What the options crowd thinks", "metrics": [pc, sk]},
        ],
        "scorecard": card,
        "output": v,
    }
