"""Every calculated price, shown as the sum it actually is.

A number with no working is something you either take on trust or
ignore. This app computes a great many of them -- what a contract is
worth, what a position cost, where it breaks even -- and each one is
arithmetic on figures that are themselves on the screen.

So each carries its own working: the same sum, written out, with the
variables named in English and their values filled in.

    what the call is worth
      share price 339.75 x  odds you end up owning it 0.5823   =  197.83
    - strike 335.00      x  odds you pay it, discounted 0.5401 =  180.94
    ------------------------------------------------------------------
    = 16.89 a share, x100 = $1,689

The deliberate constraint is that every line is a multiplication or an
addition of two named quantities. Anything that cannot be written that
way -- the normal distribution inside the option formula, say -- is
computed first and enters as a named number with its own sentence, so
the arithmetic on screen stays arithmetic and the modelling is kept
where it belongs, which is out of it.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


def term(label: str, value: Optional[float], dp: int = 2,
         unit: str = "", note: str = "") -> Dict[str, Any]:
    """One named quantity in a sum."""
    return {"label": label, "value": value, "dp": dp, "unit": unit, "note": note}


def line(op: str, *terms: Dict[str, Any], gives: Optional[float] = None,
         dp: int = 2) -> Dict[str, Any]:
    """One row: some terms, multiplied together, added or subtracted."""
    return {"op": op, "terms": list(terms), "gives": gives, "dp": dp}


def sum_of(result: float, lines: List[Dict[str, Any]], unit: str = "$",
           dp: int = 2, note: str = "", per_share: bool = False) -> Dict[str, Any]:
    return {"result": result, "lines": lines, "unit": unit, "dp": dp,
            "note": note, "per_share": per_share}


# --------------------------------------------------------------------------
# the option price itself
# --------------------------------------------------------------------------

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def option_price(spot: float, strike: float, years: float, vol: float,
                 rate: float, is_call: bool, div_yield: float = 0.0,
                 qty: int = 1) -> Dict[str, Any]:
    """Black-Scholes, written as the two-line subtraction it is.

    The formula is not mysterious once the two halves are named. You
    are buying the right to own the share and pay the strike for it,
    and each half is worth its size times the odds it actually
    happens -- with the cash leg discounted, because you pay it later.

    N(d1) and N(d2) are the odds, and they are the one thing here that
    cannot be written as arithmetic on visible numbers. They arrive as
    named quantities with a sentence saying what they are, rather than
    being hidden inside a result.
    """
    if vol <= 0 or years <= 0:
        intrinsic = max((spot - strike) if is_call else (strike - spot), 0.0)
        return sum_of(intrinsic, [
            line("", term("share price" if is_call else "strike",
                          spot if is_call else strike)),
            line("-", term("strike" if is_call else "share price",
                           strike if is_call else spot)),
        ], note="At expiry there is no time left, so the only value is what it "
                "is worth exercised right now.", per_share=True)

    q = div_yield or 0.0
    sqrt_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate - q + 0.5 * vol * vol) * years) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    disc = math.exp(-rate * years)
    carry = math.exp(-q * years)

    if is_call:
        share_odds = carry * _norm_cdf(d1)
        cash_odds = disc * _norm_cdf(d2)
        share_leg = spot * share_odds
        cash_leg = strike * cash_odds
        result = share_leg - cash_leg
        lines = [
            line("", term("share price", spot),
                 term("odds you end up owning it", share_odds, 4,
                      note="The chance it finishes above the strike, weighted by "
                           "how much of the share you effectively hold on the way."),
                 gives=share_leg),
            line("-", term("strike", strike),
                 term("odds you pay it, discounted", cash_odds, 4,
                      note="The chance you exercise, times what a dollar at expiry "
                           "is worth today."),
                 gives=cash_leg),
        ]
    else:
        cash_odds = disc * _norm_cdf(-d2)
        share_odds = carry * _norm_cdf(-d1)
        cash_leg = strike * cash_odds
        share_leg = spot * share_odds
        result = cash_leg - share_leg
        lines = [
            line("", term("strike", strike),
                 term("odds you get paid it, discounted", cash_odds, 4,
                      note="The chance it finishes below the strike, times what a "
                           "dollar at expiry is worth today."),
                 gives=cash_leg),
            line("-", term("share price", spot),
                 term("odds you hand over the share", share_odds, 4,
                      note="The chance you are put the stock, weighted the same way."),
                 gives=share_leg),
        ]

    return sum_of(round(result, 4), lines, per_share=True, note=(
        "One contract is a hundred shares, so the figure above is multiplied "
        "by 100 to get what it costs."))


# --------------------------------------------------------------------------
# the plain ones
# --------------------------------------------------------------------------

def intrinsic(spot: float, strike: float, is_call: bool) -> Dict[str, Any]:
    """What it would be worth if today were expiry."""
    if is_call:
        raw, lines = spot - strike, [
            line("", term("share price", spot)),
            line("-", term("strike", strike)),
        ]
    else:
        raw, lines = strike - spot, [
            line("", term("strike", strike)),
            line("-", term("share price", spot)),
        ]
    if raw < 0:
        lines.append(line("floor", term("but never below zero", 0.0)))
    return sum_of(max(raw, 0.0), lines, per_share=True)


def edge(market: float, fair: float) -> Dict[str, Any]:
    """How far the quoted price sits from the reference value."""
    return sum_of(round(market - fair, 4), [
        line("", term("what it costs", market)),
        line("-", term("what the same option is worth at the reference "
                       "volatility", fair)),
    ], per_share=True, note=(
        "Positive means you are paying more than the reference says it is "
        "worth; negative means less. It is a comparison, not a verdict -- the "
        "reference is one assumption about volatility and the market has "
        "another."))


def breakeven_single(strike: float, premium: float, is_call: bool) -> Dict[str, Any]:
    """Where a bought option starts to pay."""
    if is_call:
        return sum_of(round(strike + premium, 4), [
            line("", term("strike", strike)),
            line("+", term("what you paid, per share", premium)),
        ], per_share=True, note="Above this the option is worth more than it cost.")
    return sum_of(round(strike - premium, 4), [
        line("", term("strike", strike)),
        line("-", term("what you paid, per share", premium)),
    ], per_share=True, note="Below this the option is worth more than it cost.")


def net_cost(legs: List[Dict[str, Any]]) -> Dict[str, Any]:
    """What the whole position cost, leg by leg."""
    lines, total = [], 0.0
    for i, l in enumerate(legs):
        mult = 1 if l.get("kind") == "stock" else 100
        qty = abs(float(l.get("qty") or 0))
        price = float(l.get("entry") or 0)
        cash = qty * mult * price
        buying = str(l.get("side", "long")).lower().startswith("l")
        total += cash if buying else -cash
        what = ("shares" if l.get("kind") == "stock"
                else f"{l.get('strike')} {l.get('kind')}")
        lines.append(line(
            "" if i == 0 else ("+" if buying else "-"),
            term(f"{'bought' if buying else 'sold'} {qty:g} {what} at", price),
            term("contracts x shares each" if mult == 100 else "shares",
                 qty * mult, 0),
            gives=cash if buying else -cash))
    return sum_of(round(total, 2), lines, note=(
        "Positive is money out of your account, negative is money in."))


def profit_now(value_now: float, cost: float) -> Dict[str, Any]:
    """Where the position stands."""
    return sum_of(round(value_now - cost, 2), [
        line("", term("what it is worth now", value_now)),
        line("-", term("what it cost to put on", cost)),
    ], note="What it is worth now is every leg re-priced at today's market.")


def percent_of_risk(profit: float, risk: float) -> Dict[str, Any]:
    return sum_of(round(profit / risk * 100, 2) if risk else 0.0, [
        line("", term("profit so far", profit)),
        line("/", term("the most it could lose", risk)),
        line("x", term("to make it a percentage", 100, 0)),
    ], unit="%", note=(
        "Measured against what is at risk rather than against what it cost, "
        "because for anything sold those are two different numbers."))
