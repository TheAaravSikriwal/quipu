"""Checking the numbers against something other than themselves.

Every figure this app prints is computed here rather than taken from a
vendor, which is the point of it -- and also the risk. A wrong formula does
not look wrong; it produces a confident number in the right font.

So each check below tests a value against an INDEPENDENT source of truth:
a published textbook figure, an identity that must hold regardless of
implementation, a second method that should converge on the first, or a
recomputation by a different route. Nothing here checks a function against
itself.

Run:  .venv/Scripts/python.exe -m backend.verify
"""

from __future__ import annotations

import math
import sys
import warnings
from pathlib import Path
from typing import Any, List, Tuple

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from sources import options as O  # noqa: E402

RESULTS: List[Tuple[bool, str, str]] = []


def check(name: str, got: Any, want: Any, tol: float = 1e-4, note: str = "") -> None:
    if isinstance(want, bool) or want is None:
        ok = (got == want)
        detail = f"{got!r}"
    else:
        ok = got is not None and abs(float(got) - float(want)) <= tol
        detail = f"got {float(got):.6f}  want {float(want):.6f}" if got is not None else "got None"
    RESULTS.append((ok, name, (detail + ("  " + note if note else "")).strip()))


def section(title: str) -> None:
    RESULTS.append((None, title, ""))


# ---------------------------------------------------------------- pricing
section("Black-Scholes against published values")

# Hull, *Options, Futures and Other Derivatives*, the standard worked
# example: S=100 K=100 T=1 r=5% sigma=20%, no dividend.
S, K, T, R, V = 100.0, 100.0, 1.0, 0.05, 0.20
call = O.bs_price(S, K, T, V, R, True)
put = O.bs_price(S, K, T, V, R, False)
check("call price", call, 10.450584, 1e-5)
check("put price", put, 5.573526, 1e-5)

g = O.greeks(S, K, T, V, R, True)
gp = O.greeks(S, K, T, V, R, False)
# greeks() rounds on the way out -- 4 decimals, 6 for gamma -- so the
# tolerance here is the rounding, not a fudge. Anything looser would stop
# these being tests; anything tighter tests the rounding rather than the
# formula.
ROUND4, ROUND6 = 5e-5, 5e-7
check("call delta", g["delta"], 0.636831, ROUND4)
check("put delta", gp["delta"], -0.363169, ROUND4)
check("gamma", g["gamma"], 0.018762, ROUND6)
# vega is reported per one volatility POINT, so the textbook 37.524 per unit
# of sigma becomes 0.37524 here. That scaling is a deliberate presentation
# choice and worth pinning down.
check("vega, per vol point", g["vega"], 0.375240, ROUND4)
check("theta, per day", g["theta"], -6.414028 / 365.0, ROUND4)
check("rho, per rate point", g["rho"], 0.532325, ROUND4)

section("Identities that must hold whatever the implementation")

# Put-call parity. If this fails the two branches disagree about the world.
lhs = call - put
rhs = S * math.exp(0.0) - K * math.exp(-R * T)
check("put-call parity", lhs, rhs, 1e-8)

# With a dividend yield the carry term must appear on the spot leg.
q = 0.03
cq = O.bs_price(S, K, T, V, R, True, q)
pq = O.bs_price(S, K, T, V, R, False, q)
check("parity with dividends", cq - pq,
      S * math.exp(-q * T) - K * math.exp(-R * T), 1e-8)

# Deltas of a call and a put on the same strike differ by the carry factor.
check("delta relationship",
      O.greeks(S, K, T, V, R, True, q)["delta"] - O.greeks(S, K, T, V, R, False, q)["delta"],
      math.exp(-q * T), 1e-4)

# Gamma and vega are identical for calls and puts.
check("gamma call == put", g["gamma"], gp["gamma"], 1e-12)
check("vega call == put", g["vega"], gp["vega"], 1e-12)

# Deep in the money, a call is worth its discounted intrinsic and no more.
deep = O.bs_price(200.0, 50.0, 1.0, 0.20, R, True)
check("deep ITM call ~ intrinsic", deep, 200.0 - 50.0 * math.exp(-R), 1e-3)

section("Greeks against numerical derivatives of the price")

