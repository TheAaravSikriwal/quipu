"""Options chains with greeks, plus the numbers an options trader reads first.

yfinance gives strikes, bid/ask, volume, open interest and implied volatility --
but no greeks. We compute those with Black-Scholes from the quoted IV, so
delta/gamma/theta/vega are available without a paid data provider.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import yfinance as yf

DEFAULT_RISK_FREE = 0.042  # fallback if the T-bill lookup fails


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def risk_free_rate() -> float:
    """13-week T-bill as the short rate. Falls back to a constant."""
    try:
        frame = yf.Ticker("^IRX").history(period="5d")
        if frame is not None and not frame.empty:
            return float(frame["Close"].iloc[-1]) / 100.0
    except Exception:
        pass
    return DEFAULT_RISK_FREE


def greeks(
    spot: float,
    strike: float,
    years: float,
    vol: float,
    rate: float,
    is_call: bool,
    div_yield: float = 0.0,
) -> Dict[str, Optional[float]]:
    """Black-Scholes greeks, carrying the dividend yield.

    Every greek picks up a factor of exp(-qT) once the underlying pays a
    dividend. Leaving it out -- as this did -- overstates call delta and
    misprices theta and rho on any dividend payer.
    """
    if not all(v and v > 0 for v in (spot, strike, years, vol)):
        return {"delta": None, "gamma": None, "theta": None, "vega": None, "rho": None}

    q = div_yield or 0.0
    sqrt_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate - q + 0.5 * vol * vol) * years) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    discount = math.exp(-rate * years)
    carry = math.exp(-q * years)

    delta = carry * (_norm_cdf(d1) if is_call else _norm_cdf(d1) - 1.0)
    gamma = carry * _norm_pdf(d1) / (spot * vol * sqrt_t)
    vega = spot * carry * _norm_pdf(d1) * sqrt_t / 100.0  # per 1 vol point

    theta_common = -(spot * carry * _norm_pdf(d1) * vol) / (2.0 * sqrt_t)
    if is_call:
        theta = (theta_common
                 - rate * strike * discount * _norm_cdf(d2)
                 + q * spot * carry * _norm_cdf(d1)) / 365.0
        rho = strike * years * discount * _norm_cdf(d2) / 100.0
    else:
        theta = (theta_common
                 + rate * strike * discount * _norm_cdf(-d2)
                 - q * spot * carry * _norm_cdf(-d1)) / 365.0
        rho = -strike * years * discount * _norm_cdf(-d2) / 100.0

    # Returned at full precision. Rounding here rather than where a
    # number is shown is a category error: the position engine sums
    # these across legs and multiplies by a hundred, the working
    # re-derives them to show its arithmetic, and the binomial
    # comparison differences them -- all of which want the number the
    # model produced rather than a four-decimal picture of it. Every
    # caller that puts one in front of a reader rounds it there.
    return {
        "delta": delta,
        "gamma": gamma,
        "theta": theta,
        "vega": vega,
        "rho": rho,
    }


def bs_price(
    spot: float, strike: float, years: float, vol: float, rate: float,
    is_call: bool, div_yield: float = 0.0
) -> float:
    """Black-Scholes fair value -- the forward direction of the IV solver.

    Carries the dividend yield, and must: greeks() discounts the spot leg by
    e^-qT, and this function is what implied_vol() inverts. Without q here
    the solver returned the volatility of a DIFFERENT model from the one the
    greeks then used -- the IV was solved as though the stock paid nothing,
    and delta and gamma were computed as though it paid q. On a 4% yielder
    that is a real disagreement, and it was invisible because each half
    looked correct on its own.
    """
    if vol <= 0 or years <= 0:
        intrinsic = (spot - strike) if is_call else (strike - spot)
        return max(intrinsic, 0.0)

    q = div_yield or 0.0
    sqrt_t = math.sqrt(years)
    d1 = (math.log(spot / strike) + (rate - q + 0.5 * vol * vol) * years) / (vol * sqrt_t)
    d2 = d1 - vol * sqrt_t
    discount = math.exp(-rate * years)
    carry = math.exp(-q * years)

    if is_call:
        return spot * carry * _norm_cdf(d1) - strike * discount * _norm_cdf(d2)
    return strike * discount * _norm_cdf(-d2) - spot * carry * _norm_cdf(-d1)


def implied_vol(
    price: float,
    spot: float,
    strike: float,
    years: float,
    rate: float,
    is_call: bool,
    div_yield: float = 0.0,
) -> Optional[float]:
    """Back out volatility from the traded price by bisection.

    Yahoo's own impliedVolatility field is unreliable -- it frequently returns
    placeholder values like 0.00001, which would make every greek zero. Solving
    from the price we can see is slower but honest. Bisection rather than
    Newton because it cannot diverge on the ragged quotes we actually get.
    """
    if not all(v and v > 0 for v in (price, spot, strike, years)):
        return None

    q = div_yield or 0.0
    intrinsic = max((spot - strike) if is_call else (strike - spot), 0.0)
    if price < intrinsic - 0.01:
        return None  # price below intrinsic: quote is broken, not a vol signal

    low, high = 1e-4, 6.0  # 0.01% to 600% vol
    if bs_price(spot, strike, years, high, rate, is_call, q) < price:
        return None  # even 600% vol cannot reach this price

    for _ in range(60):
        mid = 0.5 * (low + high)
        if bs_price(spot, strike, years, mid, rate, is_call, q) < price:
            low = mid
        else:
            high = mid
        if high - low < 1e-6:
            break

    solved = 0.5 * (low + high)
    return solved if 0.005 < solved < 5.99 else None


def _easter(year: int) -> date:
    """Anonymous Gregorian algorithm. Needed only to find Good Friday."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    g = (8 * b + 13) // 25
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (2 * e + 2 * i - h - k + 32) % 7
    m = (a + 11 * h + 19 * l) // 433
    month, day = divmod(h + l - 7 * m + 90, 25)
    day = (h + l - 7 * m + 33 * month + 19) % 32
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """The nth given weekday of a month; n = -1 means the last one."""
    if n > 0:
        d = date(year, month, 1)
        d += timedelta(days=(weekday - d.weekday()) % 7)
        return d + timedelta(weeks=n - 1)
    nxt = date(year + (month == 12), (month % 12) + 1, 1)
    d = nxt - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    """Saturday holidays move to Friday, Sunday holidays to Monday."""
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


