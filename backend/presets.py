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


def _price_of(row: Dict, side: str = "long") -> Optional[float]:
    """What one contract can be priced at, in order of preference.

    The side of the market you would have to cross, when there is one.
    Outside trading hours there is not: every bid and ask on the board
    comes back 0.00, while `mark` and `last` stay perfectly good.

    That broke every ready-made setup between the close and the open.
    _leg already fell back to the mark, but the strike PICKER insisted
    on a live quote, so it found no usable row and the whole catalogue
    came back empty -- on an evening or a weekend, which is when
    somebody is most likely to be sitting and planning a trade.
    """
    px = row.get("ask") if side == "long" else row.get("bid")
    return px or row.get("mark") or row.get("last") or None


def _quotable(row: Dict) -> bool:
    """Whether a row can be turned into a leg at all."""
    return _price_of(row, "long") is not None or _price_of(row, "short") is not None


def _pick(rows: List[Dict], target: float,
          below: Optional[float] = None,
          above: Optional[float] = None) -> Optional[Dict]:
    """The listed strike whose delta is nearest the target.

    Delta rather than a percentage away from spot, because delta already
    accounts for how long there is and how much the thing moves: 0.30 is
    the same kind of bet on a sleepy utility and a biotech, where "5% out
    of the money" is two completely different trades.

    `below` and `above` bound the strike, and exist because nearest-delta
    on its own is not enough. On a one-day chain the deltas collapse
    towards 0 and 1 within a couple of strikes, so the 0.20 and the 0.10
    call both resolved to 345 -- and an iron condor whose two call legs
    sit on the same strike has no call side at all. It was still named
    an iron condor, and was really a put spread wearing the label.

    Returning nothing is the right answer when the chain cannot express
    the structure: _all then refuses to build it, and a setup that
    cannot be built honestly is better missing than wrong.
    """
    usable = [r for r in rows
              if r.get("delta") is not None and _quotable(r)]
    if below is not None:
        usable = [r for r in usable if r["strike"] < below]
    if above is not None:
        usable = [r for r in usable if r["strike"] > above]
    if not usable:
        return None
    return min(usable, key=lambda r: abs(abs(r["delta"]) - target))


def _leg(row: Dict, kind: str, side: str, expiry: str, qty: int = 1) -> Optional[Dict]:
    """One leg, priced at the side of the market you would have to cross."""
    if not row:
        return None
    px = _price_of(row, side)
    if not px:
        return None
    return {"kind": kind, "side": side, "strike": row["strike"],
            "qty": qty, "entry": round(float(px), 4), "expiry": expiry,
            # Kept for the detail view: the delta is the reason this strike
            # was chosen rather than the one next to it, and "the market
            # gives this about a 30% chance of finishing in the money" is
            # the only honest way to explain a strike choice to someone who
            # did not make it.
            "delta": row.get("delta"), "iv": row.get("iv")}


def _at(rows: List[Dict], strike: Optional[float]) -> Optional[Dict]:
    """The row on one exact strike.

    An iron butterfly sells the call and the put on the SAME strike, and
    a synthetic long buys and sells one. Picking each side by nearest
    delta independently lands them a strike or two apart, which is a
    different structure wearing the name -- an iron condor, in the
    butterfly's case.
    """
    if strike is None:
        return None
    for r in rows:
        if r.get("strike") == strike and _quotable(r):
            return r
    return None