# The strongest test available: differentiate the pricer itself and see
# whether the closed forms agree. If a sign or a term is wrong anywhere,
# these disagree immediately.
h = 1e-5
d_num = (O.bs_price(S + h, K, T, V, R, True) - O.bs_price(S - h, K, T, V, R, True)) / (2 * h)
check("delta vs numeric", g["delta"], d_num, ROUND4)

gm_num = (O.bs_price(S + h, K, T, V, R, True)
          - 2 * O.bs_price(S, K, T, V, R, True)
          + O.bs_price(S - h, K, T, V, R, True)) / (h * h)
check("gamma vs numeric", g["gamma"], gm_num, 1e-4)

hv = 1e-6
v_num = (O.bs_price(S, K, T, V + hv, R, True) - O.bs_price(S, K, T, V - hv, R, True)) / (2 * hv)
check("vega vs numeric", g["vega"], v_num / 100.0, ROUND4)

ht = 1e-6
t_num = -(O.bs_price(S, K, T + ht, V, R, True) - O.bs_price(S, K, T - ht, V, R, True)) / (2 * ht)
check("theta vs numeric", g["theta"], t_num / 365.0, ROUND4)

hr = 1e-6
r_num = (O.bs_price(S, K, T, V, R + hr, True) - O.bs_price(S, K, T, V, R - hr, True)) / (2 * hr)
check("rho vs numeric", g["rho"], r_num / 100.0, ROUND4)

section("Binomial tree converges on the closed form")

# A European option priced on a tree must approach Black-Scholes as the
# steps go up. This is the check that the up/down/probability triple is
# right -- a wrong p converges confidently to the wrong number.
for steps, tol in ((50, 5e-2), (500, 5e-3), (2000, 2e-3)):
    b = O.binomial(S, K, T, V, R, True, steps=steps)
    check(f"european, {steps} steps", b["european_price"], call, tol)

# An American call on a non-dividend payer is never worth exercising early,
# so it must equal the European. This is a theorem, not an approximation.
ba = O.binomial(S, K, T, V, R, True, div_yield=0.0, steps=500)
check("american call == european (no div)", ba["early_exercise_value"], 0.0, 1e-6)

# An American put IS worth exercising early, so it must be worth strictly
# more. If this comes out zero the early-exercise test is not running.
bp = O.binomial(S, K, T, V, R, False, steps=500)
RESULTS.append((bp["early_exercise_value"] > 0.01, "american put > european",
                f"early exercise worth {bp['early_exercise_value']:.4f}"))

section("Implied volatility solver round-trips")

for vol in (0.10, 0.25, 0.60, 1.20):
    for strike in (80.0, 100.0, 130.0):
        px = O.bs_price(S, strike, 0.5, vol, R, True)
        back = O.implied_vol(px, S, strike, 0.5, R, True)
        check(f"IV round trip  K={strike:.0f} sigma={vol:.2f}", back, vol, 1e-4)

# Nonsense in, nothing out -- a price below intrinsic has no implied vol and
# the solver must say so rather than return a boundary value.
RESULTS.append((O.implied_vol(0.001, 100.0, 50.0, 1.0, R, True) is None,
                "IV rejects sub-intrinsic price", "returns None"))

section("Probabilities")

pr = O.probabilities(S, T, V, R, 0.0)
# P(finishing above spot) is N(d2) with K = S. Computed here independently.
d2 = (math.log(S / S) + (R - 0.5 * V * V) * T) / (V * math.sqrt(T))
# p_above_spot is published to one decimal place.
check("P above spot == N(d2)", pr["p_above_spot"] / 100.0, O._norm_cdf(d2), 5e-4)

# The one-sigma band should hold about 68% of a lognormal's mass, which
# means the chance of finishing above the low edge minus above the high edge.
lo, hi = pr["one_sigma"]["low"], pr["one_sigma"]["high"]
RESULTS.append((lo < S < hi, "one-sigma band brackets spot", f"{lo:.2f} < {S} < {hi:.2f}"))
RESULTS.append((pr["two_sigma"]["low"] < lo and pr["two_sigma"]["high"] > hi,
                "two-sigma band is wider", "yes"))

