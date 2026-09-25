"""A trade you have already put on.

The rest of the app helps you decide. This is for after you have decided:
you hold something, and the question is no longer "is this a good idea" but
"where am I, what is working against me, and when do I get out".

Three jobs.

RECOGNISE IT. You enter legs, not a strategy name. A long call at 250 and a
short call at 270 in the same expiry is a bull call spread, and it should
say so without being told, because the name carries the whole risk profile
with it. The reference workbooks cannot do this -- Exercise 3.3 has a
checkbox that asks the user "Is this Option Strategy a Collar?" -- and the
taxonomy they teach across Sections 3.1 to 3.5 is exactly the table needed
to do it automatically.

PRICE IT. Net debit or credit, live value, profit and loss in dollars and
as a share of what is at risk, net greeks in position terms rather than
per-contract, breakevens, and the most that can be made or lost.

SAY SOMETHING USEFUL. Not a dashboard of numbers -- what they mean for
staying in. How much the position bleeds per day, what share of the
available profit has already been taken, whether the move you needed has
happened, and what is between here and expiry.

Everything is per-share internally and multiplied by 100 at the edges,
which is the mistake the workbooks warn about on nearly every tab.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sources import options as O

MULT = 100          # shares per option contract


# --------------------------------------------------------------- the legs
def _norm(leg: Dict[str, Any]) -> Dict[str, Any]:
    """One leg, cleaned. Quantity is always positive; `side` carries sign."""
    kind = str(leg.get("kind", "call")).lower()
    if kind not in ("call", "put", "stock"):
        kind = "call"
    side = -1 if str(leg.get("side", "long")).lower().startswith("s") else 1
    qty = abs(float(leg.get("qty") or 0))
    return {
        "kind": kind,
        "side": side,
        "qty": qty,
        "strike": float(leg["strike"]) if leg.get("strike") not in (None, "") else None,
        "expiry": (leg.get("expiry") or "").strip() or None,
        "entry": float(leg.get("entry") or 0),
        # Stock is one share per unit; an option controls a hundred.
        "mult": 1 if kind == "stock" else MULT,
    }


def _years(expiry: Optional[str], now: Optional[datetime] = None) -> Optional[float]:
    if not expiry:
        return None
    now = now or datetime.now(timezone.utc)
    try:
        end = datetime.strptime(expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    td = O.trading_days(now, end)
    return max(td / 252.0, 1 / 252.0) if td > 0 else 0.0


# ------------------------------------------------------------- what is it
def identify(legs: List[Dict[str, Any]], spot: Optional[float] = None) -> Dict[str, Any]:
    """Name the strategy from its legs.

    The taxonomy is the one the reference course teaches across Sections 3.1
    to 3.5. Matching runs from most specific to least so that, for example,
    a collar is not reported as a covered call with something attached.
    """
    opts = [l for l in legs if l["kind"] != "stock"]
    stock = [l for l in legs if l["kind"] == "stock"]
    n = len(opts)
    calls = [l for l in opts if l["kind"] == "call"]
    puts = [l for l in opts if l["kind"] == "put"]
    expiries = {l["expiry"] for l in opts}
    one_expiry = len(expiries) == 1
    net_shares = sum(l["side"] * l["qty"] for l in stock)

    def S(l): return l["strike"]
    longs = [l for l in opts if l["side"] > 0]
    shorts = [l for l in opts if l["side"] < 0]

    # ---- stock plus options
    if stock and n == 0:
        return _named("Long stock" if net_shares > 0 else "Short stock", "directional")
    if stock and n == 1:
        o = opts[0]
        if net_shares > 0 and o["kind"] == "call" and o["side"] < 0:
            return _named("Covered call", "income",
                          "You own the shares and have sold someone the right to buy them.")
        if net_shares > 0 and o["kind"] == "put" and o["side"] > 0:
            return _named("Married put", "protective",
                          "Shares plus a floor under them. The put is the insurance premium.")
        if net_shares < 0 and o["kind"] == "call" and o["side"] > 0:
            return _named("Protective call", "protective",
                          "Short shares with a ceiling on how far they can run against you.")
    if stock and n == 2 and len(calls) == 1 and len(puts) == 1:
        if net_shares > 0 and calls[0]["side"] < 0 and puts[0]["side"] > 0:
            return _named("Collar", "protective",
                          "Shares, a floor bought below and a ceiling sold above to pay for it.")

    # ---- single option
    if n == 1 and not stock:
        o = opts[0]
        yrs = _years(o["expiry"]) or 0
        leaps = yrs > 1.0
        if o["kind"] == "call":
            if o["side"] > 0:
                return _named("LEAPS call" if leaps else "Long call", "directional",
                              "Pure upside, and the clock is against you.")
            return _named("Naked short call", "income",
                          "Premium now, theoretically unlimited loss above the strike.")
        if o["side"] > 0:
            return _named("LEAPS put" if leaps else "Long put", "directional",
                          "Pure downside, and the clock is against you.")
        return _named("Cash-secured put", "income",
                      "Paid to promise to buy the shares at the strike.")

    # ---- two options
    if n == 2 and not stock:
        a, b = sorted(opts, key=lambda l: (S(l) or 0))
        same_strike = S(a) == S(b)
        if len(calls) == 2 and one_expiry:
            if a["side"] > 0 and b["side"] < 0:
                return _named("Bull call spread", "directional",
                              "Upside to the short strike, paid for up front.")
            if a["side"] < 0 and b["side"] > 0:
                return _named("Bear call spread", "income",
                              "Paid to say it stays below the lower strike.")
        if len(puts) == 2 and one_expiry:
            if b["side"] > 0 and a["side"] < 0:
                return _named("Bear put spread", "directional",
                              "Downside to the short strike, paid for up front.")
            if b["side"] < 0 and a["side"] > 0:
                return _named("Bull put spread", "income",
                              "Paid to say it stays above the higher strike.")
        if len(calls) == 1 and len(puts) == 1 and one_expiry:
            c, p = calls[0], puts[0]
            if same_strike:
                if c["side"] > 0 and p["side"] > 0:
                    return _named("Long straddle", "volatility",
                                  "Bought movement in either direction. Needs a big one.")
                if c["side"] < 0 and p["side"] < 0:
                    return _named("Short straddle", "volatility",
                                  "Sold movement. Paid to be right that nothing happens.")
                if c["side"] > 0 and p["side"] < 0:
                    return _named("Synthetic long stock", "directional")
                if c["side"] < 0 and p["side"] > 0:
                    return _named("Synthetic short stock", "directional")
            else:
                if c["side"] > 0 and p["side"] > 0:
                    return _named("Long strangle", "volatility",
                                  "Movement again, cheaper than a straddle and needs more of it.")
                if c["side"] < 0 and p["side"] < 0:
                    return _named("Short strangle", "volatility",
                                  "Paid for a range. Losses open on both ends.")
        if not one_expiry and len(expiries) == 2 and (len(calls) == 2 or len(puts) == 2):
            near = min(opts, key=lambda l: l["expiry"] or "")
            far = max(opts, key=lambda l: l["expiry"] or "")
            if same_strike and near["side"] < 0 and far["side"] > 0:
                return _named("Calendar spread", "volatility",
                              "Selling the near month against the far one. Time is the trade.")
            if near["side"] < 0 and far["side"] > 0:
                # A fig leaf is a long-dated call DEEP in the money
                # standing in for the shares, with a near call sold
                # against it. Testing only that the long strike is the
                # lower of the two caught every ordinary bullish call
                # diagonal as well, which is a different trade with a
                # different risk: the fig leaf behaves like stock, the
                # diagonal does not.
                deep = (spot and S(far) and S(far) <= spot * 0.90)
                dated = (_years(far["expiry"]) or 0) > 0.75
                if len(calls) == 2 and deep and dated:
                    return _named("Fig leaf", "income",
                                  "A deep long-dated call standing in for the shares, "
                                  "with a near call sold against it.")
                return _named("Diagonal spread", "volatility")

    # ---- three and four legs
    if n == 3 and len({l["kind"] for l in opts}) == 1 and one_expiry:
        s = sorted(opts, key=lambda l: S(l) or 0)
        qtys = [l["side"] * l["qty"] for l in s]
        if qtys[0] > 0 and qtys[1] < 0 and qtys[2] > 0 and abs(qtys[1]) == qtys[0] + qtys[2]:
            return _named(f"Long butterfly with {s[0]['kind']}s", "volatility",
                          "Pays most if it finishes on the middle strike.")
        if qtys[0] < 0 and qtys[1] > 0 and qtys[2] < 0:
            return _named(f"Short butterfly with {s[0]['kind']}s", "volatility")
    if n == 4 and one_expiry:
        s = sorted(opts, key=lambda l: S(l) or 0)
        kinds = [l["kind"] for l in s]
        sides = [l["side"] for l in s]
        if kinds == ["put", "put", "call", "call"]:
            strikes = [S(l) for l in s]
            # The butterfly is the special case and has to be tested
            # first: its two short strikes sit on top of each other,
            # and a condor's do not. Checked the other way round, every
            # iron butterfly came back as a condor -- which reads as a
            # range trade when it is really a bet on one price.
            pinched = strikes[1] == strikes[2]
            if sides == [1, -1, -1, 1]:
                if pinched:
                    return _named("Iron butterfly (sold)", "income",
                                  "Paid most if it finishes on the middle strike, "
                                  "with both tails bought back.")
                return _named("Iron condor (sold)", "income",
                              "Paid for a range, with both tails bought back.")
            if sides == [-1, 1, 1, -1]:
                if pinched:
                    return _named("Iron butterfly (bought)", "volatility",
                                  "Pays if it finishes away from the middle strike.")
                return _named("Iron condor (bought)", "volatility")
        if len(set(kinds)) == 1:
            if sides == [1, -1, -1, 1]:
                return _named(f"Long condor with {kinds[0]}s", "volatility")

    return _named(f"{n}-leg position" if n else "Stock position", "custom")


def _named(name: str, family: str, note: str = "") -> Dict[str, Any]:
    return {"name": name, "family": family, "note": note}


# --------------------------------------------------------------- the maths
def payoff_at(legs: List[Dict[str, Any]], price: float) -> float:
    """Profit in dollars if the underlying is `price` at expiry.

    Intrinsic value only -- at expiry there is nothing else left. Entry cost
    is subtracted for what was bought and added for what was sold, which is
    the sign convention `side` already carries.
    """
    total = 0.0
    for l in legs:
        if l["kind"] == "stock":
            value = price
        elif l["kind"] == "call":
            value = max(price - l["strike"], 0.0)
        else:
            value = max(l["strike"] - price, 0.0)
        total += l["side"] * l["qty"] * l["mult"] * (value - l["entry"])
    return total


def net_cost(legs: List[Dict[str, Any]]) -> float:
    """Positive means a debit paid, negative means a credit taken in."""
    return sum(l["side"] * l["qty"] * l["mult"] * l["entry"] for l in legs)


def value_at(legs: List[Dict[str, Any]], price: float, horizon: float,
             vol: float, rate: float, div_yield: float = 0.0) -> float:
    """Profit at `price`, `horizon` years from now, with the survivors valued.

    payoff_at assumes every leg expires, which is true of most positions
    and false of exactly the ones where it matters. A calendar spread is
    two options on the same strike: let them both expire and they cancel
    to the penny, so the app reported a calendar's MAXIMUM PROFIT as a
    $300 loss and said it could never make money. It makes money by the
    near leg expiring worthless while the far leg is still alive.

    So anything still running at the horizon is valued with
    Black-Scholes on its remaining life instead of being collapsed to
    intrinsic.
    """
    total = 0.0
    for l in legs:
        if l["kind"] == "stock":
            value = price
        else:
            left = (_years(l["expiry"]) or 0.0) - horizon
            if left <= 1e-9:
                value = (max(price - l["strike"], 0.0) if l["kind"] == "call"
                         else max(l["strike"] - price, 0.0))
            elif price <= 0:
                # Zero is absorbing in the model this is all built on: a
                # share at nothing stays at nothing, so the call is worth
                # nothing and the put is worth its strike, discounted.
                # Black-Scholes cannot be asked -- it takes log(price).
                value = (0.0 if l["kind"] == "call"
                         else l["strike"] * math.exp(-rate * left))
            else:
                value = O.bs_price(price, l["strike"], left, vol, rate,
                                   l["kind"] == "call", div_yield)
        total += l["side"] * l["qty"] * l["mult"] * (value - l["entry"])
    return total


def _payoff_fn(legs: List[Dict[str, Any]], vol: float, rate: float,
               div_yield: float):
    """The right profit function for this position, and when it applies.

    One expiry: the plain intrinsic payoff. More than one: valued at the
    NEAREST expiry, because that is the first date the position changes
    character, and it is the date a calendar is actually judged on.
    """
    expiries = sorted({l["expiry"] for l in legs if l["expiry"]})
    if len(expiries) <= 1:
        return (lambda price: payoff_at(legs, price)), None

    horizon = _years(expiries[0]) or 0.0
    return ((lambda price: value_at(legs, price, horizon, vol, rate, div_yield)),
            expiries[0])


def _breakevens(pay, lo: float, hi: float, steps: int = 4000) -> List[float]:
    """Where the payoff crosses zero, found by scanning and bisecting.

    Solved numerically rather than per strategy: the closed forms
    differ for every structure in the taxonomy, and a sign change is a
    sign change whatever the shape above it.

    Zero is treated as a BAND half a cent wide, not as a point.

    A payoff can be mathematically flat at zero over a whole stretch --
    a butterfly that happened to cost nothing to open is exactly that
    outside its wings -- and in floating point such a stretch is not
    zero, it is plus or minus a fraction of a cent, flickering sign at
    random. Testing `y < 0` there found a crossing at nearly every grid
    point: one structure reported three and a half THOUSAND
    break-evens, every one of which would have been printed as a level
    to watch.

    So the payoff is read as one of three states -- below, at, or above
    zero -- and a break-even is a move between below and above. Where
    the payoff merely touches or rides along zero, the EDGES of that
    stretch are the boundaries, because that is what is true: there is
    a region where you neither make nor lose, and it begins and ends
    somewhere.
    """
    # Half a cent. Below this nothing is a real gain or loss on a
    # position quoted in dollars, and anything smaller is arithmetic
    # noise rather than money.
    eps = 0.005

    def state(y: float) -> int:
        return 0 if abs(y) < eps else (1 if y > 0 else -1)

    xs = [lo + (hi - lo) * i / steps for i in range(steps + 1)]
    st = [state(pay(x)) for x in xs]

    out: List[float] = []
    for i in range(1, len(xs)):
        a, b = st[i - 1], st[i]
        if a == b:
            continue
        if a != 0 and b != 0:
            # A clean sign change: solve for where it happens.
            x0, x1 = xs[i - 1], xs[i]
            for _ in range(60):
                m = 0.5 * (x0 + x1)
                if state(pay(x0)) != state(pay(m)):
                    x1 = m
                else:
                    x0 = m
            out.append(round(0.5 * (x0 + x1), 2))
        else:
            # Entering or leaving the zero band. The grid point on the
            # zero side is the edge of the region.
            out.append(round(xs[i] if b == 0 else xs[i - 1], 2))

    # Two edges a hair apart are one edge.
    tidy: List[float] = []
    for v in out:
        if not tidy or v - tidy[-1] > max((hi - lo) / steps * 1.5, 0.02):
            tidy.append(v)
    return tidy


def _extremes(pay, strikes: List[float], spot: float) -> Dict[str, Any]:
    """Max profit and max loss, and whether either is unbounded.

    Checked by walking the payoff far past every strike in both directions
    and looking at the slope at the ends: a payoff still rising at four
    times spot is not going to turn around.
    """
    strikes = list(strikes) or [spot]
    lo, hi = 0.0, max(max(strikes), spot) * 4
    # The grid must contain every strike and zero exactly. A payoff is
    # piecewise linear with a corner at each strike, so its maximum and
    # minimum can only occur at a corner or at an end -- and a linspace
    # that steps straight past 100.00 reported a long straddle's worst case
    # as -1099.25 instead of the -1100 it actually is.
    xs = sorted(set([lo, hi, spot] + strikes
                    + [lo + (hi - lo) * i / 2000 for i in range(2001)]))
    ys = [pay(x) for x in xs]

    # Both questions are decided at the TOP end, because a share price
    # cannot go below zero: the payoff at S=0 is always a finite number, so
    # the downside is always bounded no matter what the position is. Only
    # what happens as price runs away upward can be unlimited -- a short
    # call loses forever, a long call gains forever.
    #
    # Reading the low end instead reported "no maximum loss" for a long
    # straddle, whose loss is exactly the premium paid, because the payoff
    # is of course falling as price rises up off zero.
    slope_hi = ys[-1] - ys[-2]
    profit_unbounded = slope_hi > 1e-6
    loss_unbounded = slope_hi < -1e-6

    return {
        "max_profit": None if profit_unbounded else round(max(ys), 2),
        "max_loss": None if loss_unbounded else round(min(ys), 2),
        "max_profit_unbounded": profit_unbounded,
        "max_loss_unbounded": loss_unbounded,
        "at_zero": round(pay(0.0), 2),
    }


def analyse(raw_legs: List[Dict[str, Any]], spot: float, vol: float,
            rate: float, div_yield: float = 0.0,
            chain_marks: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Everything about a position that is already on."""
    legs = [_norm(l) for l in raw_legs if l.get("kind")]
    legs = [l for l in legs if l["qty"] > 0]
    if not legs or not spot:
        return {"ok": False, "reason": "no legs"}

    strategy = identify(legs, spot)
    cost = net_cost(legs)

    out_legs: List[Dict[str, Any]] = []
    greeks = {"delta": 0.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
    value_now = 0.0

    for i, l in enumerate(legs):
        signed_units = l["side"] * l["qty"] * l["mult"]
        if l["kind"] == "stock":
            mark = spot
            g = {"delta": 1.0, "gamma": 0.0, "theta": 0.0, "vega": 0.0, "rho": 0.0}
            yrs = None
        else:
            yrs = _years(l["expiry"])
            key = f"{l['kind']}:{l['strike']}:{l['expiry']}"
            mark = (chain_marks or {}).get(key)
            if mark is None and yrs:
                mark = O.bs_price(spot, l["strike"], yrs, vol, rate,
                                  l["kind"] == "call", div_yield)
            mark = mark or 0.0
            g = O.greeks(spot, l["strike"], yrs or 0, vol, rate,
                         l["kind"] == "call", div_yield) if yrs else {
                k: 0.0 for k in greeks}

        value_now += signed_units * mark
        for k in greeks:
            if g.get(k) is not None:
                greeks[k] += signed_units * g[k]

        out_legs.append({
            "i": i, "kind": l["kind"],
            "side": "long" if l["side"] > 0 else "short",
            "qty": l["qty"], "strike": l["strike"], "expiry": l["expiry"],
            "entry": round(l["entry"], 4), "mark": round(mark, 4),
            "value": round(signed_units * mark, 2),
            "pl": round(signed_units * (mark - l["entry"]), 2),
            "days": O.trading_days(datetime.now(timezone.utc),
                                   datetime.strptime(l["expiry"], "%Y-%m-%d")
                                   .replace(tzinfo=timezone.utc)) if l["expiry"] else None,
            **{k: (round(g[k], 6) if g.get(k) is not None else None) for k in greeks},
        })

    pl = value_now - cost
    strikes = [l["strike"] for l in legs if l["strike"]] or [spot]

    # One payoff function for the whole analysis, so the curve, the
    # break-evens, the extremes and the odds all describe the same thing.
    pay, at_expiry = _payoff_fn(legs, vol, rate, div_yield)

    ext = _extremes(pay, strikes, spot)
    where = _where_extreme(pay, strikes, spot)
    lo = max(0.01, min(min(strikes), spot) * 0.4)
    hi = max(max(strikes), spot) * 1.8
    bes = _breakevens(pay, lo, hi)

    # What is actually at risk. For a debit that is what you paid; for a
    # credit spread it is the width less the credit, which is what max_loss
    # already found. Percentages against the wrong denominator are the most
    # common way an options P&L is misread.
    risk = abs(ext["max_loss"]) if ext["max_loss"] is not None and ext["max_loss"] < 0 \
        else (abs(cost) if cost > 0 else None)

    curve = []
    for i in range(61):
        x = lo + (hi - lo) * i / 60
        curve.append({"s": round(x, 2), "pl": round(pay(x), 2)})

    pop, pop_parts = _chance_of_profit(pay, legs, spot, vol, rate, div_yield, bes)

    nearest = min((l for l in legs if l["expiry"]), key=lambda l: l["expiry"], default=None)
    days_left = None
    if nearest:
        days_left = O.trading_days(
            datetime.now(timezone.utc),
            datetime.strptime(nearest["expiry"], "%Y-%m-%d").replace(tzinfo=timezone.utc))

    return {
        "ok": True,
        "strategy": strategy,
        "legs": out_legs,
        "spot": round(spot, 4),
        "net_cost": round(cost, 2),
        "debit": cost > 0,
        "value_now": round(value_now, 2),
        "pl": round(pl, 2),
        "pl_pct": round(pl / risk * 100, 1) if risk else None,
        "risk": round(risk, 2) if risk else None,
        "greeks": {k: round(v, 4) for k, v in greeks.items()},
        "share_equivalent": round(greeks["delta"], 1),
        "breakevens": bes,
        "breakeven_working": _breakeven_working(bes, legs, cost),
        # The page has always ASKED for these -- the chips call
        # calc(..., d.working?.net_cost) and friends -- but nothing ever
        # built the dict, so every one of those hovers resolved to
        # undefined and showed nothing. The numbers the reader most
        # wants to check were the ones with no arithmetic behind them.
        "working": _position_working(legs, cost, value_now, pl, risk, ext, where),
        "greek_working": _greek_working(legs, spot, vol, rate, div_yield),
        "chance": pop,
        "chance_working": _chance_working(pop_parts, days_left),
        "needs": _needs(pay, spot, bes, curve),
        "hope": _hope(_needs(pay, spot, bes, curve), where, bes, spot, ext),
        "valued_at": at_expiry,
        **where,
        "days_left": days_left,
        "curve": curve,
        **ext,
    }


# ------------------------------------------------------------- the support
def guidance(a: Dict[str, Any], vol: float, rate: float,
             div_yield: float = 0.0, earnings: Optional[str] = None
             ) -> List[Dict[str, str]]:
    """What the numbers mean for staying in, in the order they matter.

    Deliberately not a verdict. Nothing here says sell -- it says what has
    already happened, what it is costing to wait, and what still has to
    occur for the position to work, which is the set of facts an exit
    decision is actually made from.
    """
    out: List[Dict[str, Any]] = []

    # Each step leads with a figure in large type, and those figures were
    # the only large numbers on the page a reader could not check. The
    # sums already exist -- analyse() built them for the chips above --
    # so the step carries the same object rather than a second copy of
    # the arithmetic that could drift from it.
    def add(h, b, f="", w=None, w_label=""):
        """One step.

        `w_label` is set when the sum does NOT come to the figure above
        it. "Where half the profit is" prints a PRICE and its sum comes
        to the profit at that price -- attaching that to the figure's
        hover says $340.75 is derived from a sum ending in 350.00, which
        it is not. Labelled instead, it reads as what it is: the proof
        that the price named is the right one.
        """
        out.append({"head": h, "body": b, "figure": f,
                    "working": w, "working_label": w_label})

    # The same payoff the analysis was built from, rebuilt from the legs
    # on their way out. Needed because the drawn curve is far too coarse
    # to locate a price inside a narrow spread.
    try:
        _pay, _ = _payoff_fn([_norm(l) for l in a["legs"]], vol, rate, div_yield)
    except Exception:                                      # noqa: BLE001
        _pay = None

    W = a.get("working") or {}
    GW = a.get("greek_working") or {}
    BW = a.get("breakeven_working") or []

    spot, pl = a["spot"], a["pl"]
    risk, mp = a.get("risk"), a.get("max_profit")

    # 1 -- where you are
    share = f" That is {abs(pl) / risk * 100:.0f}% of the {_usd(risk)} at risk." if risk else ""
    captured = ""
    if mp and mp > 0 and pl > 0:
        captured = (f" You are holding {pl / mp * 100:.0f}% of the {_usd(mp)} this trade "
                    f"can ever make.")
    add("Where you are",
        f"The position is {'up' if pl >= 0 else 'down'} <b>{_usd(abs(pl))}</b>."
        f"{share}{captured}", f"{'+' if pl >= 0 else '-'}{_usd(abs(pl))}",
        W.get("profit"))

    # 2 -- the clock
    theta = a["greeks"]["theta"]
    days = a.get("days_left")
    if theta:
        daily = abs(theta)
        run = f" Held to expiry that is about {_usd(daily * days)} more." if days else ""
        add("What waiting costs",
            f"Time alone {'takes' if theta < 0 else 'adds'} <b>{_usd(daily)}</b> a "
            f"{'day' if theta < 0 else 'day in your favour'}.{run} "
            + ("Decay accelerates into expiry rather than running evenly."
               if theta < 0 else "Decay is working for you, which is the whole trade."),
            f"{_usd(theta)}/day",
            # The position's theta, not the leading leg's. These are
            # different numbers and the page prints the first.
            __import__("working").greek_total("theta", a["legs"], theta))

    # 3 -- what still has to happen
    bes = a.get("breakevens") or []
    if bes:
        nearest = min(bes, key=lambda b: abs(b - spot))
        move = (nearest / spot - 1) * 100
        inside = _profitable_now(a, spot)
        add("What has to happen",
            f"Break-even sits at <b>${nearest:,.2f}</b>, {abs(move):.1f}% "
            f"{'above' if move > 0 else 'below'} the {spot:,.2f} it trades at now. "
            + ("You are already past it." if inside
               else "The move has not happened yet.")
            + (f" The other side is ${max(bes):,.2f}." if len(bes) > 1 else ""),
            f"${nearest:,.2f}",
            BW[bes.index(nearest)] if bes.index(nearest) < len(BW) else None)

    # 4 -- the odds, on the model's terms
    if days and vol:
        yrs = max(days / 252.0, 1 / 252.0)
        pr = O.probabilities(spot, yrs, vol, rate, div_yield)
        if pr.get("available") and bes:
            band = pr["one_sigma"]
            add("Where the model says it lands",
                f"Two outcomes in three fall between <b>${band['low']:,.2f}</b> and "
                f"<b>${band['high']:,.2f}</b> by expiry, at {vol * 100:.0f}% volatility. "
                + ("Both break-evens sit inside that range."
                   if all(band["low"] < b < band["high"] for b in bes)
                   else "At least one break-even is outside it, which is the "
                        "part of the trade that needs an unusual move."),
                f"{pr['p_above_spot']:.0f}%")

    # 5 -- short legs that can be taken away from you
    itm_shorts = [l for l in a["legs"]
                  if l["side"] == "short" and l["kind"] != "stock" and l["strike"]
                  and ((l["kind"] == "call" and spot > l["strike"])
                       or (l["kind"] == "put" and spot < l["strike"]))]
    if itm_shorts:
        # A strike is a name. Rounded to whole dollars the 337.5 call
        # reads as "$338", which is a different contract that also exists.
        names = ", ".join(
            f"${l['strike']:,.2f}".rstrip("0").rstrip(".") + f" {l['kind']}"
            for l in itm_shorts)
        add("Assignment is live",
            f"Your short {names} {'is' if len(itm_shorts) == 1 else 'are'} in the money. "
            f"American options can be exercised on any day, and the risk rises as "
            f"expiry approaches and as the extrinsic value left in them goes to nothing.",
            f"{len(itm_shorts)} ITM")

    # 6 -- the event the position has to sit through
    if earnings and days:
        try:
            ed = datetime.strptime(earnings, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            to_earn = O.trading_days(datetime.now(timezone.utc), ed)
            if 0 < to_earn <= days:
                long_vega = a["greeks"]["vega"] > 0
                add("Earnings land before expiry",
                    f"Results are due {earnings}, {to_earn} trading days out and inside "
                    f"the life of this position. "
                    + ("You are long volatility, so the run-up helps and the crush "
                       "afterwards hurts."
                       if long_vega else
                       "You are short volatility: the run-up works against you and the "
                       "crush afterwards is where the position pays."),
                    f"{to_earn}d")
        except ValueError:
            pass

    # 7 -- the exits, as prices rather than advice
    if mp and mp > 0 and risk:
        half = _price_for_pl(a, mp * 0.5, _pay)
        if half:
            # The reason to take half differs by structure, so say the right
            # one: a credit trade is closed early to stop renting out risk
            # for a shrinking rent, a debit trade because the rest of the
            # move is the part you are least likely to get.
            why = ("Closing a credit trade around there is common: the rest of the "
                   "premium comes in slowly while the risk stays fully open."
                   if not a["debit"] else
                   "The second half of a debit trade's profit is the part that needs "
                   "the move to keep going, which is the part you are least likely "
                   "to be paid for.")
            import working as W                        # noqa: PLC0415
            add("Where half the profit is",
                f"Half of the maximum ({_usd(mp * 0.5)}) is reached around "
                f"<b>${half:,.2f}</b>. {why}", f"${half:,.2f}",
                # The price is found by walking the payoff, same as the
                # extremes are. Showing the settlement AT it is what makes
                # "half the maximum" something a reader can verify.
                W.settlement(a["legs"], half, a["net_cost"]),
                f"what the position is worth at ${half:,.2f}")
    return out


def _usd(v: Optional[float]) -> str:
    if v is None:
        return "--"
    return f"${abs(v):,.0f}" if abs(v) >= 100 else f"${abs(v):,.2f}"


def _profitable_now(a: Dict[str, Any], spot: float) -> bool:
    for p in a["curve"]:
        if abs(p["s"] - spot) <= (a["curve"][1]["s"] - a["curve"][0]["s"]):
            return p["pl"] > 0
    return False


def _price_for_pl(a: Dict[str, Any], target: float, pay=None) -> Optional[float]:
    """The price nearest today's at which the payoff reaches `target`.

    Solved against the payoff itself, not against the drawn curve.

    The curve is sixty-one points for a chart, spread over a range that
    runs from forty percent of spot to nearly twice it -- about eight
    dollars a step on a $337 share. A five-dollar-wide spread does all
    of its work inside ONE of those steps, so reading the answer off the
    curve skipped the entire ramp and returned the first grid point past
    it, which is already at the maximum.

    That put "half of the maximum is reached around $343.54" on a
    position whose half-way price is $340.75 -- and $343.54 is where it
    makes the whole thing, not half. Every narrow spread was wrong the
    same way, and the narrower the spread the worse it got.
    """
    if pay is None:
        # No payoff to hand: fall back to the curve, which is coarse but
        # is at least the same shape.
        best, dist = None, None
        for p in a["curve"]:
            if p["pl"] >= target:
                d = abs(p["s"] - a["spot"])
                if dist is None or d < dist:
                    best, dist = p["s"], d
        return best

    curve = a["curve"]
    lo, hi = curve[0]["s"], curve[-1]["s"]
    spot = a["spot"]

    # Fine enough that no strike-to-strike stretch is skipped, then
    # bisected so the answer is exact rather than merely close.
    steps = 4000
    prev_x, prev_y = lo, pay(lo)
    best, dist = None, None
    for i in range(1, steps + 1):
        x = lo + (hi - lo) * i / steps
        y = pay(x)
        if (prev_y < target) != (y < target):
            aa, bb = prev_x, x
            for _ in range(60):
                m = 0.5 * (aa + bb)
                if (pay(aa) < target) != (pay(m) < target):
                    bb = m
                else:
                    aa = m
            cross = 0.5 * (aa + bb)
            d = abs(cross - spot)
            if dist is None or d < dist:
                best, dist = round(cross, 2), d
        prev_x, prev_y = x, y

    if best is not None:
        return best
    # No crossing: the target is already met across the whole range, or
    # never met anywhere in it.
    return next((p["s"] for p in curve if p["pl"] >= target), None)


# --------------------------------------------------------- in plain english
def describe(a: Dict[str, Any], name: Optional[str] = None,
             symbol: Optional[str] = None) -> Dict[str, str]:
    """The position as two paragraphs a person would actually say.

    The grid of figures above this is faster to scan once you know what the
    labels mean, and useless before then. "Per point of vol: +$2.29" is not
    a sentence anybody has said out loud. So the same numbers are written
    out once, in order, with the units attached -- and then the grid is
    just the short version of something you have already read.
    """
    # "Apple Inc." already ends in a full stop, and appending one gave
    # "Apple Inc..". Repeating the legal name in every clause also reads
    # like a contract, so the sentences after the first use the ticker.
    who = (name or symbol or "the stock").rstrip(".")
    short = symbol or who
    s = a["strategy"]
    pl, cost = a["pl"], a["net_cost"]
    risk, mp, ml = a.get("risk"), a.get("max_profit"), a.get("max_loss")
    bes = a.get("breakevens") or []
    days = a.get("days_left")
    g = a["greeks"]

    # ---- what you hold, what it cost, where it stands
    name = s["name"].lower()
    article = "an" if name[:1] in "aeiou" else "a"
    bits: List[str] = [f"You are in {article} <b>{name}</b> on {who}."]

    if cost > 0:
        bits.append(f"It cost you <b>{_usd(cost)}</b> to put on and is worth "
                    f"<b>{_usd(a['value_now'])}</b> now,")
    else:
        bits.append(f"You were paid <b>{_usd(abs(cost))}</b> to put it on and it "
                    f"would cost <b>{_usd(abs(a['value_now']))}</b> to close,")

    if abs(pl) < 1:
        bits.append("so you are roughly level.")
    else:
        share = abs(pl) / risk * 100 if risk else None
        # Below one percent, the percentage says less than the dollars do.
        of_risk = (f" &mdash; about {share:.0f}% of what you have at risk"
                   if share and share >= 1 else
                   " &mdash; a fraction of what you have at risk" if share else "")
        bits.append(f"so you are <b>{'up' if pl > 0 else 'down'} {_usd(abs(pl))}</b>{of_risk}.")

    # ---- what has to happen for it to work
    if bes:
        if len(bes) == 1:
            side = "above" if _rises(a) else "below"
            bits.append(f"It starts making money {side} <b>${bes[0]:,.2f}</b>.")
        else:
            bits.append(f"It makes money {'outside' if _outside(a) else 'between'} "
                        f"<b>${min(bes):,.2f}</b> and <b>${max(bes):,.2f}</b>.")

    if mp is not None and mp > 0:
        bits.append(f"The most it can make is <b>{_usd(mp)}</b>.")
    elif a.get("max_profit_unbounded"):
        bits.append("There is no cap on what it can make.")

    if ml is not None:
        bits.append(f"The most it can lose is <b>{_usd(abs(ml))}</b>.")
    elif a.get("max_loss_unbounded"):
        bits.append("<b>There is no limit on what it can lose</b> if the price keeps "
                    "running against you.")

    if days is not None:
        bits.append(f"All of that is settled in <b>{days} trading "
                    f"{'session' if days == 1 else 'sessions'}</b>.")

    # ---- what it behaves like, day to day
    shares = g["delta"]
    gsent: List[str] = []
    if abs(shares) >= 1:
        gsent.append(f"Day to day this behaves like owning <b>{abs(shares):,.0f} "
                     f"{'shares' if abs(shares) != 1 else 'share'}</b>"
                     f"{' (short)' if shares < 0 else ''}: a $1 move in {short} "
                     f"changes it by about <b>{_usd(abs(shares))}</b>"
                     f"{' against you' if shares < 0 else ''}.")
    # Position gamma is ALREADY the change in position delta, and position
    # delta is already counted in shares -- the hundred is applied once when
    # the leg is sized. Multiplying again turned a straddle's honest five
    # shares per dollar into four hundred and seventy-five.
    if abs(g["gamma"]) >= 0.05:
        direction = "grows" if g["gamma"] > 0 else "shrinks"
        gsent.append(f"That sensitivity is not fixed &mdash; it {direction} by about "
                     f"<b>{abs(g['gamma']):,.1f} shares</b> for every dollar "
                     f"{short} rises, so the position "
                     f"{'speeds up as it works' if g['gamma'] > 0 else 'slows as it works and quickens as it fails'}.")
    if abs(g["theta"]) >= 0.01:
        gsent.append(f"Time {'costs you' if g['theta'] < 0 else 'pays you'} "
                     f"<b>{_usd(abs(g['theta']))} a day</b> whether or not anything "
                     f"happens.")
    if abs(g["vega"]) >= 0.01:
        gsent.append(f"If implied volatility rises by one point you "
                     f"{'gain' if g['vega'] > 0 else 'lose'} about "
                     f"<b>{_usd(abs(g['vega']))}</b>; if it falls a point, the reverse.")

    return {"position": " ".join(bits), "behaviour": " ".join(gsent)}


def _rises(a: Dict[str, Any]) -> bool:
    """Does the payoff improve as the price goes up?"""
    c = a.get("curve") or []
    return bool(c) and c[-1]["pl"] > c[0]["pl"]


def _outside(a: Dict[str, Any]) -> bool:
    """With two break-evens, is the money made outside them or between?

    Judged at the midpoint BETWEEN the break-evens, which is the only place
    that answers the question. Taking the midpoint of the whole plotted
    range instead landed wherever the chart happened to start and stop, and
    told a long straddle it earned between its break-evens and a short
    strangle that it earned outside them -- each exactly inverted.
    """
    c = a.get("curve") or []
    bes = a.get("breakevens") or []
    if not c or len(bes) < 2:
        return False
    target = (min(bes) + max(bes)) / 2
    mid = min(c, key=lambda p: abs(p["s"] - target))
    return mid["pl"] < 0


def _where_extreme(pay, strikes: List[float], spot: float) -> Dict[str, Any]:
    """Where the best and worst cases happen -- as a range, not a point.

    "The most you can lose is $300" is a true sentence that tells you
    nothing about whether to worry. The missing half is the price it
    happens at, and for a cash-secured put that half is the whole
    argument.

    But the price is usually a RANGE. A bull call spread loses its full
    premium anywhere at or below the long strike, not at zero, and an
    iron condor makes its maximum anywhere between the two short
    strikes. Reporting the single worst grid point named $0.00 for a
    spread that is equally dead at $100 -- technically true, and it
    would have sent someone looking for a crash that was not the risk.

    Payoffs are piecewise linear with corners only at the strikes, so
    checking zero, every strike and one point far out finds both the
    extreme and the full span it holds over.
    """
    strikes = sorted(set(strikes))
    if not strikes:
        return {"best_at": None, "worst_at": None}

    far = max(max(strikes), spot) * 4
    # A calendar's profit peaks BETWEEN the strikes rather than on one,
    # because the surviving leg's value is a curve and not a straight
    # line. Corners alone are enough for a piecewise-linear payoff and
    # are not enough here, so the grid is filled in either way.
    grid = [0.0] + strikes + [far] + [
        spot * (0.2 + 1.8 * i / 160) for i in range(161)]
    pts = sorted({round(x, 4) for x in grid if x >= 0})
    pts = [(x, pay(x)) for x in pts]

    def span(target: float):
        """Every stretch of price over which `target` is reached.

        There can be more than one, and they need to stay apart. An iron
        condor loses its maximum below the lower wing AND above the
        upper one; collapsing those to a single low-to-high range says
        it loses the maximum everywhere, including the middle, which is
        exactly where it makes money.
        """
        xs = [x for x, _ in pts]
        hit = [abs(pl - target) < 0.005 for _, pl in pts]
        out, i = [], 0
        while i < len(xs):
            if not hit[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(xs) and hit[j + 1]:
                j += 1
            out.append({"lo": round(xs[i], 2), "hi": round(xs[j], 2),
                        "to_zero": xs[i] <= 0.0, "to_inf": xs[j] >= far})
            i = j + 1
        return out or None

    return {
        "best_at": span(max(pl for _, pl in pts)),
        "worst_at": span(min(pl for _, pl in pts)),
    }


_BIAS_OF_DIR = {"up": "bullish", "down": "bearish",
                "still": "neutral", "move": "either"}


def bias_of(needs: Dict[str, Any]) -> Dict[str, Any]:
    """Which way you are hoping it goes, and whether it has to move at all.

    Read off the payoff rather than the name. The direction alone is not
    the whole answer: a cash-secured put and a long call are both
    "bullish" and they are not the same hope. One needs a rise; the
    other only needs the price NOT to fall through a level it is already
    above. Saying "bullish" for both and stopping there is the thing
    that makes an options page unreadable.
    """
    d = (needs or {}).get("dir")
    bias = _BIAS_OF_DIR.get(d, "unclear")
    winning = bool((needs or {}).get("winning_now"))
    pct = (needs or {}).get("move_pct")

    if bias in ("bullish", "bearish"):
        word = "up" if bias == "bullish" else "down"
        if winning:
            shade, plain = "holds", f"it only has to stay {word}"
        else:
            shade, plain = "needs", f"it has to go {word}"
    elif bias == "neutral":
        shade, plain = "holds", "it has to stay in a range"
    elif bias == "either":
        shade, plain = "needs", "it has to move, either way"
    else:
        shade, plain = "", ""

    return {"bias": bias, "shade": shade, "plain": plain,
            "already": winning, "move_pct": pct}


def _hope(needs: Dict[str, Any], where: Dict[str, Any], bes: List[float],
          spot: float, ext: Dict[str, Any]) -> Dict[str, Any]:
    """Which way you want it to go, and how far.

    The direction on its own does not tell you what you have signed up
    for. "Bullish" covers a long call that needs a six percent rise and
    a cash-secured put that needs the price not to fall four percent --
    opposite amounts of hoping, under one word.

    So this states three levels in the order they are reached: where the
    position stops losing, where it stops improving, and how far each is
    from today's price as a percentage. Everything here is read off the
    payoff, not off the name of the structure.
    """
    b = bias_of(needs)
    pct = lambda lvl: (round((lvl / spot - 1) * 100, 1) if spot else None)

    steps = []
    if bes:
        # Sorted by distance, then walked. Taking the min and the max
        # separately returned the SAME break-even twice on an iron
        # condor, whose two sides are equidistant from the share price
        # by construction -- and Python hands back the first element on
        # a tie for both.
        ordered = sorted(bes, key=lambda x: (abs(x - spot), x))
        inside = bool(needs.get("winning_now"))

        # Where the stock stands relative to EACH level, rather than one
        # verdict pinned to the first of them. On a two-sided position
        # "already past it" was printed against a break-even above the
        # share price that it had not come near: an iron condor sits
        # BETWEEN its break-evens, and passing either one is the thing
        # that ends it.
        def _note(level, first):
            if len(ordered) > 1:
                side = "above" if level > spot else "below"
                if first:
                    return (f"it trades {'below' if level > spot else 'above'} this now"
                            + (" and profits inside the pair" if inside else ""))
                return f"the other end, {side} where it trades now"
            if inside:
                return "it is already past this"
            return ("it has to get above this" if level > spot
                    else "it has to get below this")

        for i, level in enumerate(ordered):
            steps.append({
                "label": "breaks even at" if i == 0 else "and at",
                "level": round(level, 2),
                "pct": pct(level),
                "note": _note(level, i == 0),
            })

    # Where it stops getting better. For anything uncapped there is no
    # such price, and saying one would be the opposite of the truth.
    if ext.get("max_profit_unbounded"):
        steps.append({"label": "best case", "level": None, "pct": None,
                      "note": "no cap -- the further it runs, the more it makes"})
    else:
        best = (where.get("best_at") or [None])[0]
        if best:
            if best.get("to_inf"):
                lvl, tail = best["lo"], "or anywhere above"
            elif best.get("to_zero"):
                lvl, tail = best["hi"], "or anywhere below"
            elif abs(best["hi"] - best["lo"]) < 0.005:
                lvl, tail = best["lo"], "exactly"
            else:
                lvl, tail = best["lo"], f"up to ${best['hi']:,.2f}"
            steps.append({
                "label": "makes the most at", "level": round(lvl, 2),
                "pct": pct(lvl),
                "note": f"{tail} -- past there it makes no more"
                        if "above" in tail or "below" in tail else tail,
            })

    return {**b, "spot": round(spot, 2), "steps": steps}


def _needs(pay, spot: float, bes: List[float],
           curve: List[Dict]) -> Dict[str, Any]:
    """What has to happen for this to work, as a direction and a level.

    Read off the payoff rather than the strategy name, because the name
    is a label and the payoff is the trade. A "bull" call spread someone
    has entered upside-down is not bullish, and the shape knows that
    while the label does not.
    """
    if not curve:
        return {"dir": "unknown", "text": "", "level": None,
                "move_pct": None, "winning_now": False}

    low, high = curve[0]["pl"], curve[-1]["pl"]
    mid = pay(spot)
    below = [b for b in bes if b < spot]
    above = [b for b in bes if b >= spot]

    def gap(level):
        return round((level / spot - 1) * 100, 1) if spot else None

    # Whether the level is already on the right side of you changes the
    # sentence completely. A short call at 105 with the stock at 100 does
    # not need the stock to FALL -- it needs it not to rise, and it wins
    # if nothing happens at all. Telling someone holding a credit trade
    # that they need a move is exactly backwards.
    winning = mid > 0

    if high > 0 >= low:
        lvl = min(above) if above else (max(bes) if bes else None)
        verb = "stay above" if winning else "rise above"
        return {"dir": "up", "level": lvl, "winning_now": winning,
                "move_pct": gap(lvl) if lvl else None,
                "text": (f"{verb} {_dollars(lvl)}" if lvl
                         else ("stay up" if winning else "rise"))}
    if low > 0 >= high:
        lvl = max(below) if below else (min(bes) if bes else None)
        verb = "stay below" if winning else "fall below"
        return {"dir": "down", "level": lvl, "winning_now": winning,
                "move_pct": gap(lvl) if lvl else None,
                "text": (f"{verb} {_dollars(lvl)}" if lvl
                         else ("stay down" if winning else "fall"))}
    if mid > 0 and low <= 0 and high <= 0:
        lo = max(below) if below else (min(bes) if bes else None)
        hi = min(above) if above else (max(bes) if bes else None)
        return {"dir": "still", "level": None, "move_pct": None,
                "winning_now": mid > 0,
                "text": (f"finish between {_dollars(lo)} and {_dollars(hi)}"
                         if lo is not None and hi is not None else "stay where it is")}
    if mid <= 0 and low > 0 and high > 0:
        lo = max(below) if below else (min(bes) if bes else None)
        hi = min(above) if above else (max(bes) if bes else None)
        return {"dir": "move", "level": None, "move_pct": None,
                "winning_now": mid > 0,
                "text": (f"finish below {_dollars(lo)} or above {_dollars(hi)}"
                         if lo is not None and hi is not None
                         else "move a long way, either direction")}
    if low > 0 and high > 0 and mid > 0:
        return {"dir": "any", "level": None, "move_pct": None,
                "winning_now": True,
                "text": "make money wherever it finishes"}
    return {"dir": "none", "level": None, "move_pct": None,
            "winning_now": False,
            "text": "finish outside the range this can profit in"}


def _dollars(v: Optional[float]) -> str:
    return "--" if v is None else f"${v:,.2f}"


def _chance_working(parts: Optional[Dict[str, Any]],
                    sessions: Optional[int]) -> Optional[Dict[str, Any]]:
    """The sum behind the odds, if there were any odds to work out."""
    if not parts or not parts.get("regions"):
        return None
    import working as W                                   # noqa: PLC0415
    return W.chance(parts["regions"], parts["total"], parts["spot"],
                    parts["vol"], parts["years"], parts["rate"],
                    parts["q"], sessions)


def _extreme_price(regions: Optional[List[Dict[str, Any]]]) -> Optional[float]:
    """One finishing price to illustrate an extreme that holds over a range.

    A bull call spread makes its maximum anywhere at or above the short
    strike, so there is no single price to show -- but there is a
    natural one: the corner where the extreme is first reached. Picking
    the far end instead would settle the arithmetic at four times spot
    and read like a forecast of one.
    """
    if not regions:
        return None
    r = regions[0]
    if r.get("to_inf"):
        return r["lo"]
    if r.get("to_zero"):
        return r["hi"]
    return r["lo"]


def _position_working(legs: List[Dict[str, Any]], cost: float, value_now: float,
                      pl: float, risk: Optional[float],
                      ext: Dict[str, Any],
                      where: Dict[str, Any]) -> Dict[str, Any]:
    """The arithmetic behind the figures the page puts in large type.

    Everything here is already computed elsewhere and shown as a
    result. This is the same result written as the sum it came from, so
    the reader can check it rather than trust it.
    """
    import working as W                                   # noqa: PLC0415

    out: Dict[str, Any] = {
        "net_cost": W.net_cost([
            {"kind": l["kind"], "qty": l["qty"], "entry": l["entry"],
             "strike": l["strike"], "side": "long" if l["side"] > 0 else "short"}
            for l in legs]),
        "profit": W.profit_now(round(value_now, 2), round(cost, 2)),
    }
    if risk:
        out["pl_pct"] = W.percent_of_risk(round(pl, 2), round(risk, 2))

    out["max_profit"] = W.settlement(
        legs, _extreme_price(where.get("best_at")), cost,
        ext.get("max_profit_unbounded"))
    out["max_loss"] = W.settlement(
        legs, _extreme_price(where.get("worst_at")), cost,
        ext.get("max_loss_unbounded"))
    return out


def _greek_working(legs: List[Dict[str, Any]], spot: float, vol: float,
                   rate: float, div_yield: float) -> Dict[str, Any]:
    """The arithmetic behind each greek, for the position's first option.

    Position greeks are sums across legs, and a sum of five products is
    not a thing anyone reads. What a reader wants is what ONE of them
    is and where it came from, so the working is for the leading option
    leg -- the whole position's figure is that, scaled by size and
    added up, which the panel already says in words.
    """
    import working as W                                   # noqa: PLC0415

    leg = next((l for l in legs if l["kind"] != "stock" and l["strike"]), None)
    if not leg:
        return {}
    years = _years(leg["expiry"])
    if not years:
        return {}

    is_call = leg["kind"] == "call"
    out = {"strike": leg["strike"], "kind": leg["kind"], "expiry": leg["expiry"]}
    for name in ("delta", "gamma", "theta", "vega", "rho"):
        w = W.greek(name, spot, leg["strike"], years, vol, rate, is_call, div_yield)
        if w:
            out[name] = w
    out["price"] = W.option_price(spot, leg["strike"], years, vol, rate,
                                  is_call, div_yield)
    return out


def _breakeven_working(bes: List[float], legs: List[Dict[str, Any]],
                       cost: float) -> List[Dict[str, Any]]:
    """The arithmetic behind each break-even, where there is any.

    The engine finds these by scanning the payoff and bisecting,
    because the closed form differs for every structure in the
    taxonomy. But the ANSWER is usually one simple sum: the strike the
    payoff bends at, plus or minus what the position cost per share.

    That claim is only made where it holds. Each candidate strike is
    tried and the sum is kept only if it reproduces the level the scan
    already found, to within a cent. Where nothing reconstructs it --
    a butterfly, a ratio, anything bending more than once on the way
    -- the panel says the level was solved for rather than dressing up
    a bisection as arithmetic.
    """
    import working as W                                   # noqa: PLC0415

    # Per share of the UNDERLYING, not per leg. A vertical is two
    # contracts and still covers a hundred shares, so dividing by the
    # number of legs halved the cost and put the break-even in the
    # wrong place on everything except a single option.
    lots = max((l["qty"] for l in legs if l["kind"] != "stock"), default=1) or 1
    per_share = cost / (MULT * lots)
    strikes = sorted({l["strike"] for l in legs if l["strike"]})

    out = []
    for be in bes:
        best = None
        for k in strikes:
            for upward in (True, False):
                # Magnitude here, direction from the flag. A credit
                # carries a negative cost, so adding it moved the level
                # the wrong way -- and printed "95 + 3 = 92", which is
                # an arithmetic error sitting in a tooltip whose entire
                # job is showing arithmetic.
                level = k + abs(per_share) if upward else k - abs(per_share)
                if abs(level - be) < 0.01:
                    best = (k, upward)
                    break
            if best:
                break
        out.append(W.breakeven_from(be, best[0], per_share, best[1]) if best
                   else W.breakeven_solved(be))
    return out


def _chance_of_profit(pay, legs: List[Dict[str, Any]], spot: float, vol: float,
                      rate: float, div_yield: float,
                      bes: List[float]) -> Tuple[Optional[float], Optional[Dict]]:
    """The odds this finishes profitable, under the same lognormal the
    prices already assume.

    The break-evens cut the price line into regions, and a payoff that is
    piecewise linear cannot change sign inside one. So: work out the sign
    of each region by evaluating the middle of it, then add up the
    probability mass of the regions that pay.

    This is a RISK-NEUTRAL probability -- the drift is (r - q - v^2/2), not
    whatever you think the stock will do. It is the market's own number,
    which is what makes it consistent with the prices on the rest of the
    page, and it is not a forecast.
    """
    if not bes or not vol or not spot:
        return None, None
    expiries = [l["expiry"] for l in legs if l["expiry"]]
    if not expiries:
        return None, None
    years = _years(min(expiries))
    if not years or years <= 0:
        return None, None

    q = div_yield or 0.0
    drift = (rate - q - 0.5 * vol * vol) * years
    sd = vol * math.sqrt(years)
    if sd <= 0:
        return None, None

    def above(k: float) -> float:
        if k <= 0:
            return 1.0
        return O._norm_cdf((math.log(spot / k) + drift) / sd)

    edges = [0.0] + sorted(bes) + [float("inf")]
    total = 0.0
    # Kept as we go, because the single percentage hides that anything
    # two-sided has two separate ways of winning -- a straddle's 41% is
    # an 18% fall and a 23% rise, and those are not the same bet.
    regions: List[Dict[str, Any]] = []
    for lo, hi in zip(edges, edges[1:]):
        mid = (lo + hi) / 2 if hi != float("inf") else lo * 1.5 + 1.0
        if pay(mid) <= 0:
            continue
        p = (1.0 if lo <= 0 else above(lo)) - (0.0 if hi == float("inf") else above(hi))
        total += p
        if hi == float("inf"):
            label = f"chance it finishes above ${lo:,.2f}"
        elif lo <= 0:
            label = f"chance it finishes below ${hi:,.2f}"
        else:
            label = f"chance it finishes between ${lo:,.2f} and ${hi:,.2f}"
        regions.append({"lo": None if lo <= 0 else round(lo, 2),
                        "hi": None if hi == float("inf") else round(hi, 2),
                        "p": round(p, 6), "label": label})

    pct = round(max(0.0, min(1.0, total)) * 100, 1)
    return pct, {"regions": regions, "vol": vol, "years": years,
                 "rate": rate, "q": q, "spot": spot, "total": pct}