def _wings(rows, centre, rungs: int = 2):
    """The two listed strikes the SAME DISTANCE either side of `centre`.

    A butterfly is symmetric by definition -- equal distance out on both
    sides, so the two halves cancel and the thing has a peak rather than
    a slope. Picking each wing by delta instead gave 332.5 and 340
    around a 337.5 body: five dollars down against two and a half up,
    which is a broken-wing butterfly, a different structure with a
    different payoff, wearing this one's name.

    Delta also stops discriminating near expiry. On a board with a day
    left the calls either side of the money run 0.88 and 0.08, so
    "the 0.70 call" is whichever strike happens to be least wrong, and
    on a thin ladder there may be none that can be quoted at all.

    Distance out is measured in dollars rather than rungs because the
    ladder does not keep one spacing across the board -- 2.50 near the
    money and 5.00 further out is normal, and counting rungs would pick
    an asymmetric pair and call it symmetric.
    """
    ladder = sorted({r["strike"] for r in rows
                     if r.get("strike") is not None and _quotable(r)})
    if centre not in ladder:
        return None, None

    # A sensible width to aim for: a couple of rungs of whatever this
    # ladder's spacing is NEAR THE CENTRE. Measured locally because a
    # board is not evenly spaced -- 2.50 around the money and 10 out in
    # the tails is ordinary, and the median across the whole ladder
    # said 5 and built a butterfly twice as wide as the strikes
    # actually available around the body.
    near = [k for k in ladder if abs(k - centre) <= max(centre * 0.06, 2 * 2.5)]
    gaps = [round(b - a, 4) for a, b in zip(near, near[1:]) if b > a]         or [round(b - a, 4) for a, b in zip(ladder, ladder[1:]) if b > a]
    if not gaps:
        return None, None
    step = sorted(gaps)[len(gaps) // 2]
    want = step * rungs

    # Every width that has a listed strike on BOTH sides, nearest to
    # what we wanted first.
    usable = []
    for k in ladder:
        w = round(abs(k - centre), 4)
        if w <= 0:
            continue
        lo, hi = _at(rows, round(centre - w, 4)), _at(rows, round(centre + w, 4))
        if lo and hi:
            usable.append((abs(w - want), lo, hi))
    if not usable:
        return None, None
    usable.sort(key=lambda t: t[0])
    return usable[0][1], usable[0][2]


def _stock(spot: float) -> Dict[str, Any]:
    return {"kind": "stock", "side": "long", "strike": None, "qty": 100,
            "entry": round(spot, 4), "expiry": None}


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
        "build": lambda c, p, e, s: (lambda lo: _all(
            _leg(lo, "call", "long", e),
            _leg(_pick(c, 0.25, above=lo["strike"]) if lo else None,
                 "call", "short", e)))(_pick(c, 0.55)),
    },
    {
        "id": "bear_put", "name": "Bear put spread",
        "view": "You think it falls, but not off a cliff.",
        "note": "The mirror of the bull call spread.",
        "build": lambda c, p, e, s: (lambda hi: _all(
            _leg(hi, "put", "long", e),
            _leg(_pick(p, 0.25, below=hi["strike"]) if hi else None,
                 "put", "short", e)))(_pick(p, 0.55)),
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
        "build": lambda c, p, e, s: (lambda sh: _all(
            _leg(sh, "put", "short", e),
            _leg(_pick(p, 0.15, below=sh["strike"]) if sh else None,
                 "put", "long", e)))(_pick(p, 0.30)),
    },
    {
        "id": "bear_call", "name": "Bear call spread",
        "view": "You think it simply stays below a level.",
        "note": "The mirror of the bull put spread.",
        "build": lambda c, p, e, s: (lambda sh: _all(
            _leg(sh, "call", "short", e),
            _leg(_pick(c, 0.15, above=sh["strike"]) if sh else None,
                 "call", "long", e)))(_pick(c, 0.30)),
    },
    {
        "id": "iron_condor", "name": "Iron condor",
        "view": "You think it goes nowhere in particular.",
        "note": "Paid to define a range. Both ends are bought back, so the loss "
                "is capped whichever way it breaks.",
        "build": lambda c, p, e, s: (lambda ps, cs: _all(
            _leg(_pick(p, 0.10, below=ps["strike"]) if ps else None, "put", "long", e),
            _leg(ps, "put", "short", e),
            _leg(cs, "call", "short", e),
            _leg(_pick(c, 0.10, above=cs["strike"]) if cs else None, "call", "long", e),
        ))(_pick(p, 0.20), _pick(c, 0.20)),
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
        # A strangle wants the two strikes apart; at the money they are
        # the same trade as a straddle and cost more to be so.
        "build": lambda c, p, e, s: _all(
            _leg(_pick(c, 0.25, above=s), "call", "long", e),
            _leg(_pick(p, 0.25, below=s), "put", "long", e)),
    },
    {
        "id": "married_put", "name": "Married put",
        "view": "You want to own it, and you want a floor under it.",
        "note": "The shares plus a put is stock you cannot lose more than a "
                "known amount on. The put costs money every time you buy one, "
                "which is the premium for sleeping at night.",
        "build": lambda c, p, e, s: _all(
            _stock(s), _leg(_pick(p, 0.35), "put", "long", e)),
    },
    {
        "id": "collar", "name": "Collar",
        "view": "You own it, want a floor, and will give up the top to pay for it.",
        "note": "A married put with a call sold above to fund the put. Often "
                "costs almost nothing to put on -- the trade is that the "
                "upside stops at the call strike.",
        "build": lambda c, p, e, s: _all(
            _stock(s),
            _leg(_pick(p, 0.25), "put", "long", e),
            _leg(_pick(c, 0.25), "call", "short", e)),
    },
    {
        "id": "call_fly", "name": "Long call butterfly",
        "view": "You think it lands close to one particular price.",
        "note": "Cheap, and it pays only if the stock finishes near the middle "
                "strike. Wrong by a few dollars either way and it expires at "
                "nothing, so it is a narrow bet bought at a narrow price.",
        "build": lambda c, p, e, s: (lambda mid: (lambda w: _all(
            _leg(w[0], "call", "long", e),
            _leg(mid, "call", "short", e, 2),
            _leg(w[1], "call", "long", e),
        ))(_wings(c, mid["strike"]) if mid else (None, None)))(_pick(c, 0.50)),
    },
    {
        "id": "iron_fly", "name": "Iron butterfly",
        "view": "You think it finishes very close to where it is now.",
        "note": "Pays more than an iron condor and gives you a much smaller "
                "target. Sold at the money on both sides, with wings bought "
                "to cap what being wrong can cost.",
        "build": lambda c, p, e, s: (lambda atm: _all(
            _leg(_pick(p, 0.15, below=atm), "put", "long", e),
            _leg(_at(p, atm), "put", "short", e),
            _leg(_at(c, atm), "call", "short", e),
            _leg(_pick(c, 0.15, above=atm), "call", "long", e),
        ))((_pick(c, 0.50) or {}).get("strike")),
    },
    {
        "id": "short_strangle", "name": "Short strangle",
        "view": "You think it stays inside a range, and want paying for it.",
        "note": "Sells both sides and keeps the premium if neither is reached. "
                "Nothing is bought back, so a large move in either direction "
                "costs more than the whole credit -- on the call side there is "
                "no ceiling on it at all.",
        "build": lambda c, p, e, s: _all(
            _leg(_pick(c, 0.20, above=s), "call", "short", e),
            _leg(_pick(p, 0.20, below=s), "put", "short", e)),
    },
    {
        "id": "synthetic_long", "name": "Synthetic long stock",
        "view": "You want the shares' payoff without buying the shares.",
        "note": "A call bought and a put sold on the same strike behave almost "
                "exactly like a hundred shares, for a fraction of the cash. "
                "The loss below the strike is the same as owning it.",
        "build": lambda c, p, e, s: (lambda atm: _all(
            _leg(_at(c, atm), "call", "long", e),
            _leg(_at(p, atm), "put", "short", e),
        ))((_pick(c, 0.50) or {}).get("strike")),
    },
]