def market_holidays(year: int) -> set:
    """The nine-and-a-half days a year the NYSE is shut.

    Computed rather than listed, so it does not expire. Half-days are not
    included: the market is open, and an option decays on an open day.
    """
    out = {
        _observed(date(year, 1, 1)),                      # New Year's Day
        _nth_weekday(year, 1, 0, 3),                      # MLK
        _nth_weekday(year, 2, 0, 3),                      # Presidents
        _easter(year) - timedelta(days=2),                # Good Friday
        _nth_weekday(year, 5, 0, -1),                     # Memorial
        _observed(date(year, 7, 4)),                      # Independence
        _nth_weekday(year, 9, 0, 1),                      # Labor
        _nth_weekday(year, 11, 3, 4),                     # Thanksgiving
        _observed(date(year, 12, 25)),                    # Christmas
    }
    if year >= 2022:
        out.add(_observed(date(year, 6, 19)))             # Juneteenth
    return out


def trading_days(start: datetime, end: datetime) -> int:
    """Sessions between two dates: weekdays, less the days the market shuts.

    The reference dashboards measure time as NETWORKDAYS/252 rather than
    calendar days/365, and on a short-dated option the two disagree enough to
    move theta noticeably: a Friday expiry three calendar days out is only one
    trading day of decay away.

    Holidays are subtracted, which the first version claimed to do and did
    not. Counting bare weekdays made a calendar year 261 sessions instead of
    252, so T came out 3.6% too long, every option looked slightly too
    valuable and theta slightly too slow -- small per day, and pure bias.
    """
    if end <= start:
        return 0
    cur, last = start.date(), end.date()
    shut = set()
    for y in range(cur.year, last.year + 1):
        shut |= market_holidays(y)
    days = 0
    while cur < last:
        cur += timedelta(days=1)
        if cur.weekday() < 5 and cur not in shut:
            days += 1
    return days


