"""Step 3 -- Build the trade (Lessons 3.1 to 3.5).

The question: what exact structure, expiration and strikes express the
view from Step 2 with the best risk/reward at today's prices?

Strategy from the Lesson 3.1 matrix (direction x conviction x IV column),
expiration from the catalyst plus a buffer (3.3), strikes from the Step 2
target and delta (3.4), then priced through the same position engine the
Workshop uses (3.2, 3.5), so the trade shown here and the trade opened
there cannot disagree.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Tuple

import position as POS

from . import data as D
from .read import (BEAR, BULL, NEUTRAL, fmt, line, metric, missing, money, pct,
                   row, sum_of, table, term)
from .step1 import atm_pair

NAMES = {
    "long_call": "Long call", "long_put": "Long put",
    "bull_call": "Bull call spread", "bear_put": "Bear put spread",
    "bull_put": "Bull put spread (credit)", "bear_call": "Bear call spread (credit)",
    "straddle": "Long straddle", "strangle": "Long strangle",
    "iron_condor": "Iron condor", "calendar": "Calendar spread", "none": "No trade",
}
SELLS = {"bull_put", "bear_call", "iron_condor"}

# Lesson 3.1, as written. Rows: (conviction, direction); columns: IV.
MATRIX = {
    ("strong", BULL): {"low": ["long_call"], "mid": ["long_call", "bull_call"], "high": ["bull_call"]},
    ("moderate", BULL): {"low": ["bull_call"], "mid": ["bull_call"], "high": ["bull_put"]},
    ("strong", BEAR): {"low": ["long_put"], "mid": ["long_put", "bear_put"], "high": ["bear_put"]},
    ("moderate", BEAR): {"low": ["bear_put"], "mid": ["bear_put"], "high": ["bear_call"]},
    ("big", NEUTRAL): {"low": ["straddle", "strangle"], "mid": ["strangle"], "high": ["none"]},
    ("range", NEUTRAL): {"low": ["calendar"], "mid": ["iron_condor"], "high": ["iron_condor"]},
}
ROW_TEXT = {("strong", BULL): "Strong bullish", ("moderate", BULL): "Moderate bullish",
            ("strong", BEAR): "Strong bearish", ("moderate", BEAR): "Moderate bearish",
            ("big", NEUTRAL): "Big move, unsure direction", ("range", NEUTRAL): "Range-bound"}


def choose(card: Dict[str, Any], col: str, event_inside: bool) -> Tuple[Tuple[str, str], str, str]:
    d = card["direction"]
    if d == NEUTRAL:
        rowk = ("big", NEUTRAL) if event_inside else ("range", NEUTRAL)
    else:
        # "Moderate-to-strong" is the curriculum's own tempering of a strong
        # reading: it stays on the strong row, but in defined risk. That is
        # how XYZ -- strong, rich IV, earnings inside -- becomes a bull call
        # spread rather than dropping a row to a credit spread.
        rowk = ("strong" if card["label"] in ("Strong", "Moderate-to-strong") else "moderate", d)
    options = MATRIX[rowk][col]
    why = ""
    pick = options[0]
    if card.get("tempered"):
        spread = {"long_call": "bull_call", "long_put": "bear_put"}
        pick = next((o for o in options if o not in spread), spread.get(options[0], options[0]))
        return rowk, pick, (f"Tempered to defined risk: {card['tempered']}, so the spread rather than "
                            "the outright option.")
    if len(options) == 2:
        # The mid-IV strong row allows either. The spread is the answer when
        # a report sits inside the window, because it is short most of the
        # vega that the report will crush.
        pick = options[1] if event_inside else options[0]
        why = ("A report is inside the window, so the spread: it gives back most of the "
               "vega the report will crush." if event_inside else
               "No report inside the window, so the outright option.")
    if pick == "calendar":
        why = ("The matrix says calendar, which needs two expiries priced against each other; "
               "the nearest thing built here is a narrow iron condor.")
        pick = "iron_condor"
    return rowk, pick, why


# ---- 3.3 expiration ------------------------------------------------------------

def expiration(all_exp: List[str], pick: str, verdict: Dict[str, Any],
               earnings: Optional[Dict[str, Any]]) -> Tuple[Optional[str], Dict[str, Any]]:
    buyer = pick not in SELLS
    tf = (verdict.get("timeframe") or {})
    ev_days = earnings["days"] if earnings and earnings.get("inside") is not None and earnings.get("days") is not None \
        and earnings["days"] >= 0 else None
    parts = [("the floor for any trade", 30)]
    if buyer:
        if tf.get("low"):
            # The start of the timeframe, as the curriculum's own XYZ choice
            # does (a 2-5 week view on a 30-day option): time you do not
            # need is premium you pay for nothing, and the exit rule already
            # closes with ten days left.
            parts.append(("start of the timeframe, plus 10 days to exit before the steep decay", tf["low"] + 10))
        if ev_days is not None and ev_days <= 90:
            parts.append(("earnings, plus a two-week buffer", ev_days + 14))
    need = max(v for _, v in parts)
    if not buyer:
        need = 30                                   # sellers: 30 to 45 days
    exp = D.expiry_after(all_exp, need)
    if buyer and exp and D.days_to(exp) > 120:
        exp = D.expiry_after(all_exp, 30)
    return exp, {
        "need": need, "parts": parts, "buyer": buyer,
        "rule": ("Buyers: 30 to 90 days, landing after the catalyst and the timeframe, and exit "
                 "with two to three weeks left." if buyer else
                 "Sellers: 30 to 45 days, close at half the credit or around 21 days left, before "
                 "gamma risk grows."),
    }


# ---- 3.4 strikes ---------------------------------------------------------------

def _near(rows: List[Dict[str, Any]], k: float, above: Optional[bool] = None) -> Optional[Dict[str, Any]]:
    ok = [r for r in rows if r.get("mark") and r.get("bid") is not None and r.get("ask")]
    if above is True:
        ok = [r for r in ok if r["strike"] >= k]
    elif above is False:
        ok = [r for r in ok if r["strike"] <= k]
    return min(ok, key=lambda r: abs(r["strike"] - k)) if ok else None


def _by_delta(rows: List[Dict[str, Any]], target: float) -> Optional[Dict[str, Any]]:
    ok = [r for r in rows if r.get("mark") and r.get("delta") is not None]
    return min(ok, key=lambda r: abs(abs(r["delta"]) - target)) if ok else None


def _wing(rows: List[Dict[str, Any]], k: float, width: float, up: bool) -> Optional[Dict[str, Any]]:
    return _near(rows, k + width if up else k - width, above=up)


def strikes(pick: str, b: Dict[str, Any], v: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """The legs, and one sentence per leg on why that strike."""
    s = b["spot"]
    calls, puts = b["calls"], b["puts"]
    atm = atm_pair(b)
    target, sup, res = v.get("target"), v.get("support"), v.get("resistance")
    width = max(2.5, round(s * 0.025 / 2.5) * 2.5)
    legs, why = [], []

    def leg(r, side):
        legs.append({"kind": r["type"], "side": side, "strike": r["strike"], "qty": 1,
                     "entry": round(r["mark"], 2), "expiry": b["expiry"],
                     "delta": r.get("delta"), "theta": r.get("theta"), "vega": r.get("vega"),
                     "bid": r.get("bid"), "ask": r.get("ask"), "oi": r.get("open_interest")})

    if pick in ("long_call", "bull_call"):
        c = atm["call"]; leg(c, "long")
        why.append(f"Buy the ${fmt(c['strike'])} call: at the money (delta {fmt(c['delta'], 2)}), balanced cost and leverage.")
        if pick == "bull_call":
            sc = _near(calls, target or s * 1.05)
            if sc and sc["strike"] > c["strike"]:
                leg(sc, "short")
                why.append(f"Sell the ${fmt(sc['strike'])} call: at the target, so the market pays you for the part of the move you do not expect.")
    elif pick in ("long_put", "bear_put"):
        p = atm["put"]; leg(p, "long")
        why.append(f"Buy the ${fmt(p['strike'])} put: at the money (delta {fmt(p['delta'], 2)}).")
        if pick == "bear_put":
            sp = _near(puts, target or s * 0.95)
            if sp and sp["strike"] < p["strike"]:
                leg(sp, "short")
                why.append(f"Sell the ${fmt(sp['strike'])} put: at the target.")
    elif pick == "bull_put":
        sp = _near(puts, sup, above=False) if sup else None
        if not sp or abs(sp.get("delta") or 0) > 0.40:
            sp = _by_delta(puts, 0.30)
        lp = _wing(puts, sp["strike"], width, up=False)
        leg(sp, "short"); leg(lp, "long")
        why += [f"Sell the ${fmt(sp['strike'])} put: at or below support, where you are wrong anyway (delta {fmt(sp['delta'], 2)}).",
                f"Buy the ${fmt(lp['strike'])} put: caps the loss at the width."]
    elif pick == "bear_call":
        sc = _near(calls, res, above=True) if res else None
        if not sc or abs(sc.get("delta") or 0) > 0.40:
            sc = _by_delta(calls, 0.30)
        lc = _wing(calls, sc["strike"], width, up=True)
        leg(sc, "short"); leg(lc, "long")
        why += [f"Sell the ${fmt(sc['strike'])} call: at or above resistance (delta {fmt(sc['delta'], 2)}).",
                f"Buy the ${fmt(lc['strike'])} call: caps the loss at the width."]
    elif pick == "straddle":
        leg(atm["call"], "long"); leg(atm["put"], "long")
        why.append(f"Buy the ${fmt(atm['strike'])} call and put: pays if it moves more than the straddle, either way.")
    elif pick == "strangle":
        c, p = _by_delta(calls, 0.25), _by_delta(puts, 0.25)
        leg(c, "long"); leg(p, "long")
        why.append(f"Buy the ${fmt(c['strike'])} call and ${fmt(p['strike'])} put, both about 25 delta: cheaper than the straddle, needs a bigger move.")
    elif pick == "iron_condor":
        # Short strikes at the Step 2 range edges -- unless an edge is so
        # close to the price that selling it is a coin flip (delta over
        # 0.35), in which case the 20-delta strike stands in, and says so.
        def edge(rows, level, above, kind, word):
            r = _near(rows, level, above=above) if level else None
            if r and abs(r.get("delta") or 0) <= 0.35:
                return r, f"at {word} ${fmt(level)} from Step 2 (delta {fmt(r['delta'], 2)})"
            alt = _by_delta(rows, 0.20)
            return alt, (f"{word} at ${fmt(level)} is too close to sell (delta "
                         f"{fmt(abs(r['delta']) if r and r.get('delta') is not None else 0, 2)}), so the 20-delta "
                         f"{kind} instead" if level else f"the 20-delta {kind}")
        sp, wp = edge(puts, sup, False, "put", "support")
        sc, wc = edge(calls, res, True, "call", "resistance")
        lp, lc = _wing(puts, sp["strike"], width, up=False), _wing(calls, sc["strike"], width, up=True)
        for r, sd in ((lp, "long"), (sp, "short"), (sc, "short"), (lc, "long")):
            leg(r, sd)
        why += [f"Sell the ${fmt(sp['strike'])} put: {wp}.",
                f"Sell the ${fmt(sc['strike'])} call: {wc}.",
                f"Buy the ${fmt(lp['strike'])} put and ${fmt(lc['strike'])} call: the wings that cap the loss."]
    return legs, why


# ---- 3.2 and 3.5: the numbers ------------------------------------------------

def p_above(s: float, x: float, t: float, vol: float, r: float, q: float) -> float:
    d2 = (math.log(s / x) + (r - q - 0.5 * vol * vol) * t) / (vol * math.sqrt(t))
    return D.norm_cdf(d2)


def expected_value(a: Dict[str, Any], s: float, t: float, vol: float, r: float, q: float
                   ) -> Optional[Dict[str, Any]]:
    """EV ~ P(win) x avg win - P(loss) x avg loss, over the model's distribution.

    Integrated on the payoff curve the engine already drew, weighted by
    the lognormal density at each price. Risk-neutral, so an EV near
    zero is the expected answer: the model assumes no edge, and any edge
    is whatever Step 2 added."""
    curve = a.get("curve") or []
    if len(curve) < 10:
        return None
    pts = sorted((float(p["s"]), float(p["pl"])) for p in curve)
    sd = vol * math.sqrt(t)
    mu = math.log(s) + (r - q - 0.5 * vol * vol) * t
    wins = losses = pw = pl = 0.0
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        if x0 <= 0:
            continue
        pr = D.norm_cdf((math.log(x1) - mu) / sd) - D.norm_cdf((math.log(x0) - mu) / sd)
        y = (y0 + y1) / 2
        if y > 0:
            wins += pr * y; pw += pr
        elif y < 0:
            losses += pr * -y; pl += pr
    if pw + pl == 0:
        return None
    aw, al = (wins / pw if pw else 0), (losses / pl if pl else 0)
    ev = pw * aw - pl * al
    return {"ev": ev, "p_win": pw, "avg_win": aw, "p_loss": pl, "avg_loss": al,
            "working": sum_of(ev, [line("", term("chance of a profit", pw, 3), term("average profit", aw)),
                                   line("-", term("chance of a loss", pl, 3), term("average loss", al))],
                              note="Over the model's own distribution of prices at expiry, so it assumes no edge. "
                                   "Near zero is normal; your Step 2 analysis is what is supposed to tilt it.")}


def formula_working(pick: str, legs: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Lesson 3.2's own equations, written out for this trade."""
    L = {(l["kind"], l["side"]): l for l in legs}
    if pick == "bull_call" and len(legs) == 2:
        k1, k2 = L[("call", "long")], L[("call", "short")]
        d = k1["entry"] - k2["entry"]; w = k2["strike"] - k1["strike"]
        return {"D": d, "W": w, "rows": [
            ("Debit D", d, sum_of(d, [line("", term(f"${fmt(k1['strike'])} call", k1["entry"])),
                                      line("-", term(f"${fmt(k2['strike'])} call", k2["entry"]))], per_share=True)),
            ("Max profit", w - d, sum_of(w - d, [line("", term("width W", w)), line("-", term("debit D", d))], per_share=True)),
            ("Max loss", d, sum_of(d, [line("", term("debit D", d))], per_share=True)),
            ("Breakeven", k1["strike"] + d, sum_of(k1["strike"] + d, [line("", term("long strike", k1["strike"])), line("+", term("debit D", d))])),
            ("Reward/risk", (w - d) / d, sum_of((w - d) / d, [line("", term("max profit", w - d)), line("/", term("max loss", d))], unit="")),
        ]}
    if pick == "bear_put" and len(legs) == 2:
        k2, k1 = L[("put", "long")], L[("put", "short")]
        d = k2["entry"] - k1["entry"]; w = k2["strike"] - k1["strike"]
        return {"D": d, "W": w, "rows": [
            ("Debit D", d, sum_of(d, [line("", term(f"${fmt(k2['strike'])} put", k2["entry"])),
                                      line("-", term(f"${fmt(k1['strike'])} put", k1["entry"]))], per_share=True)),
            ("Max profit", w - d, sum_of(w - d, [line("", term("width W", w)), line("-", term("debit D", d))], per_share=True)),
            ("Max loss", d, sum_of(d, [line("", term("debit D", d))], per_share=True)),
            ("Breakeven", k2["strike"] - d, sum_of(k2["strike"] - d, [line("", term("long strike", k2["strike"])), line("-", term("debit D", d))])),
            ("Reward/risk", (w - d) / d, sum_of((w - d) / d, [line("", term("max profit", w - d)), line("/", term("max loss", d))], unit="")),
        ]}
    if pick in ("bull_put", "bear_call") and len(legs) == 2:
        kind = "put" if pick == "bull_put" else "call"
        sh, lo = L[(kind, "short")], L[(kind, "long")]
        c = sh["entry"] - lo["entry"]; w = abs(sh["strike"] - lo["strike"])
        be = sh["strike"] - c if kind == "put" else sh["strike"] + c
        return {"C": c, "W": w, "rows": [
            ("Credit C", c, sum_of(c, [line("", term(f"${fmt(sh['strike'])} {kind} sold", sh["entry"])),
                                       line("-", term(f"${fmt(lo['strike'])} {kind} bought", lo["entry"]))], per_share=True)),
            ("Max profit", c, sum_of(c, [line("", term("credit C", c))], per_share=True)),
            ("Max loss", w - c, sum_of(w - c, [line("", term("width W", w)), line("-", term("credit C", c))], per_share=True)),
            ("Breakeven", be, sum_of(be, [line("", term("short strike", sh["strike"])),
                                          line("-" if kind == "put" else "+", term("credit C", c))])),
        ]}
    if pick == "iron_condor" and len(legs) == 4:
        sp, sc = L[("put", "short")], L[("call", "short")]
        lp, lc = L[("put", "long")], L[("call", "long")]
        c = sp["entry"] + sc["entry"] - lp["entry"] - lc["entry"]
        w = max(sp["strike"] - lp["strike"], lc["strike"] - sc["strike"])
        return {"C": c, "W": w, "rows": [
            ("Credit C", c, sum_of(c, [line("", term(f"${fmt(sp['strike'])} put sold", sp["entry"])),
                                       line("+", term(f"${fmt(sc['strike'])} call sold", sc["entry"])),
                                       line("-", term(f"${fmt(lp['strike'])} put bought", lp["entry"])),
                                       line("-", term(f"${fmt(lc['strike'])} call bought", lc["entry"]))], per_share=True)),
            ("Max profit", c, sum_of(c, [line("", term("total credit", c))], per_share=True)),
            ("Max loss", w - c, sum_of(w - c, [line("", term("wider wing's width", w)), line("-", term("total credit", c))], per_share=True)),
            ("Breakeven", sp["strike"] - c, sum_of(sp["strike"] - c, [line("", term("short put", sp["strike"])), line("-", term("credit", c))])),
            ("Breakeven", sc["strike"] + c, sum_of(sc["strike"] + c, [line("", term("short call", sc["strike"])), line("+", term("credit", c))])),
        ]}
    if pick in ("straddle", "strangle") and len(legs) == 2:
        call, put = L[("call", "long")], L[("put", "long")]
        tot = call["entry"] + put["entry"]
        return {"rows": [
            ("Total premium", tot, sum_of(tot, [line("", term(f"${fmt(call['strike'])} call", call["entry"])),
                                                line("+", term(f"${fmt(put['strike'])} put", put["entry"]))], per_share=True)),
            ("Max loss", tot, sum_of(tot, [line("", term("total premium", tot))], per_share=True)),
            ("Breakeven", call["strike"] + tot, sum_of(call["strike"] + tot, [line("", term("call strike", call["strike"])), line("+", term("total premium", tot))])),
            ("Breakeven", put["strike"] - tot, sum_of(put["strike"] - tot, [line("", term("put strike", put["strike"])), line("-", term("total premium", tot))])),
        ]}
    if pick in ("long_call", "long_put") and len(legs) == 1:
        l = legs[0]; p = l["entry"]
        be = l["strike"] + p if l["kind"] == "call" else l["strike"] - p
        return {"rows": [
            ("Premium p", p, sum_of(p, [line("", term("premium", p))], per_share=True)),
            ("Max loss", p, sum_of(p, [line("", term("premium p", p))], per_share=True)),
            ("Breakeven", be, sum_of(be, [line("", term("strike", l["strike"])), line("+" if l["kind"] == "call" else "-", term("premium p", p))])),
        ]}
    return None


