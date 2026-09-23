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
        # The sign belongs to the operator OR to the value, never to
        # both. Carrying it in each printed the sale of a $200 leg as
        # "- ... = -200.00", and a reader following the row subtracted a
        # negative: a spread costing $300 read as 500 - (-200) = 700.
        # The operator carries it; every value is a magnitude.
        lines.append(line(
            ("" if buying else "-") if i == 0 else ("+" if buying else "-"),
            term(f"{'bought' if buying else 'sold'} {qty:g} {what} at", price),
            term("contracts x shares each" if mult == 100 else "shares",
                 qty * mult, 0),
            gives=cash))
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


def _what(leg: Dict[str, Any]) -> str:
    """How a leg reads in a sentence."""
    if leg.get("kind") == "stock":
        return "shares"
    strike = leg.get("strike")
    return f"${strike:g} {leg.get('kind')}" if strike is not None else str(leg.get("kind"))


def settlement(legs: List[Dict[str, Any]], price: float, cost: float,
               unbounded: bool = False) -> Optional[Dict[str, Any]]:
    """What the position is worth if the share finishes at `price`.

    The best and worst cases are not solved from a formula -- they are
    found by walking the payoff across every strike and reading off the
    highest and lowest points, because the closed form is different for
    each of the twenty-eight structures and a scan is the same for all
    of them.

    So the arithmetic shown here is not the search. It is the settlement
    at the price the search landed on, which is the thing worth seeing:
    every leg exercised or abandoned, added up, less what it cost to
    open. A reader can check that by hand, which is the whole point.

    Takes legs in either shape the engine keeps them in. Internally
    `side` is +1 or -1 and `mult` carries the hundred; on the way out to
    the page `side` becomes "long"/"short" and `mult` is dropped. Both
    forms reach this function, and reading the second one as the first
    multiplied a string by a float -- or, worse, would have silently
    priced an option contract as a single share.
    """
    if unbounded or price is None:
        return None

    lines, settle = [], 0.0
    for leg in legs:
        kind = leg.get("kind")
        if kind == "stock":
            value = price
        elif kind == "call":
            value = max(price - (leg.get("strike") or 0.0), 0.0)
        else:
            value = max((leg.get("strike") or 0.0) - price, 0.0)

        raw = leg.get("side", 1)
        side = (-1 if str(raw).lower().startswith("s") else 1)             if isinstance(raw, str) else (1 if raw > 0 else -1)
        mult = leg.get("mult") or (1 if kind == "stock" else 100)
        shares = abs(float(leg.get("qty") or 0)) * mult
        cash = side * shares * value
        settle += cash

        held = "you own" if side > 0 else "you owe"
        # A leg you owe is always subtracted, even when it settles at
        # nothing -- "+ you owe ... 0.00" reads as a credit. The side
        # decides the operator; the leading row still has to show a
        # minus rather than leaving a short leg looking positive.
        lines.append(line(
            ("" if side > 0 else "-") if not lines
            else ("+" if side > 0 else "-"),
            term(f"{held} {_what(leg)}, worth", value,
                 note=("Worth nothing at this price -- it expires unexercised."
                       if value == 0 and kind != "stock" else "")),
            term("shares", shares, 0),
            gives=abs(cash)))

    # A credit was money in, so closing the position gives it back to you
    # rather than taking it away. Printing "- -300" would be arithmetically
    # right and unreadable.
    paid = cost >= 0
    lines.append(line(
        "-" if paid else "+",
        term("what you paid to open it" if paid else "what you were paid to open it",
             abs(cost)),
        gives=abs(cost)))

    return sum_of(round(settle - cost, 2), lines, note=(
        f"Every leg settled at ${price:,.2f}, then the opening cost taken off. "
        "This is the finishing price the payoff peaks at, not a forecast."))


_GREEK_UNIT = {
    "delta": "for every $1 the share moves",
    "gamma": "of delta, for every $1 the share moves",
    "theta": "a day",
    "vega": "for every 1 point of volatility",
    "rho": "for every 1 point of rates",
}