def _clean(value: Any, digits: int = 4) -> Optional[float]:
    try:
        num = float(value)
        if num != num or math.isinf(num):
            return None
        return round(num, digits)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int:
    """NaN is truthy, so `value or 0` lets it through. Guard explicitly."""
    try:
        num = float(value)
        if num != num or math.isinf(num):
            return 0
        return int(num)
    except (TypeError, ValueError):
        return 0


def _binomial_fields(spot, strike, years, vol, rate, is_call, div_yield):
    """Tree price for one contract, flattened onto the row. Cheap enough at
    64 steps to run for every strike; the tile only shows it on request."""
    if not vol:
        return {"binomial": None, "early_exercise": None}
    b = binomial(spot, strike, years, vol, rate, is_call, div_yield, steps=64)
    if not b.get("available"):
        return {"binomial": None, "early_exercise": None}
    return {"binomial": b["price"], "early_exercise": b["early_exercise_value"]}


def _rows(frame, spot: float, years: float, rate: float, is_call: bool,
          div_yield: float = 0.0) -> List[Dict]:
    out: List[Dict[str, Any]] = []
    if frame is None or frame.empty:
        return out

    for _, row in frame.iterrows():
        strike = _clean(row.get("strike"))
        iv = _clean(row.get("impliedVolatility"), 6)
        if strike is None:
            continue

        volume = _int(row.get("volume"))
        oi = _int(row.get("openInterest"))
        bid, ask = _clean(row.get("bid")), _clean(row.get("ask"))
        last = _clean(row.get("lastPrice"))

        # Prefer the mid of a live two-sided quote; fall back to the last trade.
        mark = (bid + ask) / 2 if bid and ask else last
        intrinsic = max(spot - strike, 0.0) if is_call else max(strike - spot, 0.0)

        # Treat Yahoo's IV as a hint, not a fact. Anything outside a plausible
        # band is a placeholder, so solve from the price instead.
        vendor_iv = iv if iv and 0.01 < iv < 5.0 else None
        solved_iv = implied_vol(mark, spot, strike, years, rate, is_call, div_yield)
        use_iv = solved_iv or vendor_iv
        iv_source = "solved" if solved_iv else ("vendor" if vendor_iv else "none")

        out.append(
            {
                "contract": row.get("contractSymbol"),
                # Calls and puts get merged in the unusual-activity list, and
                # a row there is unreadable without saying which it is.
                "type": "call" if is_call else "put",
                "strike": strike,
                "last": last,
                "bid": bid,
                "ask": ask,
                "mark": round(mark, 4) if mark else None,
                "spread_pct": round(((ask - bid) / ask) * 100, 2)
                if bid and ask else None,
                "volume": volume,
                "open_interest": oi,
                # Volume well above open interest means today's flow is new
                # positioning, not existing holders trading among themselves.
                "vol_oi_ratio": round(volume / oi, 2) if oi > 0 else None,
                "iv": round(use_iv * 100, 2) if use_iv else None,
                "iv_source": iv_source,
                "itm": bool(row.get("inTheMoney", False)),
                **_binomial_fields(spot, strike, years, use_iv, rate, is_call, div_yield),
                # What you are buying: intrinsic is value you would have if it
                # expired now, extrinsic is what you pay for the time left.
                "intrinsic": round(intrinsic, 4),
                "extrinsic": round(max((mark or 0) - intrinsic, 0), 4),
                "extrinsic_pct": round((max((mark or 0) - intrinsic, 0) / mark) * 100, 1)
                if mark else None,
                **greeks(spot, strike, years, use_iv or 0.0, rate, is_call, div_yield),
            }
        )
    return out