def build(ctx: Dict[str, Any], step1: Dict[str, Any], step2: Dict[str, Any]) -> Dict[str, Any]:
    card, v = step2["scorecard"], step2["output"]
    o1 = step1.get("output") or {}
    col = (o1.get("iv_column") or {}).get("column", "mid")
    ev = o1.get("earnings")
    rowk, pick, why_pick = choose(card, col, bool(ev and ev.get("inside")))

    matrix = {"rows": [{"key": f"{k[0]}:{k[1]}", "label": ROW_TEXT[k],
                        "cells": {c: " / ".join(NAMES[x] for x in MATRIX[k][c]) for c in ("low", "mid", "high")}}
                       for k in MATRIX],
              "row": f"{rowk[0]}:{rowk[1]}", "column": col, "by": (o1.get("iv_column") or {}).get("by")}
    base = {"available": True, "question": "What exact structure, expiration and strikes express the view?",
            "matrix": matrix, "strategy": pick, "name": NAMES[pick], "why": why_pick}
    if pick == "none":
        return {**base, "legs": [], "summary": "No trade: with no direction and rich IV the move is already "
                                               "priced in, and buying it is paying for what the market expects."}

    exp, ex = expiration(ctx["all_expiries"], pick, v, ev)
    if not exp:
        return {**base, "available": False, "why": "No listed expiry far enough out."}
    b = ctx["board_for"](exp)
    if not b:
        return {**base, "available": False, "why": f"Could not load the {exp} board."}
    legs, why_k = strikes(pick, b, v)
    if not legs:
        return {**base, "available": False, "why": "Could not find quoted strikes for this structure."}

    a = atm_pair(b)
    vol = (a["call"]["iv"] + a["put"]["iv"]) / 200 if a else 0.3
    rate, q = b.get("rate") or ctx["rate"], b.get("div_yield") or 0.0
    an = POS.analyse([{k: l[k] for k in ("kind", "side", "strike", "qty", "entry", "expiry")} for l in legs],
                     b["spot"], vol, rate, q)
    t = b["days_to_expiry"] / 365
    s = b["spot"]
    bes = an.get("breakevens") or []

    # 3.5 probabilities, by the curriculum's own formula.
    probs = []
    for be in bes:
        pa = p_above(s, be, t, vol, rate, q)
        probs.append({"label": f"finishes above ${fmt(be)}", "value": pa * 100,
                      "working": sum_of(pa * 100, [line("", term(f"N(d2) at K = ${fmt(be)}", pa, 4,
                                                                  note="d2 = [ln(S/K) + (r - q - IV^2/2) T] / (IV sqrt T): the "
                                                                       "risk-neutral chance of finishing above K.")),
                                                   line("x", term("as a percent", 100, 0))], unit="%")})
    if len(bes) == 2:
        lo, hi = sorted(bes)
        inside = p_above(s, lo, t, vol, rate, q) - p_above(s, hi, t, vol, rate, q)
        # Which side of the pair makes money decides what "profit" means.
        mid_pl = min((p for p in an.get("curve") or []), key=lambda p: abs(p["s"] - (lo + hi) / 2), default=None)
        wins_inside = bool(mid_pl and mid_pl["pl"] > 0)
        pp = inside if wins_inside else 1 - inside
        probs.append({"label": (f"finishes between ${fmt(lo)} and ${fmt(hi)}" if wins_inside
                                else f"finishes outside ${fmt(lo)} to ${fmt(hi)}"),
                      "value": pp * 100, "profit": True,
                      "working": sum_of(pp * 100, ([line("", term(f"above ${fmt(lo)}", p_above(s, lo, t, vol, rate, q), 4)),
                                                   line("-", term(f"above ${fmt(hi)}", p_above(s, hi, t, vol, rate, q), 4))]
                                                  if wins_inside else
                                                  [line("", term("one", 1, 0)),
                                                   line("-", term(f"above ${fmt(lo)}", p_above(s, lo, t, vol, rate, q), 4)),
                                                   line("+", term(f"above ${fmt(hi)}", p_above(s, hi, t, vol, rate, q), 4))])
                                        + [line("x", term("as a percent", 100, 0))], unit="%")})
    elif len(bes) == 1:
        probs[0]["profit"] = True
        up = (an.get("curve") or [{}])[-1].get("pl", 0) > 0
        if not up:
            pa = probs[0]["value"] / 100
            probs[0] = {"label": f"finishes below ${fmt(bes[0])}", "value": (1 - pa) * 100, "profit": True,
                        "working": sum_of((1 - pa) * 100, [line("", term("one", 1, 0)),
                                                           line("-", term(f"N(d2) at K = ${fmt(bes[0])}", pa, 4)),
                                                           line("x", term("as a percent", 100, 0))], unit="%")}
    tgt = v.get("target")
    touch = None
    if tgt:
        pt = p_above(s, tgt, t, vol, rate, q)
        pt = pt if tgt > s else 1 - pt
        touch = {"finish": pt * 100, "touch": min(100, 2 * pt * 100), "target": tgt,
                 "working": sum_of(min(1, 2 * pt) * 100, [line("", term(f"chance of finishing past ${fmt(tgt)}", pt, 4)),
                                                          line("x", term("touch rule", 2, 0)),
                                                          line("x", term("as a percent", 100, 0))], unit="%")}
    evv = expected_value(an, s, t, vol, rate, q)

    # Position greeks, per leg and net, against the naked long leg.
    gl = []
    for l in legs:
        sg = 1 if l["side"] == "long" else -1
        gl.append({"leg": f"{l['side']} ${fmt(l['strike'])} {l['kind']}",
                   "delta": sg * (l["delta"] or 0), "theta": sg * (l["theta"] or 0), "vega": sg * (l["vega"] or 0)})
    net = {k: sum(g[k] for g in gl) for k in ("delta", "theta", "vega")}
    naked = next((g for g in gl if g["leg"].startswith("long")), None)

    maxp = an.get("max_profit"); maxl = an.get("max_loss")
    return {
        **base, "expiry": exp, "dte": b["days_to_expiry"], "expiration": ex, "strike_why": why_k,
        "legs": legs, "spot": s, "vol": vol * 100,
        "formulas": formula_working(pick, legs),
        "payoff": {
            "net_cost": an.get("net_cost"), "debit": an.get("debit"),
            "max_profit": maxp, "max_loss": maxl,
            "max_profit_unbounded": an.get("max_profit_unbounded"),
            "max_loss_unbounded": an.get("max_loss_unbounded"),
            "breakevens": bes, "chance": an.get("chance"), "chance_working": an.get("chance_working"),
            "reward_risk": (maxp / abs(maxl)) if maxp and maxl and not an.get("max_profit_unbounded") else None,
            "curve": an.get("curve"), "working": an.get("working"),
            "best_at": an.get("best_at"), "worst_at": an.get("worst_at"),
        },
        "probability": {"breakevens": probs, "touch": touch, "ev": evv},
        "greeks": {"legs": gl, "net": net, "naked": naked,
                   "engine": an.get("greeks"), "working": an.get("greek_working")},
        "strategy_engine": (an.get("strategy") or {}).get("name"),
    }