# Touching a level must always be at least as likely as finishing past it.
bad = [r for r in pr["ladder"]
       if r["p_touch"] is not None and r["move_pct"] > 0
       and r["p_touch"] < r["p_finish_above"] - 1e-9]
RESULTS.append((not bad, "P(touch) >= P(finish) on the upside",
                "all rungs" if not bad else f"{len(bad)} rungs violate it"))

section("Trading-day clock")

from datetime import datetime, timezone  # noqa: E402

# A full calendar year holds about 252 trading days.
d = O.trading_days(datetime(2026, 1, 1, tzinfo=timezone.utc),
                   datetime(2027, 1, 1, tzinfo=timezone.utc))
RESULTS.append((248 <= d <= 254, "a year is ~252 sessions", f"{d} sessions"))
# Friday to Monday is one trading day, not three calendar ones.
fri = datetime(2026, 9, 18, tzinfo=timezone.utc)
mon = datetime(2026, 9, 21, tzinfo=timezone.utc)
check("Fri->Mon is 1 trading day", O.trading_days(fri, mon), 1, 0)

section("Screener metrics, recomputed by a different route")

try:
    import yfinance as yf
    from screener import scan as SC

    raw = yf.download(["AAPL", "MSFT"], period="2y", interval="1d",
                      auto_adjust=True, threads=True, progress=False)
    m = SC.measure(raw)
    close = raw["Close"]["AAPL"].dropna()

    # Annualised 20-day realised vol, by hand.
    lr = np.log(close / close.shift(1)).dropna()
    want_vol = lr.tail(20).std() * math.sqrt(252) * 100
    check("AAPL 20d realised vol", m.loc["AAPL", "vol20"], want_vol, 1e-6)

    # 12-1 momentum: the year to a month ago, skipping the last month.
    want_mom = (close.iloc[-22] / close.iloc[-253] - 1) * 100
    check("AAPL 12-1 momentum", m.loc["AAPL", "mom_12_1"], want_mom, 1e-6)

    # Distance from the 200-day.
    want_200 = (close.iloc[-1] / close.tail(200).mean() - 1) * 100
    check("AAPL vs 200-day", m.loc["AAPL", "from_200"], want_200, 1e-6)

    # Drawdown must be non-negative and no worse than the year's full fall.
    dd = m.loc["AAPL", "drawdown"]
    year = close.tail(252)
    RESULTS.append((0 <= dd <= 100 and dd >= (1 - year.iloc[-1] / year.max()) * 100 - 1e-6,
                    "AAPL drawdown is sane", f"{dd:.2f}%"))

    # R-squared is a proportion.
    r2 = m.loc["AAPL", "trend_r2"]
    RESULTS.append((0 <= r2 <= 1, "trend R^2 within [0,1]", f"{r2:.3f}"))
except Exception as exc:
    RESULTS.append((False, "screener metrics", f"could not run: {exc}"))

section("Series integrity (what the candles are drawn from)")

try:
    from sources import quotes as Q
    s = Q.fetch_series("AAPL")
    problems = []
    for rng in s.get("ranges", []):
        pts = s[rng]["points"]
        if len(pts) < 2:
            problems.append(f"{rng} empty")
            continue
        for p in pts:
            if not (p["l"] <= min(p["o"], p["c"]) + 1e-9
                    and p["h"] >= max(p["o"], p["c"]) - 1e-9
                    and p["h"] >= p["l"]):
                problems.append(f"{rng} {p['t']} OHLC inconsistent")
                break
            if any(p[k] != p[k] for k in "ohlc"):
                problems.append(f"{rng} {p['t']} NaN")
                break
    RESULTS.append((not problems, "every candle has high>=o,c>=low, no NaN",
                    "all ranges clean" if not problems else "; ".join(problems[:3])))

    # Reported change must agree with the first and last close it came from.
    r = s["6M"]
    want = (r["points"][-1]["c"] / r["points"][0]["c"] - 1) * 100
    check("6M change matches its own points", r["change_pct"], want, 0.01)
except Exception as exc:
    RESULTS.append((False, "series integrity", f"could not run: {exc}"))

section("Universe filter keeps what matters")

