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
            "qty": qty, "entry": round(float(px), 4), "expiry": expiry,
            # Kept for the detail view: the delta is the reason this strike
            # was chosen rather than the one next to it, and "the market
            # gives this about a 30% chance of finishing in the money" is
            # the only honest way to explain a strike choice to someone who
            # did not make it.
            "delta": row.get("delta"), "iv": row.get("iv")}


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


def _curve(legs: List[Dict], spot: float, vol: float, years: float) -> List[Dict]:
    """The payoff, drawn over the range the stock can actually reach.

    analyse() scans from 40% to 180% of spot, which is the right range to
    hunt for break-evens in and the wrong one to draw: on a one-day
    expiry it put $136 and $621 on the axis of an Apple chart and squeezed
    every strike that mattered into a sliver in the middle.

    So the width comes from the move the option itself is priced for --
    three standard deviations either side, which is where the lognormal
    has essentially all of its mass -- and is then widened if it has to be
    to keep every strike on the page.
    """
    norm = [P._norm(l) for l in legs]
    strikes = [l["strike"] for l in norm if l["strike"]]

    sd = (vol or 0.3) * (max(years, 1 / 252.0) ** 0.5)
    band = max(3.0 * sd, 0.03)
    lo, hi = spot * (1 - band), spot * (1 + band)

    if strikes:
        pad = (max(strikes) - min(strikes)) * 0.25 or spot * 0.02
        lo = min(lo, min(strikes) - pad)
        hi = max(hi, max(strikes) + pad)
    lo = max(0.01, lo)

    return [{"s": round(lo + (hi - lo) * i / 60, 2),
             "pl": round(P.payoff_at(norm, lo + (hi - lo) * i / 60), 2)}
            for i in range(61)]


def _scenarios(legs: List[Dict], spot: float) -> List[Dict[str, Any]]:
    """What it is worth at expiry across a spread of finishing prices.

    A payoff curve shows the shape; this shows the arithmetic. People who
    do not read charts read this, and people who do use it to check that
    they read the chart the right way round.
    """
    # payoff_at works on normalised legs -- signed sides and a per-leg
    # multiplier -- which analyse() builds internally. Handing it the raw
    # catalogue legs looks like it works right up until it does not.
    norm = [P._norm(l) for l in legs]
    out = []
    for move in (-0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15):
        price = spot * (1 + move)
        pl = P.payoff_at(norm, price)
        out.append({
            "move": round(move * 100),
            "price": round(price, 2),
            "pl": round(pl, 2),
            "good": pl > 0,
        })
    return out


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
            "scenarios": _scenarios(legs, spot),
            "greeks": a.get("greeks"),
            "days_left": a.get("days_left"),
            "curve": _curve(legs, spot, vol, _years(expiry)),
            "risk": a.get("risk"),
            "expiry": expiry,
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
            "needs": a.get("needs"),
            "best_at": a.get("best_at"),
            "worst_at": a.get("worst_at"),
            "summary": _sentence(a, spot),
            "detected": (a.get("strategy") or {}).get("name"),
        })
    return out