def greek_total(name: str, legs: List[Dict[str, Any]],
                total: float) -> Optional[Dict[str, Any]]:
    """A position greek as the sum of the legs that make it.

    The per-contract working explains one option. A position is several,
    and the figure the page prints is all of them added up with their
    signs and sizes -- so a hover that showed the leading leg's number
    disagreed with the number it was attached to. On a two-by-two
    spread it read -0.18 under a printed $1.25.
    """
    rows, run = [], 0.0
    for leg in legs:
        per = leg.get(name)
        if per is None:
            continue
        raw = leg.get("side", 1)
        side = (-1 if str(raw).lower().startswith("s") else 1)             if isinstance(raw, str) else (1 if raw > 0 else -1)
        mult = leg.get("mult") or (1 if leg.get("kind") == "stock" else 100)
        units = side * abs(float(leg.get("qty") or 0)) * mult
        cash = units * float(per)
        run += cash
        rows.append(line(
            ("" if cash >= 0 else "-") if not rows
            else ("+" if cash >= 0 else "-"),
            term(f"{'long' if side > 0 else 'short'} "
                 f"{abs(float(leg.get('qty') or 0)):g} {_what(leg)}, each share", per, 4),
            term("shares", abs(units), 0),
            gives=abs(cash)))

    if not rows:
        return None
    return sum_of(round(run, 4), rows, note=(
        f"Each leg's {name} is per share. Multiplied by the shares it "
        f"controls and added up with its sign, that is {_GREEK_UNIT.get(name, '')}."
    ).strip())


# --------------------------------------------------------------------------
# the greeks
# --------------------------------------------------------------------------

def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def greek(name: str, spot: float, strike: float, years: float, vol: float,
          rate: float, is_call: bool, div_yield: float = 0.0) -> Optional[Dict[str, Any]]:
    """One greek, written as the product it is.

    Each of these is a handful of quantities multiplied together, and
    every one of them has a plain name. The two that cannot be written
    as arithmetic on visible numbers are the normal curve's height and
    its area -- the bell curve at d1, and the odds of finishing in the
    money -- so those arrive named, with a sentence, exactly as they do
    in the price itself.

    The arithmetic here is deliberately the same as options.greeks()
    rather than a retelling of it: the suite checks the two agree to
    twelve decimal places, so the working cannot drift into describing
    a calculation the app is not doing.
    """
    if not all(v and v > 0 for v in (spot, strike, years, vol)):
        return None

    q = div_yield or 0.0
    sqrt_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate - q + 0.5 * vol * vol) * years) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    disc = math.exp(-rate * years)
    carry = math.exp(-q * years)
    nd1, nd2 = _norm_cdf(d1), _norm_cdf(d2)
    pdf = _norm_pdf(d1)

    odds_lbl = "odds it finishes in the money"
    odds_note = ("The chance the share ends above the strike, under the same "
                 "lognormal the prices already assume. Not a forecast -- the "
                 "market's own number.")
    bell_lbl = "height of the bell curve at today's price"
    bell_note = ("How densely the possible outcomes are packed right where the "
                 "strike is. It peaks at the money, which is why gamma and vega "
                 "do too.")
    carry_lbl = "dividend discount"
    carry_note = ("Holding the option rather than the share means missing the "
                  "dividends, so every greek is scaled by this.")

    if name == "delta":
        if is_call:
            res = carry * nd1
            lines = [line("", term(carry_lbl, carry, 4, note=carry_note),
                          term(odds_lbl, nd1, 4, note=odds_note))]
        else:
            res = carry * (nd1 - 1.0)
            lines = [line("", term(carry_lbl, carry, 4, note=carry_note),
                          term("odds it finishes in the money, less one",
                               nd1 - 1.0, 4,
                               note="A put gains as the share falls, so its delta "
                                    "is negative: the same odds, counted the "
                                    "other way."))]
        return sum_of(round(res, 6), lines, unit="", note=(
            "Read as shares: a 0.60 delta behaves like 60 shares of exposure, "
            "because one contract covers a hundred."))

    if name == "gamma":
        res = carry * pdf / (spot * vol * sqrt_t)
        return sum_of(round(res, 6), [
            line("", term(carry_lbl, carry, 4, note=carry_note),
                 term(bell_lbl, pdf, 4, note=bell_note)),
            line("/", term("share price", spot),
                 term("volatility", vol, 4),
                 term("square root of the time left", sqrt_t, 4,
                      note="Movement grows with the square root of time, not "
                           "with time, which is why this and not the years.")),
        ], unit="", note=(
            "How much the delta itself moves for a $1 change in the share. "
            "Large near the money and near expiry -- the two places a position "
            "changes character fastest."))

    if name == "vega":
        res = spot * carry * pdf * sqrt_t / 100.0
        return sum_of(round(res, 6), [
            line("", term("share price", spot),
                 term(carry_lbl, carry, 4, note=carry_note),
                 term(bell_lbl, pdf, 4, note=bell_note),
                 term("square root of the time left", sqrt_t, 4)),
            line("/", term("to put it per one point of volatility", 100, 0)),
        ], unit="", note=(
            "What a single percentage point of implied volatility is worth, "
            "per share. Bigger the longer there is to run."))

    if name == "rho":
        if is_call:
            res = strike * years * disc * nd2 / 100.0
            lines = [line("", term("strike", strike),
                          term("years left", years, 4),
                          term("what a dollar at expiry is worth today", disc, 4),
                          term(odds_lbl, nd2, 4, note=odds_note)),
                     line("/", term("to put it per one point of rates", 100, 0))]
        else:
            res = -strike * years * disc * _norm_cdf(-d2) / 100.0
            lines = [line("", term("strike", strike),
                          term("years left", years, 4),
                          term("what a dollar at expiry is worth today", disc, 4),
                          term("odds it finishes below the strike",
                               _norm_cdf(-d2), 4, note=odds_note)),
                     line("/", term("to put it per one point of rates, negative "
                                    "because a put gains when rates fall", -100, 0))]
        return sum_of(round(res, 6), lines, unit="", note=(
            "Negligible on anything short-dated. It is most of why a long-dated "
            "call costs what it does."))

    if name == "theta":
        common = -(spot * carry * pdf * vol) / (2.0 * sqrt_t)
        if is_call:
            second = -rate * strike * disc * nd2
            third = q * spot * carry * nd1
            second_lbl = "interest you are not earning on the strike"
            third_lbl = "dividends you are not receiving"
        else:
            second = rate * strike * disc * _norm_cdf(-d2)
            third = -q * spot * carry * _norm_cdf(-d1)
            second_lbl = "interest earned on the strike you may receive"
            third_lbl = "dividends foregone"
        res = (common + second + third) / 365.0
        return sum_of(round(res, 6), [
            line("", term("the value bleeding out of the option", common, 4,
                          note="The bulk of it: uncertainty is worth money and "
                               "there is a day less of it each day."),),
            line("+", term(second_lbl, second, 4)),
            line("+", term(third_lbl, third, 4)),
            line("/", term("days in a year, to put it per day", 365, 0)),
        ], unit="", note=(
            "Per calendar day, and always against the buyer. It accelerates "
            "into expiry rather than bleeding evenly."))

    return None