try:
    from screener import universe as U
    syms = set(U.symbols())
    must = ["AAPL", "MSFT", "NVDA", "SPY", "QQQ", "IWM", "BRK-B", "GOOGL", "TSLA"]
    missing = [m for m in must if m not in syms]
    RESULTS.append((not missing, "major names survive filtering",
                    "all present" if not missing else f"missing {missing}"))

    idx = U.index()
    geared = [s for s in ("TQQQ", "SQQQ", "SOXL", "UVXY") if s in syms]
    RESULTS.append((not geared, "geared products excluded by default",
                    "none present" if not geared else f"leaked {geared}"))
except Exception as exc:
    RESULTS.append((False, "universe filter", f"could not run: {exc}"))


section("Event calendar parses to what the publishers actually say")

try:
    import collections
    from datetime import date as _d
    from sources import events as EV

    # The Fed holds exactly eight regularly scheduled meetings a year, and
    # has for decades. It is the sharpest available check on the parser:
    # a year that comes back with seven means a month-straddling meeting
    # was dropped, and nine means a notation vote was counted as a rate
    # decision. Both were real bugs found by this check.
    meetings = EV._fomc()
    per_year = collections.Counter(r["date"][:4] for r in meetings)
    full = {y: n for y, n in per_year.items() if y not in (min(per_year), max(per_year))}
    wrong = {y: n for y, n in full.items() if n != 8}
    RESULTS.append((not wrong, "FOMC: eight scheduled meetings a year",
                    f"{len(full)} full years all correct" if not wrong else f"off: {wrong}"))

    weekend = [r["date"] for r in meetings if _d.fromisoformat(r["date"]).weekday() > 4]
    RESULTS.append((not weekend, "FOMC: no decision lands on a weekend",
                    "none" if not weekend else str(weekend[:3])))

    dupes = [d for d, n in collections.Counter(r["date"] for r in meetings).items() if n > 1]
    RESULTS.append((not dupes, "FOMC: no date parsed twice",
                    "none" if not dupes else str(dupes[:3])))

    # 1 February 2023 and 1 November 2023 are the two decisions that fell in
    # a different month from the one the meeting started in. If the parser
    # regresses on abbreviated month labels, these are the dates that vanish.
    got = {r["date"] for r in meetings}
    straddle = [d for d in ("2023-02-01", "2023-11-01") if d not in got]
    RESULTS.append((not straddle, "FOMC: month-straddling meetings kept",
                    "both present" if not straddle else f"lost {straddle}"))

    # The estimated releases are the only dates here Quipu made up, so they
    # are held to the rules they claim to follow.
    est = [e for e in EV._expected_bls(200) if not e["confirmed"]]
    jobs = [e for e in est if e["kind"] == "jobs"]
    bad = [e["date"] for e in jobs if _d.fromisoformat(e["date"]).weekday() != 4]
    RESULTS.append((not bad, "jobs estimate always lands on a Friday",
                    f"{len(jobs)} checked" if not bad else f"not Friday: {bad}"))

    cpi = [e for e in est if e["kind"] == "inflation"]
    out = [e["date"] for e in cpi if not 10 <= _d.fromisoformat(e["date"]).day <= 15]
    RESULTS.append((not out, "CPI estimate stays in its 10th-15th window",
                    f"{len(cpi)} checked" if not out else f"outside: {out}"))

    weekend2 = [e["date"] for e in est if _d.fromisoformat(e["date"]).weekday() > 4]
    RESULTS.append((not weekend2, "no estimated release on a weekend",
                    "none" if not weekend2 else str(weekend2[:3])))

    holiday = [e["date"] for e in est
               if _d.fromisoformat(e["date"]) in EV._holidays(_d.fromisoformat(e["date"]).year)]
    RESULTS.append((not holiday, "no estimated release on a market holiday",
                    "none" if not holiday else str(holiday[:3])))

    # An estimate must never sit next to the confirmed version of the same
    # release: CPI and PCE are both inflation, and keying the merge on the
    # subject rather than the release silently deleted the CPI estimate.
    merged = EV.upcoming(None, horizon=150)["events"]
    seen = collections.Counter((e["title"], e["date"][:7]) for e in merged)
    clash = [k for k, n in seen.items() if n > 1]
    RESULTS.append((not clash, "no release appears twice in one month",
                    f"{len(merged)} events" if not clash else str(clash[:3])))

    months = {e["date"][:7] for e in merged}
    cpi_months = {e["date"][:7] for e in merged if "CPI" in e["title"]}
    gap = sorted(months - cpi_months)[:-1]      # the final month is cut short
    RESULTS.append((not gap, "an inflation report in every whole month",
                    f"{len(cpi_months)} months" if not gap else f"missing {gap}"))

    # BEA publishes county-level GDP for the year before last under a
    # title containing "GDP". Flagging that as a market event told the
    # reader to expect a growth number that was not coming.
    skipped = EV._bea_row("GDP by County and Personal Income by County, 2025")
    RESULTS.append((skipped is None, "regional BEA detail is not an event",
                    "county GDP skipped" if skipped is None else f"kept as {skipped[0]}"))

    adv = EV._bea_row("GDP (Advance Estimate), 3rd Quarter 2026")
    RESULTS.append((adv is not None and adv[2] == 2,
                    "the GDP that moves markets is kept",
                    adv[0] if adv else "advance estimate dropped"))

    third = EV._bea_row("GDP (Third Estimate), Industries, 2nd Quarter 2026")
    RESULTS.append((third is not None and third[2] == 1,
                    "stale GDP revisions are down-weighted",
                    third[0] if third else "final estimate dropped"))

    order = [e["date"] for e in merged]
    RESULTS.append((order == sorted(order), "calendar comes back in date order",
                    "sorted" if order == sorted(order) else "out of order"))