def _usd(v: float) -> str:
    return P._usd(v)


def _years(expiry: str) -> float:
    return P._years(expiry) or (1 / 252.0)


def _px(v: float) -> str:
    """A price per share, always to the cent.

    _usd drops the cents above $100, which is right for a total and wrong
    for a number someone is going to type into an order ticket: it
    rendered a $341.22 share as "$341". Same failure as rounding a 337.5
    strike to 338 -- a correct total sitting on top of a price that was
    never quoted.
    """
    return f"${v:,.2f}"


def _strike(v: float) -> str:
    """A strike, printed as the contract is actually listed.

    Rounding to whole dollars turned the 337.5 put into "338" -- a
    contract that does not exist. Every number under it was right, which
    is what made it dangerous: the arithmetic checked out and the ticket
    would have been wrong.
    """
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}".rstrip("0").rstrip(".")


def _leg_words(leg: Dict[str, Any]) -> Dict[str, Any]:
    """One leg, spelled out the way you would say it out loud."""
    qty = int(leg.get("qty") or 1)
    side = "Buy" if leg["side"] == "long" else "Sell"
    cash = float(leg.get("entry") or 0) * qty * (1 if leg["kind"] == "stock" else 100)

    if leg["kind"] == "stock":
        what = f"{qty} shares"
        why = "The shares themselves, which is what the call is sold against."
    else:
        what = (f"{qty} contract{'s' if qty > 1 else ''} of the "
                f"{_strike(leg['strike'])} {leg['kind']}")
        d = leg.get("delta")
        if d is None:
            why = ""
        else:
            pct = abs(d) * 100
            moneyness = ("roughly at the money" if pct > 45
                         else "close to the money" if pct > 35
                         else "a fair way out of the money" if pct > 18
                         else "well out of the money")
            role = ("Bought to cap the loss rather than to make money."
                    if leg["side"] == "long" and pct < 20
                    else "This is the leg that has to work."
                    if leg["side"] == "long" and pct > 35
                    else "Sold to bring in the premium; you keep it if the "
                         "price stays away from this strike."
                    if leg["side"] == "short" else "")
            why = (f"Chosen because it is {moneyness} — the market puts the "
                   f"odds of it finishing in the money at about {pct:.0f}%. {role}").strip()

    return {
        "text": f"{side} {what} at {_px(leg['entry'])} a share",
        "cash": round(cash if leg["side"] == "long" else -cash, 2),
        "direction": "out" if leg["side"] == "long" else "in",
        "why": why,
        "iv": leg.get("iv"),
    }