# --------------------------------------------------------------------------
# break-even
# --------------------------------------------------------------------------

def breakeven_from(level: float, strike: float, per_share: float,
                   upward: bool) -> Dict[str, Any]:
    """Where the payoff crosses zero, as the strike plus what it cost.

    The engine finds break-evens by scanning the payoff and bisecting,
    because the closed form differs for every structure in the
    taxonomy. But for nearly all of them the ANSWER is the same simple
    sum -- the strike the payoff bends at, plus or minus the net cost
    per share -- and that is a sentence a reader can check.

    Only used where it actually reconstructs the number the scan
    found. Where it does not, the caller says the level was solved for
    rather than pretending to an arithmetic that does not hold.
    """
    return sum_of(round(level, 4), [
        line("", term("the strike the payoff bends at", strike)),
        line("+" if upward else "-",
             term("what the position cost, per share" if per_share >= 0
                  else "what you were paid, per share", abs(per_share))),
    ], per_share=True, note=(
        "Past this level the position is worth more than it cost."
        if upward else
        "Below this level the position is worth more than it cost."))


def breakeven_solved(level: float) -> Dict[str, Any]:
    """An honest non-answer, for the shapes that have no simple sum."""
    return sum_of(round(level, 4), [
        line("", term("found by solving for where the payoff crosses zero", level)),
    ], per_share=True, note=(
        "This structure has no one-line break-even: the payoff bends at more "
        "than one strike, so the level is solved for numerically rather than "
        "added up."))