except Exception as exc:
    RESULTS.append((False, "event calendar", f"could not run: {exc}"))

section("A setup says the contract it would actually buy")

try:
    import presets as PR

    # Half-dollar strikes are the norm near the money on a liquid name.
    # Printing them to the nearest whole dollar named a contract that does
    # not exist, under arithmetic that was entirely correct -- which is
    # what made it worth a permanent check rather than a one-line fix.
    strikes = [335, 337.5, 347.5, 12.25, 1250, 7.0, 0.5, 2.5]
    wrong = [v for v in strikes if float(PR._strike(v).replace(",", "")) != float(v)]
    RESULTS.append((not wrong, "printed strike parses back to the real one",
                    f"{len(strikes)} checked" if not wrong else f"wrong: {wrong}"))

    half = PR._strike(337.5)
    RESULTS.append((half == "337.5", "half-dollar strikes keep their half",
                    f'337.5 prints as "{half}"'))

    # The words a leg is described in must name the same strike the leg
    # carries, or the explanation and the ticket disagree.
    leg = {"kind": "put", "side": "short", "strike": 337.5, "qty": 1,
           "entry": 0.56, "expiry": "2026-09-23", "delta": -0.25}
    words = PR._leg_words(leg)
    RESULTS.append(("337.5" in words["text"], "leg description names its own strike",
                    words["text"]))

    # A short leg brings money in; a long leg sends it out. Getting this
    # backwards flips the cost of every spread on the page.
    # A per-share price is a number someone types into a ticket, so it
    # keeps its cents no matter how large it is.
    share = PR._leg_words({"kind": "stock", "side": "long", "strike": None,
                           "qty": 100, "entry": 341.2235, "expiry": None})
    RESULTS.append(("$341.22" in share["text"], "per-share prices keep their cents",
                    share["text"]))

    short_cash = PR._leg_words(leg)["cash"]
    long_cash = PR._leg_words(dict(leg, side="long"))["cash"]
    RESULTS.append((short_cash < 0 < long_cash, "selling credits, buying debits",
                    f"sell {short_cash}, buy {long_cash}"))
except Exception as exc:
    RESULTS.append((False, "setup descriptions", f"could not run: {exc}"))

section("Discrete dividends, priced the way the market pays them")

