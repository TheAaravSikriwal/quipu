"""Ready-made structures, built from the board you are looking at.

Knowing you are mildly bullish is easy. Turning that into "long the 340
call, short the 350, for a $4.10 debit" is the part that stops people, and
it is mechanical: the strikes come off delta, which is the only strike
selector that transfers between a $16 stock and a $340 one.

So each setup states the view in a sentence, picks its own strikes from the
live chain, prices itself at the side of the market you would actually
cross, and reports the odds. Nothing here is a recommendation -- they are
the standard structures, filled in with today's numbers, so the trade-off
between "likely to work" and "worth much when it does" is visible before
you commit rather than after.

Deltas are the conventional choices: around 0.30 for a short strike you
want to expire worthless, 0.15 to 0.10 for the wing you buy to cap the
loss, 0.50ish for a long leg you want to actually participate.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import position as P


def _pick(rows: List[Dict], target: float) -> Optional[Dict]:
    """The listed strike whose delta is nearest the target.

    Delta rather than a percentage away from spot, because delta already
    accounts for how long there is and how much the thing moves: 0.30 is
    the same kind of bet on a sleepy utility and a biotech, where "5% out
    of the money" is two completely different trades.
    """
    usable = [r for r in rows
              if r.get("delta") is not None and (r.get("bid") or r.get("ask"))]
    if not usable:
        return None
    return min(usable, key=lambda r: abs(abs(r["delta"]) - target))


def _leg(row: Dict, kind: str, side: str, expiry: str, qty: int = 1) -> Optional[Dict]:
    """One leg, priced at the side of the market you would have to cross."""
    if not row:
        return None
    px = row.get("ask") if side == "long" else row.get("bid")
    px = px or row.get("mark") or row.get("last")
    if not px:
        return None
    return {"kind": kind, "side": side, "strike": row["strike"],
            "qty": qty, "entry": round(float(px), 4), "expiry": expiry}


def _all(*legs) -> Optional[List[Dict]]:
    """Every leg or none -- a half-built spread is a different trade."""
    return None if any(l is None for l in legs) else list(legs)


#: Each entry says what you have to believe, then builds itself.
CATALOGUE = [
    {
        "id": "buy_call", "name": "Buy a call", "view": "You think it goes up.",
        "note": "The whole cost is at risk and the clock is against you, but "
                "there is no cap on what it can make.",
        "build": lambda c, p, e, s: _all(_leg(_pick(c, 0.45), "call", "long", e)),
    },
    {
        "id": "buy_put", "name": "Buy a put", "view": "You think it goes down.",
        "note": "Same shape as buying a call, pointed the other way.",
        "build": lambda c, p, e, s: _all(_leg(_pick(p, 0.45), "put", "long", e)),
    },
    {
        "id": "bull_call", "name": "Bull call spread",
        "view": "You think it goes up, but not enormously.",
        "note": "Selling a higher call pays for part of the one you buy. "
                "Cheaper than buying outright, and the gain stops at the short strike.",
        "build": lambda c, p, e, s: _all(
            _leg(_pick(c, 0.55), "call", "long", e),
            _leg(_pick(c, 0.25), "call", "short", e)),
    },
    {
        "id": "bear_put", "name": "Bear put spread",
        "view": "You think it falls, but not off a cliff.",
        "note": "The mirror of the bull call spread.",
        "build": lambda c, p, e, s: _all(
            _leg(_pick(p, 0.55), "put", "long", e),
            _leg(_pick(p, 0.25), "put", "short", e)),
    },
    {
        "id": "csp", "name": "Cash-secured put",
        "view": "You would happily own it lower, and want paying to wait.",
        "note": "You keep the premium if it stays up. If it falls through the "
                "strike you buy the shares there, which is the point rather than the risk "
                "-- but only if you actually wanted them.",
        "build": lambda c, p, e, s: _all(_leg(_pick(p, 0.30), "put", "short", e)),
    },
    {
        "id": "covered_call", "name": "Covered call",
        "view": "You own the shares and think it drifts rather than runs.",
        "note": "Income against stock you already hold. The shares get called away "
                "if it closes above the strike.",
        "build": lambda c, p, e, s: _all(
            {"kind": "stock", "side": "long", "strike": None, "qty": 100,
             "entry": round(s, 4), "expiry": None},
            _leg(_pick(c, 0.30), "call", "short", e)),
    },
    {
        "id": "bull_put", "name": "Bull put spread",
        "view": "You think it simply stays above a level.",
        "note": "Paid up front. You keep it if the stock holds up; the long put "
                "below caps what a collapse can cost.",
        "build": lambda c, p, e, s: _all(
            _leg(_pick(p, 0.30), "put", "short", e),
            _leg(_pick(p, 0.15), "put", "long", e)),
    },
    {
        "id": "bear_call", "name": "Bear call spread",
        "view": "You think it simply stays below a level.",
        "note": "The mirror of the bull put spread.",
        "build": lambda c, p, e, s: _all(
            _leg(_pick(c, 0.30), "call", "short", e),
            _leg(_pick(c, 0.15), "call", "long", e)),
    },
    {
        "id": "iron_condor", "name": "Iron condor",
        "view": "You think it goes nowhere in particular.",
        "note": "Paid to define a range. Both ends are bought back, so the loss "
                "is capped whichever way it breaks.",
        "build": lambda c, p, e, s: _all(
            _leg(_pick(p, 0.10), "put", "long", e),
            _leg(_pick(p, 0.20), "put", "short", e),
            _leg(_pick(c, 0.20), "call", "short", e),
            _leg(_pick(c, 0.10), "call", "long", e)),
    },
    {
        "id": "straddle", "name": "Long straddle",
        "view": "You think something big happens, and do not know which way.",
        "note": "Buying both sides at the money. Needs a move larger than the "
                "two premiums together, so it is expensive to be merely right.",
        "build": lambda c, p, e, s: _all(
            _leg(_pick(c, 0.50), "call", "long", e),
            _leg(_pick(p, 0.50), "put", "long", e)),
    },
    {
        "id": "strangle", "name": "Long strangle",
        "view": "Same as the straddle, and you want it cheaper.",
        "note": "Both sides out of the money. Costs less and needs a bigger move.",
        "build": lambda c, p, e, s: _all(
            _leg(_pick(c, 0.25), "call", "long", e),
            _leg(_pick(p, 0.25), "put", "long", e)),
    },
]


def _sentence(a: Dict[str, Any], spot: float) -> str:
    """The odds and the trade-off, in one line."""
    ch = a.get("chance")
    mp, ml = a.get("max_profit"), a.get("max_loss")
    cost = a.get("net_cost", 0)
    bits = []

    if ch is not None:
        bits.append(f"About <b>{ch:.0f} in 100</b> that this finishes ahead")
    if cost > 0:
        bits.append(f"costs <b>{P._usd(cost)}</b>")
    elif cost < 0:
        bits.append(f"pays you <b>{P._usd(abs(cost))}</b> now")

    if a.get("max_profit_unbounded"):
        bits.append("no cap on the upside")
    elif mp is not None:
        bits.append(f"makes at most <b>{P._usd(mp)}</b>")
    if a.get("max_loss_unbounded"):
        bits.append("<b>no limit on the loss</b>")
    elif ml is not None:
        bits.append(f"risks at most <b>{P._usd(abs(ml))}</b>")

    bes = a.get("breakevens") or []
    if len(bes) == 1:
        bits.append(f"break-even <b>${bes[0]:,.2f}</b>")
    elif len(bes) > 1:
        bits.append(f"break-even <b>${min(bes):,.2f}</b> and <b>${max(bes):,.2f}</b>")
    return ", ".join(bits) + "."


def build(calls: List[Dict], puts: List[Dict], expiry: str, spot: float,
          vol: float, rate: float, div_yield: float = 0.0) -> List[Dict[str, Any]]:
    """Every setup that can be built from this board, priced and scored."""
    out: List[Dict[str, Any]] = []
    for spec in CATALOGUE:
        try:
            legs = spec["build"](calls, puts, expiry, spot)
        except Exception:
            legs = None
        if not legs:
            continue
        a = P.analyse(legs, spot, vol, rate, div_yield)
        if not a.get("ok"):
            continue
        out.append({
            "id": spec["id"],
            "name": spec["name"],
            "view": spec["view"],
            "note": spec["note"],
            "legs": legs,
            "chance": a.get("chance"),
            "net_cost": a.get("net_cost"),
            "debit": a.get("debit"),
            "max_profit": a.get("max_profit"),
            "max_loss": a.get("max_loss"),
            "max_profit_unbounded": a.get("max_profit_unbounded"),
            "max_loss_unbounded": a.get("max_loss_unbounded"),
            "breakevens": a.get("breakevens"),
            "summary": _sentence(a, spot),
            "detected": (a.get("strategy") or {}).get("name"),
        })
    return out