def binomial(spot: float, strike: float, years: float, vol: float, rate: float,
             is_call: bool, div_yield: float = 0.0, steps: int = 100,
             american: bool = True) -> Dict[str, Any]:
    """Cox-Ross-Rubinstein tree, the way the reference dashboard builds it.

    Black-Scholes assumes you hold to expiry. A tree does not: at every node
    it asks whether exercising right now beats waiting, which is the one
    question Black-Scholes cannot answer. For American options -- which is
    over 90% of listed equity options -- that difference is real money,
    concentrated in deep in-the-money puts and in calls over a dividend.

        dt = T / steps
        u  = exp(vol * sqrt(dt))          up branch
        d  = 1 / u                        down branch
        p  = (growth - d) / (u - d)       risk-neutral up probability
        discount = exp(-r * dt)           per step

    Then walk backwards from expiry. At each node the value is the larger of
    exercising now and the discounted average of the two nodes it leads to.
    Set american=False and the exercise branch is switched off, which is the
    workbook's EUROPEAN_ZERO_AMERICAN_ONE flag.
    """
    if not all(v and v > 0 for v in (spot, strike, years, vol)) or steps < 1:
        return {"available": False}

    q = div_yield or 0.0
    dt = years / steps
    u = math.exp(vol * math.sqrt(dt))
    d = 1.0 / u
    growth = math.exp((rate - q) * dt)
    if not (d < growth < u):
        # No risk-neutral probability exists; the tree is too coarse for these
        # inputs and would produce a number that looks fine and is not.
        return {"available": False, "reason": "tree does not admit a probability"}

    p_up = (growth - d) / (u - d)
    p_dn = 1.0 - p_up
    disc = math.exp(-rate * dt)

    # terminal payoffs
    values = []
    for i in range(steps + 1):
        s_t = spot * (u ** (steps - i)) * (d ** i)
        values.append(max(s_t - strike, 0.0) if is_call else max(strike - s_t, 0.0))

    early_gain = 0.0
    for step in range(steps - 1, -1, -1):
        for i in range(step + 1):
            hold = (p_up * values[i] + p_dn * values[i + 1]) * disc
            if american:
                s_t = spot * (u ** (step - i)) * (d ** i)
                exercise = max(s_t - strike, 0.0) if is_call else max(strike - s_t, 0.0)
                if exercise > hold:
                    early_gain = max(early_gain, exercise - hold)
                    hold = exercise
            values[i] = hold

    price = values[0]
    euro = price
    if american:
        e = binomial(spot, strike, years, vol, rate, is_call, q, steps, american=False)
        euro = e.get("price", price) if e.get("available") else price

    return {
        "available": True,
        "price": round(price, 4),
        "european_price": round(euro, 4),
        # What the right to exercise early is worth. Zero on most calls; real
        # on in-the-money puts, which is exactly where Black-Scholes is wrong.
        "early_exercise_value": round(max(price - euro, 0.0), 4),
        "steps": steps,
        "up": round(u, 6),
        "down": round(d, 6),
        "p_up": round(p_up, 4),
        "p_down": round(p_dn, 4),
        "step_discount": round(disc, 8),
        "dt_years": round(dt, 8),
    }


def probabilities(spot: float, years: float, vol: float, rate: float,
                  div_yield: float = 0.0) -> Dict[str, Any]:
    """Where the market thinks the price will be, and with what odds.

    Lifted from the strike-picking block in the reference dashboards. Under
    the same lognormal the option price already assumes, ln(S_T) is normal
    with mean ln(S) + (r - q - v^2/2)T and standard deviation v*sqrt(T). Every
    number below falls out of that, so the odds are consistent with the prices
    on the rest of the page rather than being a separate opinion.
    """
    if not all(v and v > 0 for v in (spot, years, vol)):
        return {"available": False}

    q = div_yield or 0.0
    drift = (rate - q - 0.5 * vol * vol) * years
    sd = vol * math.sqrt(years)

    def above(k: float) -> float:
        """P(S_T > k). This is N(d2) -- the same d2 the option price uses."""
        if k <= 0:
            return 1.0
        return _norm_cdf((math.log(spot / k) + drift) / sd)

    def band(sigmas: float) -> Dict[str, float]:
        return {
            "low": round(spot * math.exp(drift - sigmas * sd), 2),
            "high": round(spot * math.exp(drift + sigmas * sd), 2),
        }

    def touch(k: float) -> Optional[float]:
        """P(price touches k at any point before expiry).

        Roughly twice the chance of finishing past it, because a path can
        cross and come back. Matters when the plan is to sell before expiry
        rather than hold to it.
        """
        if k <= 0 or spot <= 0:
            return None
        mu = drift / years
        a = math.log(k / spot)
        try:
            p = _norm_cdf((-abs(a) + mu * years) / sd) + math.exp(
                2 * mu * abs(a) / (vol * vol)
            ) * _norm_cdf((-abs(a) - mu * years) / sd)
        except OverflowError:
            return None
        return round(min(max(p, 0.0), 1.0) * 100, 1)

    return {
        "available": True,
        "one_sigma": band(1),      # ~68% of outcomes
        "two_sigma": band(2),      # ~95% of outcomes
        "median": round(spot * math.exp(drift), 2),
        "p_above_spot": round(above(spot) * 100, 1),
        "ladder": [
            {
                "move_pct": m,
                "price": round(spot * (1 + m / 100), 2),
                "p_finish_above": round(above(spot * (1 + m / 100)) * 100, 1),
                "p_touch": touch(spot * (1 + m / 100)),
            }
            for m in (-15, -10, -5, -2.5, 2.5, 5, 10, 15)
        ],
    }