try:
    from datetime import datetime as _dt, timezone as _tz

    NOW = _dt(2026, 1, 2, tzinfo=_tz.utc)
    DIVS = [{"date": "2026-02-13", "amount": 0.50},
            {"date": "2026-05-15", "amount": 0.50},
            {"date": "2027-02-12", "amount": 0.50}]
    S0, R = 100.0, 0.04

    # Only the payments that fall before expiry come out of the spot.
    e1 = O.escrowed_spot(S0, DIVS, "2026-03-31", R, NOW)
    check("one dividend before a March expiry", len(e1["used"]), 1, 0)
    e2 = O.escrowed_spot(S0, DIVS, "2026-06-30", R, NOW)
    check("two before a June expiry", len(e2["used"]), 2, 0)
    e0 = O.escrowed_spot(S0, DIVS, "2026-01-30", R, NOW)
    check("none before a January expiry", len(e0["used"]), 0, 0)

    # The amount taken out is the present value, never the face value.
    t = O.trading_days(NOW, _dt(2026, 2, 13, tzinfo=_tz.utc)) / 252.0
    check("dividend is discounted, not just subtracted",
          e1["pv"], 0.50 * math.exp(-R * t), 1e-6)
    RESULTS.append((e1["pv"] < 0.50, "present value is below face value",
                    f'{e1["pv"]:.4f} < 0.50'))

    # Put-call parity under the escrowed model is an identity and must
    # hold to the penny: C - P = S_adj - K.e^(-rT). If this drifts, the
    # dividend is being counted twice somewhere, or not at all.
    T, VOL, K = 0.5, 0.25, 100.0
    sadj = O.escrowed_spot(S0, DIVS, "2026-06-30", R, NOW)["spot"]
    c = O.bs_price(sadj, K, T, VOL, R, True, 0.0)
    p_ = O.bs_price(sadj, K, T, VOL, R, False, 0.0)
    check("parity holds with discrete dividends",
          c - p_, sadj - K * math.exp(-R * T), 1e-9)

    # And the whole point: over a short window straddling an ex-date the
    # two models must NOT agree. A continuous yield spreads the payment
    # out; the market takes it all on the day.
    yld = (0.50 * 4) / S0
    short_T = 14 / 252
    cont = O.bs_price(S0 * math.exp(-yld * short_T), K, short_T, VOL, R, True, 0.0)
    disc = O.bs_price(O.escrowed_spot(S0, DIVS, "2026-01-22", R, NOW)["spot"],
                      K, short_T, VOL, R, True, 0.0)
    RESULTS.append((abs(cont - disc) > 0.05,
                    "the two dividend models differ across an ex-date",
                    f"continuous {cont:.3f} vs escrowed {disc:.3f}"))

    # A company with no dividend history must price identically either
    # way -- the new path cannot move a non-payer.
    plain = O.escrowed_spot(S0, [], "2026-06-30", R, NOW)
    check("no dividends means no adjustment", plain["spot"], S0, 1e-12)
except Exception as exc:
    RESULTS.append((False, "discrete dividends", f"could not run: {exc}"))

section("Filed accounts agree with the filings")

try:
    from sources import sec_edgar as SE, sec_xbrl as SX

    facts = SX.fetch("AAPL", SE.lookup_cik)
    RESULTS.append((facts.get("available"), "Apple's XBRL facts load",
                    facts.get("entity") or facts.get("reason", "")))
    rows = {r["end"]: r for r in facts.get("annual", [])}

    # Apple's FY2024 as printed on the cover of the 10-K. An outside
    # number, not something this code can talk itself into.
    fy24 = rows.get("2024-09-28", {})
    check("AAPL FY2024 revenue", fy24.get("revenue"), 391_035_000_000, 1)
    check("AAPL FY2024 net income", fy24.get("net_income"), 93_736_000_000, 1)

    # The accounting identity. Assets = liabilities + equity is true by
    # construction in a filed balance sheet, so if it fails here the
    # three figures have been read off different periods or filings.
    bad = []
    for end, r in rows.items():
        a, l, e = r.get("assets"), r.get("liabilities"), r.get("equity")
        if a and l and e and abs(a - (l + e)) / a > 0.005:
            bad.append(end)
    RESULTS.append((not bad, "assets = liabilities + equity",
                    f"{len(rows)} years balance" if not bad else f"off in {bad}"))

    # Margins are computed here, so they must reproduce by hand.
    r = rows.get("2024-09-28", {})
    if r.get("revenue") and r.get("net_income"):
        check("net margin recomputes", r["net_margin"],
              r["net_income"] / r["revenue"], 1e-9)

    # Revenue cannot be smaller than the profit left after costs.
    upside_down = [end for end, r in rows.items()
                   if r.get("gross_profit") and r.get("revenue")
                   and r["gross_profit"] > r["revenue"]]
    RESULTS.append((not upside_down, "gross profit never exceeds revenue",
                    "consistent" if not upside_down else str(upside_down)))

    # Restatements collapse: one row per period end, never two.
    ends = [r["end"] for r in facts.get("annual", [])]
    RESULTS.append((len(ends) == len(set(ends)), "one row per fiscal year",
                    f"{len(ends)} years, no repeats"))

    # A REIT stops tagging rent as contract revenue when the lease
    # standard changes. Preferring the tag by list order alone gave
    # Realty Income a 2018 income statement and $1.3bn of revenue
    # against an actual $5.5bn, which is the kind of wrong that looks
    # entirely plausible on screen.
    o = SX.fetch("O", SE.lookup_cik)
    latest = (o.get("annual") or [{}])[-1].get("end", "")
    RESULTS.append((latest >= "2023", "a REIT reports its recent years",
                    f"latest annual period {latest or 'none'}"))
