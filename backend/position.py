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
def identify(legs: List[Dict[str, Any]]) -> Dict[str, Any]:
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
                if len(calls) == 2 and (S(far) or 0) < (S(near) or 0):
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
            if sides == [1, -1, -1, 1]:
                return _named("Iron condor (sold)", "income",
                              "Paid for a range, with both tails bought back.")
            if sides == [-1, 1, 1, -1]:
                return _named("Iron condor (bought)", "volatility")
        if len(set(kinds)) == 1:
            if sides == [1, -1, -1, 1]:
                return _named(f"Long condor with {kinds[0]}s", "volatility")
        if kinds.count("put") == 2 and kinds.count("call") == 2:
            strikes = [S(l) for l in s]
            if strikes[1] == strikes[2] and sides == [1, -1, -1, 1]:
                return _named("Iron butterfly (sold)", "income")

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


def _breakevens(legs, lo: float, hi: float, steps: int = 4000) -> List[float]:
    """Where the payoff crosses zero, found by scanning and bisecting.

    Solved numerically rather than per strategy: the closed forms differ for
    every structure in the taxonomy, and a sign change is a sign change
    whatever the shape above it.
    """
    out: List[float] = []
    prev_x = lo
    prev_y = payoff_at(legs, lo)
    for i in range(1, steps + 1):
        x = lo + (hi - lo) * i / steps
        y = payoff_at(legs, x)
        if prev_y == 0:
            out.append(round(prev_x, 2))
        elif (prev_y < 0) != (y < 0):
            a, b = prev_x, x
            for _ in range(60):
                m = 0.5 * (a + b)
                if (payoff_at(legs, a) < 0) != (payoff_at(legs, m) < 0):
                    b = m
                else:
                    a = m
            out.append(round(0.5 * (a + b), 2))
        prev_x, prev_y = x, y
    # Collapse duplicates that the scan can produce at a kink.
    tidy: List[float] = []
    for v in out:
        if not tidy or abs(v - tidy[-1]) > 0.01:
            tidy.append(v)
    return tidy


def _extremes(legs, spot: float) -> Dict[str, Any]:
    """Max profit and max loss, and whether either is unbounded.

    Checked by walking the payoff far past every strike in both directions
    and looking at the slope at the ends: a payoff still rising at four
    times spot is not going to turn around.
    """
    strikes = [l["strike"] for l in legs if l["strike"]] or [spot]
    lo, hi = 0.0, max(max(strikes), spot) * 4
    # The grid must contain every strike and zero exactly. A payoff is
    # piecewise linear with a corner at each strike, so its maximum and
    # minimum can only occur at a corner or at an end -- and a linspace
    # that steps straight past 100.00 reported a long straddle's worst case
    # as -1099.25 instead of the -1100 it actually is.
    xs = sorted(set([lo, hi, spot] + strikes
                    + [lo + (hi - lo) * i / 2000 for i in range(2001)]))
    ys = [payoff_at(legs, x) for x in xs]

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
        "at_zero": round(payoff_at(legs, 0.0), 2),
    }


def analyse(raw_legs: List[Dict[str, Any]], spot: float, vol: float,
            rate: float, div_yield: float = 0.0,
            chain_marks: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Everything about a position that is already on."""
    legs = [_norm(l) for l in raw_legs if l.get("kind")]
    legs = [l for l in legs if l["qty"] > 0]
    if not legs or not spot:
        return {"ok": False, "reason": "no legs"}

    strategy = identify(legs)
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
    ext = _extremes(legs, spot)
    strikes = [l["strike"] for l in legs if l["strike"]] or [spot]
    lo = max(0.01, min(min(strikes), spot) * 0.4)
    hi = max(max(strikes), spot) * 1.8
    bes = _breakevens(legs, lo, hi)

    # What is actually at risk. For a debit that is what you paid; for a
    # credit spread it is the width less the credit, which is what max_loss
    # already found. Percentages against the wrong denominator are the most
    # common way an options P&L is misread.
    risk = abs(ext["max_loss"]) if ext["max_loss"] is not None and ext["max_loss"] < 0 \
        else (abs(cost) if cost > 0 else None)

    curve = []
    for i in range(61):
        x = lo + (hi - lo) * i / 60
        curve.append({"s": round(x, 2), "pl": round(payoff_at(legs, x), 2)})

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
    out: List[Dict[str, str]] = []
    add = lambda h, b, f="": out.append({"head": h, "body": b, "figure": f})

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
        f"{share}{captured}", f"{'+' if pl >= 0 else '-'}{_usd(abs(pl))}")

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
            f"{_usd(theta)}/day")

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
            f"${nearest:,.2f}")

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
        names = ", ".join(f"${l['strike']:,.0f} {l['kind']}" for l in itm_shorts)
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
        half = _price_for_pl(a, mp * 0.5)
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
            add("Where half the profit is",
                f"Half of the maximum ({_usd(mp * 0.5)}) is reached around "
                f"<b>${half:,.2f}</b>. {why}", f"${half:,.2f}")
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


def _price_for_pl(a: Dict[str, Any], target: float) -> Optional[float]:
    """The underlying price at which the payoff first reaches `target`."""
    best, dist = None, None
    for p in a["curve"]:
        if p["pl"] >= target:
            d = abs(p["s"] - a["spot"])
            if dist is None or d < dist:
                best, dist = p["s"], d
    return best


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
    bits: List[str] = [f"You are in a <b>{s['name'].lower()}</b> on {who}."]

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