def _max_pain(calls: List[Dict], puts: List[Dict]) -> Optional[float]:
    """The strike at which the most option value expires worthless.

    Meaningless without open interest, and Yahoo often returns it as zero, so
    we return None rather than a confident-looking number built on nothing.
    """
    strikes = sorted({row["strike"] for row in calls + puts})
    if not strikes:
        return None
    if sum(row["open_interest"] for row in calls + puts) == 0:
        return None

    best_strike, best_pain = None, None
    for candidate in strikes:
        pain = 0.0
        for row in calls:
            if candidate > row["strike"]:
                pain += (candidate - row["strike"]) * row["open_interest"]
        for row in puts:
            if candidate < row["strike"]:
                pain += (row["strike"] - candidate) * row["open_interest"]
        if best_pain is None or pain < best_pain:
            best_strike, best_pain = candidate, pain
    return best_strike


def escrowed_spot(spot: float, dividends: Optional[List[Dict]], expiry: str,
                  rate: float, now: Optional[datetime] = None) -> Dict[str, Any]:
    """Spot with the dividends due before expiry taken out of it.

    A continuous dividend yield is the right model for an index and the
    wrong one for a single company, which pays four times a year on
    dates it has announced. The distinction is invisible over a year and
    enormous over a fortnight: Coca-Cola's 2.4% annual yield spread
    smoothly across two weeks removes 8 cents from the spot, but if the
    ex-date falls inside those two weeks the market removes the whole 53.
    Priced both ways the same option differs by 11%, in opposite
    directions for calls and puts.

    So where the payment dates are known, the standard escrowed model is
    used instead: subtract the present value of each dividend going ex
    before expiry, and price off what is left with no yield term at all.
    Put-call parity then reads C - P = S_adj - K.e^(-rT), and the
    early-exercise test in the binomial sees a real dividend on a real
    date rather than a trickle.

    Falls back to whatever continuous yield it was given when the
    schedule is not known -- which is most non-payers, where it is zero
    and the distinction does not arise.
    """
    now = now or datetime.now(timezone.utc)
    if not dividends or not spot:
        return {"spot": spot, "pv": 0.0, "used": [], "model": "yield"}

    try:
        end = datetime.strptime(expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return {"spot": spot, "pv": 0.0, "used": [], "model": "yield"}

    pv, used = 0.0, []
    for d in dividends:
        when, amount = d.get("date"), d.get("amount")
        if not when or not amount:
            continue
        try:
            ex = datetime.strptime(str(when)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        # Strictly between now and expiry. A dividend that has already
        # gone is in the price; one that goes after expiry is not the
        # option holder's concern.
        if not (now <= ex <= end):
            continue
        t = max(trading_days(now, ex) / 252.0, 0.0)
        cash = float(amount) * math.exp(-rate * t)
        pv += cash
        used.append({"date": str(when)[:10], "amount": float(amount),
                     "pv": round(cash, 4)})

    if not used:
        # Known schedule, nothing due before expiry: the correct yield is
        # zero, not the annual average. Saying "yield" here would apply a
        # dividend that is not coming.
        return {"spot": spot, "pv": 0.0, "used": [], "model": "discrete"}

    return {"spot": round(spot - pv, 6), "pv": round(pv, 6),
            "used": used, "model": "discrete"}


def fetch_options(symbol: str, max_expiries: int = 4,
                  div_yield: float = 0.0,
                  only: Optional[str] = None,
                  dividends: Optional[List[Dict]] = None) -> Dict[str, Any]:
    """Chains for the nearest expiries, with greeks and flow metrics.

    `only` pulls a single named expiry instead of the first few. The
    position builder needs one specific board at a time and each expiry is
    its own request, so fetching four to show one is three wasted seconds.
    """
    ticker = yf.Ticker(symbol)
    listed = list(ticker.options or [])
    expiries = [only] if (only and only in listed) else listed[:max_expiries]
    if not expiries:
        return {"available": False, "reason": "no listed options", "expiries": []}

    info = ticker.info or {}
    spot = float(info.get("currentPrice") or info.get("regularMarketPrice") or 0.0)
    rate = risk_free_rate()
    now = datetime.now(timezone.utc)

    chains: List[Dict[str, Any]] = []
    for expiry in expiries:
        try:
            chain = ticker.option_chain(expiry)
        except Exception:
            continue

        expiry_dt = datetime.strptime(expiry, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        days = max((expiry_dt - now).days, 0)
        # Time in TRADING days, as the reference dashboards measure it. A
        # weekend carries no decay in this convention, which matters a lot on
        # a three-day option and not at all on a one-year one.
        tdays = trading_days(now, expiry_dt)
        years = max(tdays / 252.0, 1 / 252.0)

        # Price off the escrowed spot where the payment dates are known,
        # and off the continuous yield where they are not. Never both --
        # that would charge the dividend twice.
        esc = escrowed_spot(spot, dividends, expiry, rate, now)
        use_spot = esc["spot"]
        use_q = 0.0 if esc["model"] == "discrete" else div_yield

        calls = _rows(chain.calls, use_spot, years, rate, True, use_q)
        puts = _rows(chain.puts, use_spot, years, rate, False, use_q)

        call_vol = sum(r["volume"] for r in calls)
        put_vol = sum(r["volume"] for r in puts)
        call_oi = sum(r["open_interest"] for r in calls)
        put_oi = sum(r["open_interest"] for r in puts)

        # An at-the-money straddle prices in the move the market expects.
        atm_call = min(calls, key=lambda r: abs(r["strike"] - spot), default=None)
        s_atm_iv = atm_call["iv"] if atm_call else None
        atm_put = min(puts, key=lambda r: abs(r["strike"] - spot), default=None)
        straddle = None
        if atm_call and atm_put and atm_call["last"] and atm_put["last"]:
            straddle = round(atm_call["last"] + atm_put["last"], 2)

        unusual = sorted(
            [
                r for r in calls + puts
                if (r["vol_oi_ratio"] or 0) > 2 and r["volume"] > 200
            ],
            key=lambda r: r["vol_oi_ratio"],
            reverse=True,
        )[:8]

        # Say plainly which fields the vendor did not give us this run, so the
        # UI can grey out a tile instead of showing a confident zero.
        rows = calls + puts
        quality = {
            "quotes_live": any(r["bid"] or r["ask"] for r in rows),
            "open_interest_present": any(r["open_interest"] for r in rows),
            "iv_solved_pct": round(
                100 * sum(1 for r in rows if r["iv_source"] == "solved") / len(rows), 1
            )
            if rows else 0.0,
        }

        chains.append(
            {
                "expiry": expiry,
                "days_to_expiry": days,
                "trading_days": tdays,
                "calls": calls,
                "puts": puts,
                "stats": {
                    "call_volume": call_vol,
                    "put_volume": put_vol,
                    "put_call_volume_ratio": round(put_vol / call_vol, 3)
                    if call_vol else None,
                    "call_oi": call_oi,
                    "put_oi": put_oi,
                    "put_call_oi_ratio": round(put_oi / call_oi, 3) if call_oi else None,
                    "atm_iv": atm_call["iv"] if atm_call else None,
                    "max_pain": _max_pain(calls, puts),
                    "straddle_price": straddle,
                    "expected_move_pct": round((straddle / spot) * 100, 2)
                    if straddle and spot else None,
                },
                "unusual_activity": unusual,
                "data_quality": quality,
                "probability": probabilities(
                    spot, years, (s_atm_iv or 0) / 100.0, rate, div_yield
                ),
            }
        )

    return {
        "available": bool(chains),
        "spot": round(spot, 4) if spot else None,
        "risk_free_rate": round(rate, 5),
        "dividend_yield": round(div_yield, 5),
        "all_expiries": list(ticker.options or []),
        "expiries": chains,
    }