except Exception as exc:
    RESULTS.append((False, "filed accounts", f"could not run: {exc}"))

section("No dict literal quietly overwrites itself")

# A patch once inserted a new "events" key next to the old one instead of
# replacing it. Python keeps the last and says nothing, so the endpoint
# went on calling the previous version of the function -- the payload
# looked complete, the new field it was supposed to carry was simply
# never there. Nothing else in the suite would have caught it.
try:
    import ast as _ast
    import collections as _c
    import os as _os

    dupes = []
    root = Path(__file__).resolve().parent.parent
    for folder, dirs, files in _os.walk(root):
        dirs[:] = [d for d in dirs
                   if d not in (".venv", "__pycache__", ".git", "node_modules", "cache")]
        for name in files:
            if not name.endswith(".py"):
                continue
            path = _os.path.join(folder, name)
            try:
                tree = _ast.parse(open(path, encoding="utf-8").read())
            except (OSError, SyntaxError):
                continue
            for node in _ast.walk(tree):
                if not isinstance(node, _ast.Dict):
                    continue
                keys = [k.value for k in node.keys
                        if isinstance(k, _ast.Constant) and isinstance(k.value, str)]
                for key, n in _c.Counter(keys).items():
                    if n > 1:
                        dupes.append(f"{name}:{node.lineno} {key!r}")
    RESULTS.append((not dupes, "no repeated keys in a dict literal",
                    "clean" if not dupes else ", ".join(dupes[:3])))
except Exception as exc:
    RESULTS.append((False, "duplicate key scan", f"could not run: {exc}"))

section("Source files carry no corrupted escapes")

# A patch once wrote literal backspace bytes where a regex word boundary
# was meant. The pattern still compiled, still looked correct in an
# editor, and matched nothing -- which silently emptied a whole section
# of the calendar. Cheap to check, invisible otherwise.
try:
    import os as _os

    found = []
    for root, dirs, files in _os.walk(Path(__file__).resolve().parent.parent):
        dirs[:] = [d for d in dirs
                   if d not in (".venv", "__pycache__", ".git", "node_modules", "cache")]
        for name in files:
            if not name.endswith((".py", ".js", ".css", ".html")):
                continue
            path = _os.path.join(root, name)
            try:
                raw = open(path, "rb").read()
            except OSError:
                continue
            for code in (0x07, 0x08, 0x0B, 0x0C, 0x1B):
                if bytes([code]) in raw:
                    found.append(f"{name}:{hex(code)}")
    RESULTS.append((not found, "no stray control bytes in source",
                    "clean" if not found else ", ".join(sorted(set(found))[:4])))
except Exception as exc:
    RESULTS.append((False, "control byte scan", f"could not run: {exc}"))

# ------------------------------------------------------------------ report
if __name__ == "__main__":
    passed = failed = 0
    for ok, name, detail in RESULTS:
        if ok is None:
            print(f"\n{name}\n{'-' * len(name)}")
            continue
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name:<42} {detail}")
        passed += ok
        failed += not ok
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