def _sentence(a: Dict[str, Any], spot: float) -> str:
    """The trade-off -- what it costs, what it can do -- in one line."""
    mp, ml = a.get("max_profit"), a.get("max_loss")
    cost = a.get("net_cost", 0)
    bits = []

    # The odds used to lead this sentence as "about 40 in 100 that this
    # finishes ahead", which is a percentage wearing a hat. It is the
    # headline figure on the card now, said as a percentage, so repeating
    # it here in worse words only made the card longer.
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
    out = ", ".join(bits) + "."
    return out[:1].upper() + out[1:]


#: What the SHAPE has to be for each setup, asserted here and checked
#: against what the payoff actually turns out to want. A "bull" call
#: spread built upside-down off a thin chain is not bullish, and the
#: label would go on saying it was.
DECLARED_BIAS = {
    "buy_call": "bullish",      "buy_put": "bearish",
    "bull_call": "bullish",     "bear_put": "bearish",
    "csp": "bullish",           "covered_call": "bullish",
    "bull_put": "bullish",      "bear_call": "bearish",
    "iron_condor": "neutral",   "straddle": "either",
    "strangle": "either",       "married_put": "bullish",
    "collar": "bullish",        "call_fly": "neutral",
    "iron_fly": "neutral",      "short_strangle": "neutral",
    "synthetic_long": "bullish",
}

# The derivation lives with the payoff it is read from -- the position
# workspace shows the same thing for a hand-built spread, and two copies
# of this would be two chances to disagree about which way a trade leans.
bias_of = P.bias_of


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
            "legs_explained": [_leg_words(l) for l in legs],
            "days_left": a.get("days_left"),
            "expiry": expiry,
            "id": spec["id"],
            "name": spec["name"],
            "view": spec["view"],
            "note": spec["note"],
            "legs": legs,
            "chance": a.get("chance"),
            "chance_working": a.get("chance_working"),
            "net_cost": a.get("net_cost"),
            "debit": a.get("debit"),
            "max_profit": a.get("max_profit"),
            "max_loss": a.get("max_loss"),
            "max_profit_unbounded": a.get("max_profit_unbounded"),
            "max_loss_unbounded": a.get("max_loss_unbounded"),
            "breakevens": a.get("breakevens"),
            "needs": a.get("needs"),
            **bias_of(a.get("needs")),
            "best_at": a.get("best_at"),
            "worst_at": a.get("worst_at"),
            "summary": _sentence(a, spot),
            "detected": (a.get("strategy") or {}).get("name"),
        })
    return out
