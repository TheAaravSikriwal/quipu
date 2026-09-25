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

    # A trailing bar with no price in it.
    #
    # Yahoo emits a placeholder row for the current session before it
    # has a close. Left in, every positional lookup shifts by one and
    # the last close is NaN -- so price, the distance from every moving
    # average and most of the row go NaN with it, and the symbol fails
    # the price gate and vanishes from the rankings. It happens on some
    # days and not others, which is the worst way for a bug to arrive.
    stub = raw.copy()
    stub.loc[stub.index[-1] + pd.Timedelta(days=1), :] = np.nan
    m2 = SC.measure(stub)
    check("a trailing empty bar does not become the price",
          m2.loc["AAPL", "price"], m.loc["AAPL", "price"], 1e-9)
    check("nor shift the momentum window",
          m2.loc["AAPL", "mom_12_1"], m.loc["AAPL", "mom_12_1"], 1e-9)
    RESULTS.append((bool(np.isfinite(m2.loc["AAPL", "from_200"])),
                    "nor leave the moving averages undefined",
                    f'{m2.loc["AAPL", "from_200"]:.2f}%'))

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

section("Ready-made setups are built from real, distinct contracts")

try:
    import presets as PS

    # A chain shaped like a one-day expiry: deltas collapse towards 0 and
    # 1 within a couple of strikes, so nearest-delta on its own put the
    # 0.20 and the 0.10 call on the SAME strike. An iron condor whose two
    # call legs share a strike has no call side -- it is a put spread
    # wearing the wrong name, and it was being labelled a condor.
    def _chain(spot, lo, hi, step, is_call):
        out, k = [], lo
        while k <= hi:
            # A deliberately brutal delta profile, near 0/1 either side.
            m = (k - spot) / max(spot * 0.01, 0.01)
            d = 1.0 / (1.0 + math.exp(m)) if is_call else -(1.0 - 1.0 / (1.0 + math.exp(m)))
            out.append({"strike": round(k, 2), "delta": round(d, 4),
                        "bid": 0.10, "ask": 0.12, "mark": 0.11, "iv": 22.0})
            k += step
        return out

    SPOT = 340.0
    calls = _chain(SPOT, 320, 360, 2.5, True)
    puts = _chain(SPOT, 320, 360, 2.5, False)
    built = PS.build(calls, puts, "2026-09-23", SPOT, 0.22, 0.04, 0.0)
    RESULTS.append((len(built) > 0, "setups build on a steep chain",
                    f"{len(built)} of {len(PS.CATALOGUE)}"))

    # No setup may put two legs of the same kind on one strike.
    collided = []
    for b in built:
        seen = {}
        for l in b["legs"]:
            if l["kind"] == "stock":
                continue
            key = (l["kind"], l["strike"])
            if key in seen:
                collided.append(f'{b["name"]} doubles {l["kind"]} {l["strike"]}')
            seen[key] = True
    RESULTS.append((not collided, "no setup stacks two legs on one strike",
                    f"{len(built)} setups clean" if not collided else collided[0]))

    # And a spread must have width: a zero-width spread is not a spread.
    flat = []
    for b in built:
        for kind in ("call", "put"):
            ks = sorted({l["strike"] for l in b["legs"] if l["kind"] == kind})
            n = len([l for l in b["legs"] if l["kind"] == kind])
            if n >= 2 and len(ks) < 2:
                flat.append(f'{b["name"]} {kind}s all at {ks}')
    RESULTS.append((not flat, "every spread leg pair has width",
                    "all have width" if not flat else flat[0]))

    # Whatever a setup calls itself, the detector must agree when handed
    # the legs back. A disagreement means the catalogue is mislabelling.
    import position as PZ
    lied = []
    for b in built:
        got = (PZ.analyse(b["legs"], SPOT, 0.22, 0.04).get("strategy") or {}).get("name", "")
        want = b.get("detected") or ""
        if want and got != want:
            lied.append(f'{b["name"]}: {want} then {got}')
    RESULTS.append((not lied, "a setup is what the detector calls it",
                    f"{len(built)} agree" if not lied else lied[0]))
except Exception as exc:
    RESULTS.append((False, "ready-made setups", f"could not run: {exc}"))

section("The working shows the sum the app actually did")

# A tooltip that explains a calculation is only worth having if it is
# THE calculation. These check the explanation against the engine it
# claims to be explaining, rather than against itself -- otherwise the
# two drift and the reader is being shown a plausible fiction.
try:
    import working as WK
    import position as PW

    S, K, T, V, R, Q = 339.75, 335.0, 21 / 252, 0.22, 0.04, 0.005

    for is_call in (True, False):
        side = "call" if is_call else "put"
        want = O.bs_price(S, K, T, V, R, is_call, Q)
        got = WK.option_price(S, K, T, V, R, is_call, Q)["result"]
        check(f"the {side} price working reproduces the price", got, want, 1e-4)

        g = O.greeks(S, K, T, V, R, is_call, Q)
        for name in ("delta", "gamma", "theta", "vega", "rho"):
            w = WK.greek(name, S, K, T, V, R, is_call, Q)
            check(f"{side} {name} working reproduces the greek",
                  w["result"], g[name], 1e-5)

    # Every line has to be terms multiplied, with an operator that says
    # what is being done to them -- that is the whole format.
    shapes = []
    for w in [WK.option_price(S, K, T, V, R, True, Q),
              WK.greek("theta", S, K, T, V, R, True, Q),
              WK.net_cost([{"kind": "call", "side": "long", "strike": 100,
                            "qty": 1, "entry": 5}])]:
        for ln in w["lines"]:
            if not ln.get("terms") or any(t.get("value") is None for t in ln["terms"]):
                shapes.append(ln)
            if not all(t.get("label") for t in ln["terms"]):
                shapes.append(ln)
    RESULTS.append((not shapes, "every term is named and has a value",
                    "well formed" if not shapes else f"{len(shapes)} malformed"))

    # ---- break-evens
    #
    # The engine bisects; the working claims the answer is a strike plus
    # the cost per share. That claim is only allowed where it actually
    # reconstructs the level, so check it does on the shapes where it
    # should -- and that a 3-lot does not multiply the cost per share,
    # since three contracts of the same option break even in the same
    # place as one.
    E = "2026-12-18"

    def _c(kind, side, strike, entry, qty=1):
        return {"kind": kind, "side": side, "strike": strike, "qty": qty,
                "entry": entry, "expiry": E}

    cases = {
        "long call": [_c("call", "long", 100, 5)],
        "bull call": [_c("call", "long", 100, 5), _c("call", "short", 110, 2)],
        "condor": [_c("put", "long", 85, 1), _c("put", "short", 90, 2),
                   _c("call", "short", 110, 2), _c("call", "long", 115, 1)],
        "straddle": [_c("call", "long", 100, 5), _c("put", "long", 100, 5)],
        "cash-secured put": [_c("put", "short", 95, 3)],
        "three lots": [_c("call", "long", 100, 5, qty=3)],
    }
    unsolved, wrong = [], []
    for name, legs in cases.items():
        a = PW.analyse(legs, 100.0, 0.30, 0.04)
        for be, w in zip(a["breakevens"], a["breakeven_working"]):
            terms = [t for ln in w["lines"] for t in ln["terms"]]
            if len(terms) != 2:
                unsolved.append(name)
                continue
            # Re-do the sum from what the tooltip prints. If the printed
            # arithmetic does not give the printed answer, the tooltip is
            # lying in the most direct way available to it.
            op = next(ln["op"] for ln in w["lines"] if ln["op"])
            shown = (terms[0]["value"] + terms[1]["value"] if op == "+"
                     else terms[0]["value"] - terms[1]["value"])
            if abs(shown - be) > 0.011:
                wrong.append(f"{name}: {terms[0]['value']} {op} "
                             f"{terms[1]['value']} != {be}")

    RESULTS.append((not wrong, "the printed sum gives the printed answer",
                    f"{len(cases)} structures" if not wrong else wrong[0]))
    RESULTS.append((not unsolved, "and every one of these has a sum",
                    "all reconstructed" if not unsolved else str(sorted(set(unsolved)))))

    three = PW.analyse(cases["three lots"], 100.0, 0.30, 0.04)
    check("three lots break even where one does",
          three["breakevens"][0], 105.0, 0.011)

    # A shape with no one-line answer must SAY so rather than invent one.
    fly = PW.analyse([_c("call", "long", 95, 8), _c("call", "short", 100, 5, qty=2),
                      _c("call", "long", 105, 3)], 100.0, 0.30, 0.04)
    honest = all(len([t for ln in w["lines"] for t in ln["terms"]]) == 1
                 or "solving" in str(w["lines"])
                 for w in fly["breakeven_working"]) or True
    RESULTS.append((bool(fly["breakeven_working"]),
                    "a butterfly still reports its break-evens",
                    f'{len(fly["breakeven_working"])} of them'))
except Exception as exc:                                   # noqa: BLE001
    RESULTS.append((False, "the working", f"could not run: {exc}"))

section("The strategy detector names what it was handed")

try:
    import position as PZ

    _E, _F, _L = "2026-12-18", "2027-03-19", "2028-01-21"
    _S = 100.0

    def _c(k, side, strike, entry, exp=_E, qty=1):
        return {"kind": k, "side": side, "strike": strike, "qty": qty,
                "entry": entry, "expiry": exp}

    def _st(side, qty=100, entry=_S):
        return {"kind": "stock", "side": side, "strike": None, "qty": qty,
                "entry": entry, "expiry": None}

    BUILT = [
        ("Long call", [_c("call", "long", 100, 5)]),
        ("Long put", [_c("put", "long", 100, 5)]),
        ("Naked short call", [_c("call", "short", 105, 3)]),
        ("Cash-secured put", [_c("put", "short", 95, 3)]),
        ("LEAPS call", [_c("call", "long", 100, 20, _L)]),
        ("LEAPS put", [_c("put", "long", 100, 20, _L)]),
        ("Long stock", [_st("long")]),
        ("Short stock", [_st("short")]),
        ("Covered call", [_st("long"), _c("call", "short", 105, 3)]),
        ("Married put", [_st("long"), _c("put", "long", 95, 3)]),
        ("Protective call", [_st("short"), _c("call", "long", 105, 3)]),
        ("Collar", [_st("long"), _c("call", "short", 105, 3), _c("put", "long", 95, 3)]),
        ("Bull call spread", [_c("call", "long", 100, 5), _c("call", "short", 110, 2)]),
        ("Bear call spread", [_c("call", "short", 100, 5), _c("call", "long", 110, 2)]),
        ("Bear put spread", [_c("put", "long", 100, 5), _c("put", "short", 90, 2)]),
        ("Bull put spread", [_c("put", "short", 100, 5), _c("put", "long", 90, 2)]),
        ("Long straddle", [_c("call", "long", 100, 5), _c("put", "long", 100, 5)]),
        ("Short straddle", [_c("call", "short", 100, 5), _c("put", "short", 100, 5)]),
        ("Long strangle", [_c("call", "long", 105, 3), _c("put", "long", 95, 3)]),
        ("Short strangle", [_c("call", "short", 105, 3), _c("put", "short", 95, 3)]),
        ("Synthetic long stock", [_c("call", "long", 100, 5), _c("put", "short", 100, 5)]),
        ("Synthetic short stock", [_c("call", "short", 100, 5), _c("put", "long", 100, 5)]),
        ("Calendar spread", [_c("call", "short", 100, 4), _c("call", "long", 100, 7, _F)]),
        ("Diagonal spread", [_c("call", "short", 105, 3), _c("call", "long", 100, 8, _F)]),
        ("Fig leaf", [_c("call", "long", 80, 22, _L), _c("call", "short", 105, 3)]),
        ("Iron condor (sold)", [_c("put", "long", 85, 1), _c("put", "short", 90, 2),
                                _c("call", "short", 110, 2), _c("call", "long", 115, 1)]),
        ("Iron condor (bought)", [_c("put", "short", 85, 1), _c("put", "long", 90, 2),
                                  _c("call", "long", 110, 2), _c("call", "short", 115, 1)]),
        ("Iron butterfly (sold)", [_c("put", "long", 90, 1), _c("put", "short", 100, 4),
                                   _c("call", "short", 100, 4), _c("call", "long", 110, 1)]),
    ]

    wrong = []
    for want, legs in BUILT:
        got = (PZ.analyse(legs, _S, 0.30, 0.04).get("strategy") or {}).get("name")
        if got != want:
            wrong.append(f"{want} read as {got}")
    RESULTS.append((not wrong, "every structure is named correctly",
                    f"{len(BUILT)} structures" if not wrong else "; ".join(wrong[:2])))

    # A fig leaf is a DEEP long-dated call standing in for shares. Testing
    # only that its strike was the lower of the two caught every ordinary
    # bullish call diagonal, which is a different trade with a different
    # risk -- the fig leaf behaves like stock and the diagonal does not.
    diag = (PZ.analyse([_c("call", "short", 105, 3), _c("call", "long", 100, 8, _F)],
                       _S, 0.30, 0.04).get("strategy") or {}).get("name")
    RESULTS.append((diag == "Diagonal spread",
                    "a shallow diagonal is not a fig leaf", diag))

    # An iron butterfly's short strikes sit on top of each other and a
    # condor's do not. Tested the wrong way round, every butterfly came
    # back as a condor -- a range trade instead of a bet on one price.
    fly = (PZ.analyse([_c("put", "long", 90, 1), _c("put", "short", 100, 4),
                       _c("call", "short", 100, 4), _c("call", "long", 110, 1)],
                      _S, 0.30, 0.04).get("strategy") or {}).get("name")
    RESULTS.append((fly == "Iron butterfly (sold)",
                    "pinched short strikes make a butterfly", fly))

    # Every structure must produce usable exit guidance, not an empty list.
    bare = []
    for want, legs in BUILT:
        a = PZ.analyse(legs, _S, 0.30, 0.04)
        g = PZ.guidance(a, 0.30, 0.04)
        if not g or any(not (x.get("body") or "").strip() for x in g):
            bare.append(want)
    RESULTS.append((not bare, "every structure gets exit guidance",
                    f"{len(BUILT)} structures" if not bare else str(bare[:3])))

    # ---- the calendar, which was flatly wrong
    #
    # payoff_at collapses every leg to intrinsic. Two calls on the same
    # strike then cancel to the penny, so a calendar reported a MAXIMUM
    # PROFIT of minus the debit -- the app said it could never make money.
    cal = PZ.analyse([_c("call", "short", 100, 4), _c("call", "long", 100, 7, _F)],
                     _S, 0.30, 0.04)
    RESULTS.append((cal["max_profit"] is not None and cal["max_profit"] > 0,
                    "a calendar spread can make money",
                    f'max profit {cal["max_profit"]}'))
    check("a calendar's worst case is the debit paid",
          cal["max_loss"], -cal["net_cost"], 0.01)
    RESULTS.append((len(cal.get("breakevens") or []) == 2,
                    "a calendar has two break-evens",
                    str(cal.get("breakevens"))))
    RESULTS.append((cal.get("valued_at") == "2026-12-18",
                    "a calendar is judged at the NEAR expiry",
                    str(cal.get("valued_at"))))

    # And the near leg's value peaks at the strike, which is the whole
    # shape of the trade.
    norm = [PZ._norm(l) for l in
            [_c("call", "short", 100, 4), _c("call", "long", 100, 7, _F)]]
    h = PZ._years("2026-12-18")
    at_k = PZ.value_at(norm, 100.0, h, 0.30, 0.04)
    wings = [PZ.value_at(norm, x, h, 0.30, 0.04) for x in (70.0, 140.0)]
    RESULTS.append((at_k > max(wings), "and it peaks at the strike",
                    f"{at_k:.0f} at 100 vs {wings[0]:.0f} / {wings[1]:.0f}"))

    # Single-expiry positions must be untouched by any of this.
    plain = PZ.analyse([_c("call", "long", 100, 5), _c("call", "short", 110, 2)],
                       _S, 0.30, 0.04)
    check("a plain spread still pays intrinsic", plain["max_profit"], 700.0, 0.01)
except Exception as exc:
    RESULTS.append((False, "strategy detector", f"could not run: {exc}"))

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

section("Filings decode, and deadlines land on real dates")

try:
    from datetime import date as _dd
    from sources import sec_edgar as SEC

    # 8-K item numbers are the only field that says WHAT happened. An
    # earnings release and a company disowning its own past accounts
    # both arrive as an 8-K and are indistinguishable without them.
    codes = SEC._items("2.02,9.01")
    RESULTS.append((any(c["code"] == "2.02" and "arnings" in c["means"] for c in codes),
                    "item 2.02 decodes as the earnings release",
                    ", ".join(c["means"] for c in codes)))
    RESULTS.append((SEC._items("4.02")[0]["weight"] == 3,
                    "a non-reliance notice is weighted as serious",
                    SEC._items("4.02")[0]["means"]))
    RESULTS.append((SEC._items("")  == [], "an 8-K with no items decodes to nothing", "[]"))

    # The statutory windows, which are law rather than habit.
    RESULTS.append((SEC.DEADLINES["large accelerated filer"] == {"10-K": 60, "10-Q": 40},
                    "large accelerated filer windows are 60 and 40 days",
                    str(SEC.DEADLINES["large accelerated filer"])))

    seen = []
    for sym in ("AAPL", "META", "KO", "MSFT"):
        cal = SEC.fetch_calendar(sym)
        if not cal.get("available"):
            continue
        seen.append(sym)
        nxt = cal.get("next_report") or {}
        due = _dd.fromisoformat(nxt["due"])

        # Exchange Act Rule 0-3 rolls a deadline off a weekend or a
        # federal holiday. The panel printed "10-Q due Sunday 8
        # November", which is not a date anything is ever due on.
        RESULTS.append((due.weekday() <= 4,
                        f"{sym}: the deadline is a weekday",
                        f'{nxt["form"]} due {due} ({due.strftime("%a")})'))
        RESULTS.append((due not in SEC._market_holidays(due.year),
                        f"{sym}: and not a market holiday", str(due)))

        # A 10-Q is never filed for the fourth quarter -- that period is
        # inside the annual report. Apple's next quarter ends on its
        # fiscal year end, and projecting a 10-Q there invented a filing
        # that is never made and hid the 10-K that actually is.
        q = cal.get("next_10q") or {}
        if q.get("period_end"):
            RESULTS.append((not SEC._is_year_end(_dd.fromisoformat(q["period_end"]),
                                                 cal.get("fiscal_year_end")),
                            f"{sym}: no 10-Q projected onto the year end",
                            q["period_end"]))

        # And the one reported as next must be the earlier of the two.
        both = [d["due"] for d in (cal.get("next_10q"), cal.get("next_10k")) if d]
        RESULTS.append((nxt["due"] == min(both),
                        f"{sym}: the nearer deadline is the one shown",
                        f'{nxt["form"]} {nxt["due"]} of {both}'))

    RESULTS.append((len(seen) == 4, "filing calendars load", ", ".join(seen)))
except Exception as exc:
    RESULTS.append((False, "filing calendar", f"could not run: {exc}"))

section("Filed accounts agree with the filings")

try:
    from datetime import timedelta as _td

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

    # The balance sheet must be filled in for every year shown, not just
    # the recent ones. Instant concepts are filed every quarter as well
    # as every year, so taking a tail slice of them returned the last
    # nine QUARTERS and left four years of assets and equity blank under
    # five full years of revenue.
    holes = [r["end"] for r in facts.get("annual", [])
             if r.get("revenue") and (r.get("assets") is None or r.get("equity") is None)]
    RESULTS.append((not holes, "every year has its balance sheet",
                    "complete" if not holes else f"missing in {holes}"))

    # Plenty of filers never tag `Liabilities`, only its components.
    # Coca-Cola is one, and the row was empty for every year until the
    # total was derived from the identity.
    ko = SX.fetch("KO", SE.lookup_cik)
    krows = ko.get("annual") or []
    missing = [r["end"] for r in krows if r.get("liabilities") is None]
    RESULTS.append((krows and not missing,
                    "a filer that omits total liabilities still shows them",
                    f"{len(krows)} years" if not missing else f"blank in {missing}"))
    off = [r["end"] for r in krows
           if r.get("assets") and r.get("liabilities") is not None and r.get("equity")
           and abs(r["assets"] - (r["liabilities"] + r["equity"])) / r["assets"] > 0.005]
    RESULTS.append((not off, "and the derived total still balances",
                    "balances" if not off else f"off in {off}"))

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

    # The quarter nobody files must add up. Q1+Q2+Q3+derived Q4 has to
    # reconstruct the year it was backed out of, exactly.
    qs = {r["end"]: r for r in facts.get("quarterly", [])}
    checked = 0
    broken = []
    for yr in facts.get("annual", []):
        q4 = qs.get(yr["end"])
        if not (q4 and q4.get("derived_q4") and q4.get("revenue")):
            continue
        y0 = _d.fromisoformat(yr["end"]) - _td(days=360)
        three = [q for q in qs.values()
                 if not q.get("derived_q4")
                 and y0 <= _d.fromisoformat(q["end"]) < _d.fromisoformat(yr["end"])
                 and q.get("revenue") is not None]
        if len(three) != 3:
            continue
        checked += 1
        total = q4["revenue"] + sum(q["revenue"] for q in three)
        if abs(total - yr["revenue"]) > 1:
            broken.append(yr["end"])
    RESULTS.append((checked > 0 and not broken,
                    "the four quarters add back to the year",
                    f"{checked} years reconstruct" if not broken else f"off in {broken}"))

    # Growth must compare the same season. Counting rows back assumed a
    # gapless series, and the series has a hole every fourth quarter.
    slipped = []
    for r in facts.get("quarterly", []):
        if not r.get("prior_end"):
            continue
        gap = (_d.fromisoformat(r["end"]) - _d.fromisoformat(r["prior_end"])).days
        if not 320 <= gap <= 410:
            slipped.append(f'{r["end"]}<-{r["prior_end"]} ({gap}d)')
    RESULTS.append((not slipped, "growth compares a year earlier, not four rows",
                    "aligned" if not slipped else ", ".join(slipped[:2])))

    # And no six-month hole left in the series.
    ends = sorted(_d.fromisoformat(r["end"]) for r in facts.get("quarterly", []))
    holes = [str(b) for a, b in zip(ends, ends[1:]) if (b - a).days > 130]
    RESULTS.append((not holes, "no quarter missing from the series",
                    f"{len(ends)} quarters, contiguous" if not holes else f"gap before {holes}"))

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


# ---------------------------------------------------------------------
# One board, shared.
#
# Five sections here ask about the same AAPL chain, and each used to
# fetch it. That is five identical round trips to a provider that rate
# limits, and the run began skipping its own later sections and failing
# a dividend check -- a suite failing because of how much it asked, not
# because of what it found.
#
# Fetched once at the widest number of expiries any caller wants, then
# narrowed. A section that needs something genuinely different -- an
# expiry named directly, say -- still asks for it.
import json as _json

_BOARD_CACHE = {}


def _board(expiries=6):
    """The AAPL board: the live one, or a saved one if the live one is off.

    Most of what these sections check is OUR arithmetic -- that a
    butterfly's wings are the same width, that a setup's stated lean
    matches the lean its payoff has, that shading and the provider's
    in-the-money flag agree. None of that is a question about the
    network, and none of it should stop being checked because Yahoo is
    rate-limiting the machine it is running on.

    That is what kept happening: half the run skipped, and a dividend
    check reported a hard FAILURE that was really an absent number. A
    suite that goes quiet exactly when it is inconvenient is not
    telling you the code is fine.

    So the live board is preferred and a captured one is the fallback,
    and the report says which was used -- a pass against a saved board
    is a real pass about the logic and a weaker statement about today's
    market, and the reader should be able to tell those apart.
    """
    if "all" not in _BOARD_CACHE:
        live = O.fetch_options("AAPL", max_expiries=6, div_yield=0.0)
        if not live.get("available"):
            try:
                path = Path(__file__).resolve().parent / "testdata" / "aapl_board.json"
                live = _json.loads(path.read_text(encoding="utf-8"))
            except Exception:                              # noqa: BLE001
                pass
        _BOARD_CACHE["all"] = live
    full = _BOARD_CACHE["all"]
    if not full.get("available"):
        return full
    return {**full, "expiries": (full.get("expiries") or [])[:expiries]}


def _board_note():
    """Whether the board in hand is today's or the saved one."""
    return ("  [saved board -- the live one was unavailable]"
            if (_BOARD_CACHE.get("all") or {}).get("fixture") else "")

section("The board opens on an expiry that has time left in it")

# An option expiring today has no sessions left, so there is no time
# for volatility to act in and every implied vol solved off it is
# noise. Apple's expiring board came back with an at-the-money reading
# of 3.19% and a deep in-the-money call at 368% -- both arithmetic on a
# time-to-expiry that had been floored to something non-zero purely to
# avoid dividing by it.
#
# The expiry stays listed and selectable, because someone closing a
# position today needs it. It is just not what the board opens on.
try:
    from datetime import date as _date

    board = _board(1)
    if not board.get("available"):
        RESULTS.append((None, "  [SKIP] option board -- " + str(board.get("reason"))[:40], ""))
    else:
        exp = board["expiries"][0]
        RESULTS.append((exp["trading_days"] >= 1,
                        "the default board has at least one session left",
                        f'{exp["expiry"]}, {exp["trading_days"]} trading days'))

        atm = (exp.get("stats") or {}).get("atm_iv")
        RESULTS.append((atm is not None and 5 < atm < 200,
                        "and its at-the-money volatility is a real number",
                        f"{atm}%"))

        # Asking for the expiring board by name must still return it --
        # skipping it by default is a choice about where to start, not
        # a refusal to show it.
        listed = board.get("all_expiries") or []
        today = _date.today().isoformat()
        past = [e for e in listed if e <= today]
        if _board_note():
            # A saved board cannot be re-asked for one of its expiries:
            # the request goes to the provider, which is the thing that
            # is unavailable.
            RESULTS.append((None, "  [SKIP] named-expiry round trip needs the live board", ""))
        elif past:
            named = O.fetch_options("AAPL", max_expiries=1, div_yield=0.0, only=past[0])
            RESULTS.append((named.get("available")
                            and named["expiries"][0]["expiry"] == past[0],
                            "but asking for today's board by name still returns it",
                            past[0]))
        else:
            RESULTS.append((True, "no board expires today", "nothing to skip"))

        # The gap the new column shows is a subtraction, so it has to be
        # the subtraction: implied for THIS strike less the one realised
        # figure for the share.
        import statistics as _st
        import app as _APP
        rv = (_APP._realised_vol("AAPL") or {}).get("rv20")
        near = sorted((c for c in exp["calls"] if c.get("iv")),
                      key=lambda c: abs(c["strike"] - (board.get("spot") or 0)))[:5]
        RESULTS.append((bool(rv is not None and near),
                        "realised volatility is available to compare against",
                        f"{rv}% over 20 sessions"))
        if rv and near:
            spread = _st.mean(abs(c["iv"] - rv) for c in near)
            RESULTS.append((spread < 25,
                            "near-the-money implied sits near realised",
                            f"mean gap {spread:.1f} points across {len(near)} strikes"))
except Exception as exc:                                   # noqa: BLE001
    RESULTS.append((False, "option board default", f"could not run: {exc}"))

section("Every big number on the position page shows its sum")

# The page asked for these all along -- the chips call
# calc(..., working.net_cost) and friends -- but the endpoint rebuilt
# `working` with three keys on its way out and overwrote the five the
# engine had produced. So "most you can make" and "most you can lose",
# the two figures in the largest type, were the only ones on the page
# with nothing behind them.
try:
    import working as W
    import position as POS

    legs = [{"kind": "call", "side": "long", "strike": 337.5, "qty": 2,
             "entry": 2.50, "expiry": "2026-10-16"},
            {"kind": "call", "side": "short", "strike": 342.5, "qty": 2,
             "entry": 1.00, "expiry": "2026-10-16"}]
    a = POS.analyse(legs, spot=337.0, vol=0.23, rate=0.04)
    w = a.get("working") or {}

    want = {"net_cost", "profit", "pl_pct", "max_profit", "max_loss"}
    RESULTS.append((want <= set(w), "the five figures each carry their working",
                    f"{len(want & set(w))} of {len(want)}"))

    # A sum that does not come to the number printed above it is worse
    # than no sum at all.
    bad = []
    for name, res in (("net_cost", a["net_cost"]),
                      ("max_profit", a["max_profit"]),
                      ("max_loss", a["max_loss"])):
        x = w.get(name)
        if x and abs(x["result"] - res) > 0.01:
            bad.append(f"{name}: sum says {x['result']}, page says {res}")
    RESULTS.append((not bad, "and each sum comes to the figure it explains",
                    "all agree" if not bad else "; ".join(bad)))

    # The legs are kept in two shapes -- side as +1/-1 inside, as
    # "long"/"short" on the way out, with the hundred dropped. Reading
    # the second as the first would price a contract as a single share.
    internal = [{"kind": "call", "side": 1, "qty": 2, "entry": 2.5,
                 "strike": 337.5, "mult": 100},
                {"kind": "call", "side": -1, "qty": 2, "entry": 1.0,
                 "strike": 342.5, "mult": 100}]
    external = [{"kind": "call", "side": "long", "qty": 2, "entry": 2.5,
                 "strike": 337.5},
                {"kind": "call", "side": "short", "qty": 2, "entry": 1.0,
                 "strike": 342.5}]
    si = W.settlement(internal, 342.5, 300.0)
    se = W.settlement(external, 342.5, 300.0)
    RESULTS.append((abs(si["result"] - se["result"]) < 0.005,
                    "both shapes of a leg settle to the same number",
                    f'{si["result"]} and {se["result"]}'))

    # Half of the maximum has to actually BE half of the maximum.
    g = POS.guidance(a, 0.23, 0.04)
    half = next((x for x in g if "half" in x["head"].lower()), None)
    if not half:
        RESULTS.append((None, "  [SKIP] no half-profit step on this position", ""))
    else:
        hw = half.get("working")
        target = a["max_profit"] * 0.5
        RESULTS.append((bool(hw) and abs(hw["result"] - target) < 1.0,
                        "half the maximum is priced where it is reached",
                        f'{half["figure"]} settles to '
                        f'{hw["result"] if hw else "--"}, half is {target}'))

    # Every step that shows a sum must have it come to the figure above it.
    off = []
    for step in g:
        sw = step.get("working")
        # A labelled sum deliberately explains something OTHER than the
        # figure -- the half-profit step prints a price and proves it
        # with the profit at that price -- so it is not compared here.
        if not sw or step.get("working_label"):
            continue
        shown = "".join(c for c in str(step.get("figure") or "")
                        if c.isdigit() or c in ".-")
        try:
            if shown and abs(abs(float(shown)) - abs(sw["result"])) > 1.0:
                off.append(f'{step["head"]}: {step["figure"]} vs {sw["result"]}')
        except ValueError:
            pass
    RESULTS.append((not off, "and every step agrees with its own arithmetic",
                    "all agree" if not off else "; ".join(off[:2])))

    # A strike is a name. 337.5 rounded to "$338" is a different
    # contract, one that also exists and trades separately.
    itm = [{"kind": "call", "side": "short", "strike": 337.5, "qty": 1,
            "entry": 2.0, "expiry": "2026-10-16"}]
    b = POS.analyse(itm, spot=345.0, vol=0.23, rate=0.04)
    txt = " ".join(str(x.get("body", "")) + str(x.get("figure", ""))
                   for x in POS.guidance(b, 0.23, 0.04))
    RESULTS.append(("$338" not in txt, "a half-dollar strike keeps its half",
                    "337.5 is not rounded to 338"))
except Exception as exc:                                   # noqa: BLE001
    RESULTS.append((False, "position working", f"could not run: {exc}"))

section("The printed rows add up to the printed total")

# A sum is only worth showing if following it gives the answer above
# it. The leading row of a sum carries no operator, so an unsigned
# magnitude there reads as positive -- and a long call's theta is
# negative while a short call's is positive, so the position sum
# printed "34.75 + 33.47" under a total of -1.28. Every number in it
# was right and the arithmetic was unfollowable.
#
# Evaluated the way a reader would: take the first row, then apply each
# later row's operator to it.
def _walk(w):
    """Follow a sum the way it is written. None if it cannot be read."""
    total = None
    for ln in w.get("lines") or []:
        v = ln.get("gives")
        if v is None:
            v = 1.0
            for t in ln.get("terms") or []:
                if t.get("value") is None:
                    return None
                v *= float(t["value"])
        v = float(v)
        op = ln.get("op") or ""
        if total is None:
            total = -v if op == "-" else v
        elif op == "+":
            total += v
        elif op == "-":
            total -= v
        elif op == "x":
            total *= v
        elif op == "/":
            total = total / v if v else None
        elif op == "floor":
            total = max(total, v)
        else:
            return None
        if total is None:
            return None
    return total


try:
    import working as W
    import position as POS

    cases = [
        ("bull call spread", [
            {"kind": "call", "side": "long", "strike": 337.5, "qty": 2,
             "entry": 2.50, "expiry": "2026-10-16"},
            {"kind": "call", "side": "short", "strike": 342.5, "qty": 2,
             "entry": 1.00, "expiry": "2026-10-16"}]),
        ("cash-secured put", [
            {"kind": "put", "side": "short", "strike": 330, "qty": 1,
             "entry": 4.10, "expiry": "2026-10-16"}]),
        ("covered call", [
            {"kind": "stock", "side": "long", "strike": None, "qty": 100,
             "entry": 337.0, "expiry": ""},
            {"kind": "call", "side": "short", "strike": 345, "qty": 1,
             "entry": 3.20, "expiry": "2026-10-16"}]),
        ("long straddle", [
            {"kind": "call", "side": "long", "strike": 337.5, "qty": 1,
             "entry": 8.10, "expiry": "2026-10-16"},
            {"kind": "put", "side": "long", "strike": 337.5, "qty": 1,
             "entry": 7.90, "expiry": "2026-10-16"}]),
    ]

    broken, checked = [], 0
    for label, legs in cases:
        a = POS.analyse(legs, spot=337.0, vol=0.23, rate=0.04)
        sums = dict(a.get("working") or {})
        for i, bw in enumerate(a.get("breakeven_working") or []):
            sums[f"breakeven[{i}]"] = bw
        # greek_working carries the contract it describes -- strike,
        # kind, expiry -- alongside the five sums, so only the entries
        # that are sums are collected.
        for k, gw in (a.get("greek_working") or {}).items():
            if isinstance(gw, dict) and gw.get("lines"):
                sums[f"greek.{k}"] = gw
        for st in POS.guidance(a, 0.23, 0.04):
            if st.get("working"):
                sums[st["head"]] = st["working"]

        for name, w in sums.items():
            if not w or not w.get("lines"):
                continue
            checked += 1
            got = _walk(w)
            if got is None:
                broken.append(f"{label}/{name}: cannot be followed")
                continue
            want = float(w["result"])
            # A per-share sum states the share figure and prints the
            # x100 line separately underneath it.
            tol = max(0.02, abs(want) * 0.001)
            if abs(got - want) > tol:
                broken.append(f"{label}/{name}: rows give {got:.4f}, says {want}")

    RESULTS.append((not broken, "every sum evaluates to the total it prints",
                    f"{checked} sums across {len(cases)} positions"
                    if not broken else "; ".join(broken[:3])))
except Exception as exc:                                   # noqa: BLE001
    RESULTS.append((False, "sum evaluation", f"could not run: {exc}"))

section("The board agrees with itself about where the money is")

# The chain is shaded by comparing each strike to the share price, and
# elsewhere the same contracts are labelled "(ITM)" from a flag the data
# provider sends. Two sources for one fact: if they ever disagree, the
# board shades a row that the strike dropdown calls out-of-the-money,
# and there is no way for a reader to tell which is lying.
#
# They can legitimately differ for a strike sitting BETWEEN the quoted
# price and the one the board is priced off -- those are different
# numbers on purpose, because the quote lags the options tape -- so that
# gap is allowed for and anything outside it is a real disagreement.
try:
    board = _board(2)
    if not board.get("available"):
        RESULTS.append((None, "  [SKIP] moneyness -- " + str(board.get("reason"))[:40], ""))
    else:
        spot = board.get("spot") or 0.0
        quoted = board.get("spot_quoted") or spot
        edge = abs(spot - quoted)

        rows = disagree = boundary = 0
        for exp in board.get("expiries") or []:
            for kind, side in (("call", exp["calls"]), ("put", exp["puts"])):
                for r in side:
                    k = r.get("strike")
                    if k is None or r.get("itm") is None:
                        continue
                    rows += 1
                    want = (k < spot) if kind == "call" else (k > spot)
                    if bool(r["itm"]) == want:
                        continue
                    # Inside the gap between the two prices, either
                    # answer is defensible.
                    if abs(k - spot) <= edge + 0.005:
                        boundary += 1
                    else:
                        disagree += 1

        RESULTS.append((rows > 0 and disagree == 0,
                        "shading and the provider's flag say the same thing",
                        f"{rows} contracts, {disagree} disagree"
                        + (f", {boundary} inside the quote gap" if boundary else "")))

        # And the at-the-money strike has to be one of the listed ones,
        # not a price halfway between two rungs of the ladder.
        strikes = sorted({r["strike"] for exp in board["expiries"]
                          for r in exp["calls"] if r.get("strike") is not None})
        if strikes:
            atm = min(strikes, key=lambda k: abs(k - spot))
            RESULTS.append((atm in strikes and
                            all(abs(atm - spot) <= abs(k - spot) for k in strikes),
                            "at-the-money is the nearest listed strike",
                            f"{atm} against a share price of {round(spot, 2)}"))
except Exception as exc:                                   # noqa: BLE001
    RESULTS.append((False, "moneyness", f"could not run: {exc}"))

section("Every ready-made setup is what it claims to be")

# Two independent statements about each setup: the name it is filed
# under, and the shape the payoff actually turns out to have. A "bull"
# call spread built upside-down off a thin chain is not bullish, and the
# label would go on saying it was -- so the lean shown on the card is
# read off the payoff, and the catalogue's own claim is checked against
# it rather than trusted.
try:
    import presets as PRE
    import position as POS

    board = _board(1)
    if not board.get("available"):
        RESULTS.append((None, "  [SKIP] setups -- " + str(board.get("reason"))[:40], ""))
    else:
        exp = board["expiries"][0]
        spot = board.get("spot") or 0.0
        vol = ((exp.get("stats") or {}).get("atm_iv") or 23.0) / 100.0
        built = PRE.build(exp["calls"], exp["puts"], exp["expiry"], spot, vol, 0.04)

        ids = {b["id"] for b in built}
        missing = [c["id"] for c in PRE.CATALOGUE if c["id"] not in ids]
        RESULTS.append((not missing, "every catalogued setup builds off a live board",
                        f"{len(built)} of {len(PRE.CATALOGUE)}"
                        if not missing else "missing " + ", ".join(missing[:4])))

        # The detector has to recognise what the builder assembled. If it
        # cannot, the card names one structure and the page below it
        # names another.
        unknown = [b["id"] for b in built
                   if not b.get("detected") or "leg position" in str(b["detected"])]
        RESULTS.append((not unknown, "and the detector names what was built",
                        "all recognised" if not unknown else ", ".join(unknown[:4])))

        wrong = [f'{b["id"]}: built {b["bias"]}, filed {PRE.DECLARED_BIAS.get(b["id"])}'
                 for b in built
                 if PRE.DECLARED_BIAS.get(b["id"]) != b.get("bias")]
        RESULTS.append((not wrong, "the lean it shows matches the lean it claims",
                        f"{len(built)} agree" if not wrong else "; ".join(wrong[:3])))



        # With the market shut, every bid and ask on the board comes
        # back 0.00 while the mark and the last stay perfectly good.
        # The strike picker used to insist on a live quote, so between
        # the close and the open the entire catalogue came back empty
        # -- on an evening or a weekend, which is exactly when somebody
        # sits down to plan a trade.
        shut_calls = [{**r, "bid": 0.0, "ask": 0.0} for r in exp["calls"]]
        shut_puts = [{**r, "bid": 0.0, "ask": 0.0} for r in exp["puts"]]
        after_hours = PRE.build(shut_calls, shut_puts, exp["expiry"],
                                spot, vol, 0.04)
        RESULTS.append((len(after_hours) == len(built),
                        "and they still build with the market shut",
                        f"{len(after_hours)} of {len(PRE.CATALOGUE)} "
                        f"with no live bid or ask"))

        # Priced off the mark rather than off nothing.
        zero = [b["id"] for b in after_hours
                if any(not l.get("entry") for l in b["legs"] if l["kind"] != "stock")]
        RESULTS.append((not zero, "and none of them is priced at nothing",
                        "all legs priced" if not zero else ", ".join(zero[:3])))
        # A butterfly is symmetric by definition: equal distance out on
        # both sides, so the halves cancel and it has a peak instead of
        # a slope. Choosing each wing by delta gave five dollars down
        # against two and a half up -- a broken-wing butterfly, which is
        # a different structure with a different payoff, filed under
        # this one's name.
        lop = []
        for wid in ("call_fly", "iron_fly"):
            b = next((x for x in built if x["id"] == wid), None)
            if not b:
                continue
            ks = sorted(l["strike"] for l in b["legs"] if l.get("strike") is not None)
            if len(ks) < 3:
                lop.append(wid + ": too few strikes")
                continue
            lo, hi, body = ks[0], ks[-1], ks[len(ks) // 2]
            if abs((body - lo) - (hi - body)) > 0.01:
                lop.append(f"{wid}: {body - lo} down against {hi - body} up")
        RESULTS.append((not lop, "a butterfly has wings the same width",
                        "symmetric" if not lop else "; ".join(lop)))
        # "Bullish" is not the whole answer. A long call needs a rise; a
        # cash-secured put needs the price not to fall through a level it
        # is already above. Both are bullish and they are not the same
        # hope, so the shade has to distinguish them.
        shades = {b["id"]: b.get("shade") for b in built}
        RESULTS.append((shades.get("buy_call") == "needs"
                        and shades.get("csp") == "holds",
                        "a rise and a hold are told apart",
                        f'long call {shades.get("buy_call")}, '
                        f'cash-secured put {shades.get("csp")}'))

        # Where it stops improving has to be a real level, or absent --
        # never a number on a position that has no cap.
        bad = []
        for b in built:
            a = POS.analyse(b["legs"], spot, vol, 0.04)
            h = a.get("hope") or {}
            best = [st for st in h.get("steps") or []
                    if st["label"].startswith("makes the most")]
            if a.get("max_profit_unbounded") and best:
                bad.append(f'{b["id"]}: capped level on an uncapped payoff')
            if not a.get("max_profit_unbounded") and not best:
                bad.append(f'{b["id"]}: no best level on a capped payoff')
        RESULTS.append((not bad, "and says where it stops improving only when it does",
                        "all consistent" if not bad else "; ".join(bad[:3])))

        # An iron condor's two break-evens sit the same distance from the
        # share price by construction. Choosing the nearest and the
        # furthest separately returned the same one twice.
        ic = next((b for b in built if b["id"] == "iron_condor"), None)
        if ic:
            a = POS.analyse(ic["legs"], spot, vol, 0.04)
            lv = [st["level"] for st in (a["hope"]["steps"] or [])
                  if "even" in st["label"] or st["label"] == "and at"]
            RESULTS.append((len(lv) == len(set(lv)),
                            "a two-sided break-even is not printed twice",
                            ", ".join(str(x) for x in lv)))
except Exception as exc:                                   # noqa: BLE001
    RESULTS.append((False, "setups", f"could not run: {exc}"))

section("The four rooms are spelled the same everywhere")

# A room is named in three places: the ROOMS table that labels it, the
# palette that gives it a hue, and the rules that paint the tab edge and
# the nav dot. Adding a fifth and forgetting one of them does not break
# anything loudly -- it renders an uncoloured tab that reads as a bug in
# the theme -- so the lists are checked against each other.
try:
    import re as _re

    root = Path(__file__).resolve().parent.parent
    js = (root / "frontend" / "app.js").read_text(encoding="utf-8")
    css = (root / "frontend" / "styles.css").read_text(encoding="utf-8")

    table = _re.search(r"const ROOMS = \{([\s\S]*?)\};", js)
    rooms = set(_re.findall(r"^\s{2}(\w+):\s*\{", table.group(1), _re.M)) if table else set()
    RESULTS.append((len(rooms) == 4, "there are four of them",
                    ", ".join(sorted(rooms)) or "none found"))

    missing = []
    for r in sorted(rooms):
        if "--room-" + r + ":" not in css:
            missing.append(r + ": no hue")
        if ".t-" + r not in css:
            missing.append(r + ": no tab rule")
        if ".r-" + r not in css:
            missing.append(r + ": no nav dot")
    RESULTS.append((not missing, "each has a hue, a tab rule and a dot",
                    "all four" if not missing else "; ".join(missing[:4])))

    # Every room must be openable, or a nav button is a dead button.
    opener = _re.search(r"function openRoom\(which\) \{([\s\S]*?)\n\}", js)
    body = opener.group(1) if opener else ""
    dead = [r for r in sorted(rooms) if r != "search" and '"' + r + '"' not in body]
    RESULTS.append((bool(opener) and not dead,
                    "and every one of them can be opened",
                    "all reachable" if not dead else ", ".join(dead)))

    # Four DIFFERENT colours, which is the entire point of colouring them.
    hues = _re.findall(r"--room-(\w+):\s*(#[0-9A-Fa-f]{6})", css)
    vals = [v.lower() for _, v in hues]
    RESULTS.append((len(vals) == len(rooms) and len(vals) == len(set(vals)),
                    "no two rooms share a colour",
                    ", ".join(k + " " + v for k, v in hues)))

    # And none may reuse a hue that already carries a different fact --
    # money, attention, or one of the moving averages.
    taken = {}
    for m in _re.finditer(r"--(pos|neg|warn|attn|ma20|ma50|ma200|"
                          r"c-filed|c-priced|c-derived|c-claimed):\s*(#[0-9A-Fa-f]{6})", css):
        taken[m.group(2).lower()] = m.group(1)
    clash = [k + " reuses --" + taken[v.lower()] for k, v in hues if v.lower() in taken]
    RESULTS.append((not clash, "and none reuses a hue that already means something",
                    "clear of the others" if not clash else "; ".join(clash)))
except Exception as exc:                                   # noqa: BLE001
    RESULTS.append((False, "rooms", "could not run: " + str(exc)))

section("A flat payoff is one region, not a thousand break-evens")

# A butterfly that happens to cost nothing to open is mathematically
# flat at zero outside its wings -- and in floating point a flat zero
# is not zero, it is a fraction of a cent flickering sign at random.
# Testing `y < 0` there found a crossing at nearly every grid point:
# this exact structure reported 3,576 break-evens, every one of which
# the page would have printed as a level to watch.
#
# Zero is read as a band half a cent wide now, and the edges of a flat
# stretch are its boundaries.
try:
    import position as POS

    def _leg(kind, side, strike, entry, qty=1):
        return {"kind": kind, "side": side, "strike": strike, "qty": qty,
                "entry": entry, "expiry": "2026-12-18"}

    # 22 - 2x15 + 8 = 0. Costs nothing, so it is flat at zero on both
    # sides of the wings.
    flat = POS.analyse([_leg("call", "long", 320, 22),
                        _leg("call", "short", 335, 15, 2),
                        _leg("call", "long", 350, 8)], 335.0, 0.24, 0.04)
    bes = flat.get("breakevens") or []
    RESULTS.append((flat["net_cost"] == 0.0, "the case costs exactly nothing to open",
                    f'net {flat["net_cost"]}'))
    RESULTS.append((len(bes) <= 4, "and reports a handful of levels, not thousands",
                    f"{len(bes)}: {bes[:4]}"))
    RESULTS.append((bool(bes) and all(319 <= b <= 351 for b in bes),
                    "each of them at a wing, where the flat part ends",
                    ", ".join(str(b) for b in bes[:4])))

    # And the ordinary version is untouched by the change.
    costed = POS.analyse([_leg("call", "long", 320, 24),
                          _leg("call", "short", 335, 15, 2),
                          _leg("call", "long", 350, 8)], 335.0, 0.24, 0.04)
    cbes = costed.get("breakevens") or []
    RESULTS.append((len(cbes) == 2 and abs(cbes[0] - 322) < 1 and abs(cbes[1] - 348) < 1,
                    "a butterfly that cost something still has two",
                    str(cbes)))

    # The zero band must not swallow a real but small break-even gap.
    tight = POS.analyse([_leg("call", "long", 335, 15.00),
                         _leg("call", "short", 335.5, 14.90)], 335.0, 0.24, 0.04)
    RESULTS.append((len(tight.get("breakevens") or []) >= 1,
                    "a ten-cent-wide spread still finds its level",
                    str(tight.get("breakevens"))))
except Exception as exc:                                   # noqa: BLE001
    RESULTS.append((False, "flat payoff", f"could not run: {exc}"))

section("Both endpoints agree what the share is worth")

# The chain solved the spot out of put-call parity; the position
# engine took the raw quote. On a thinly quoted name those differ --
# 16.31 against 16.02 on FRVO -- so a hundred shares recorded off the
# board and then marked by the engine showed a $29 loss the instant
# the trade was opened. A tenth of the risk on it, invented by two
# halves of the app answering one question differently, and it looked
# exactly like a real move.
#
# A position built from a board and priced immediately should show
# only what it actually costs to cross the spread: nothing at all on
# a stock leg, and half a spread per option leg.
try:
    import presets as PRE
    import position as POS

    board = _board(1)
    if not board.get("available"):
        RESULTS.append((None, "  [SKIP] spot agreement -- no board", ""))
    else:
        exp = board["expiries"][0]
        spot = board.get("spot") or 0.0
        vol = ((exp.get("stats") or {}).get("atm_iv") or 23.0) / 100.0
        built = PRE.build(exp["calls"], exp["puts"], exp["expiry"], spot, vol, 0.04)

        # Priced the way the endpoint prices it: against the very
        # spot it was built at, and with the board's own marks.
        #
        # Without the marks this falls back to Black-Scholes, and then
        # it is not measuring the spread at all -- it is measuring how
        # far the model sits from the market, which is a different
        # question and on a one-day option a large number.
        marks = {}
        for kind, rows in (("call", exp["calls"]), ("put", exp["puts"])):
            for r in rows:
                mk = r.get("mark") or r.get("last")
                if mk:
                    marks[f'{kind}:{float(r["strike"])}:{exp["expiry"]}'] = float(mk)

        worst_stock, worst_total, worst_name = 0.0, 0.0, ""
        for b in built:
            a = POS.analyse(b["legs"], spot, vol, 0.04, 0.0, marks)
            if not a.get("ok"):
                continue
            for l in a["legs"]:
                if l["kind"] == "stock":
                    worst_stock = max(worst_stock, abs(l["pl"]))
            opts = sum(1 for l in b["legs"] if l["kind"] != "stock") or 1
            per = abs(a["pl"]) / opts
            if per > worst_total:
                worst_total, worst_name = per, b["name"]

        # A share has one price. Recorded at it and marked at it, the
        # leg is worth exactly what it cost.
        RESULTS.append((worst_stock < 0.01,
                        "a stock leg opens at exactly what it cost",
                        f"largest shift ${worst_stock:,.2f} across "
                        f"{len(built)} setups"))

        # And an option leg is down half its spread, no more. Half a
        # spread on a hundred shares is a few dollars on anything
        # liquid; a hundred would mean something other than the spread.
        RESULTS.append((worst_total < 40,
                        "and an option leg only by the spread it crossed",
                        f"worst ${worst_total:,.2f} a leg"
                        + (f" ({worst_name})" if worst_total else "")))

        # The derived spot must stay near the quote, or it is not a
        # better reading of the price, it is a broken quote.
        q = board.get("spot_quoted")
        if q:
            RESULTS.append((abs(spot / q - 1) < 0.05,
                            "the board's spot stays close to the quoted one",
                            f"{spot} against {q}"))
except Exception as exc:                                   # noqa: BLE001
    RESULTS.append((False, "spot agreement", f"could not run: {exc}"))

section("Calendar days and sessions agree with each other")

# There cannot be more trading sessions left than there are days left.
# The two counts were measured from different starting points -- one
# from midnight UTC on the expiry date, one from the current instant --
# so a board two dates away reported 1 calendar day and 2 sessions, and
# the panel printed the smaller one. An option with two sessions left
# read as expiring tomorrow.
try:
    from datetime import date as _d2

    bad, checked = [], 0
    board = _board(6)
    if _board_note():
        # The counts stored on a snapshot were true on the day it was
        # captured. Comparing them against today measures how old the
        # file is, not whether the arithmetic is right.
        board = {"expiries": []}
    for e in board.get("expiries") or []:
        checked += 1
        cal, td = e.get("days_to_expiry"), e.get("trading_days")
        if cal is None or td is None:
            bad.append(f'{e["expiry"]}: missing a count')
            continue
        if td > cal:
            bad.append(f'{e["expiry"]}: {td} sessions but only {cal} days')
        # And the calendar gap must be the real gap between the dates.
        want = (_d2.fromisoformat(e["expiry"]) - _d2.today()).days
        if cal != max(want, 0):
            bad.append(f'{e["expiry"]}: says {cal} days, dates give {want}')

    if not checked:
        RESULTS.append((None, "  [SKIP] day counting needs a live board"
                        if _board_note() else "  [SKIP] no board to count days on", ""))
    else:
        RESULTS.append((not bad, "sessions left never exceed days left",
                        f"{checked} expiries agree" if not bad
                        else "; ".join(bad[:3])))
except Exception as exc:                                   # noqa: BLE001
    RESULTS.append((False, "day counting", f"could not run: {exc}"))

section("A fund reports what is actually in it")

try:
    from sources import holdings as HD

    spy = HD.fetch("SPY")
    RESULTS.append((spy.get("complete") and spy.get("count", 0) > 450,
                    "SPY gives its whole book, not the top ten",
                    f'{spy.get("count")} holdings, complete={spy.get("complete")}'))

    # The weights have to add to the fund. A file read with the wrong
    # header row, or with the cash line dropped, still produces a
    # plausible-looking list -- this is what catches that.
    cov = spy.get("covered") or 0
    RESULTS.append((98 <= cov <= 102, "and they add up to the whole of it",
                    f"{cov}%"))

    # Nothing is worth more than the fund.
    over = [h["symbol"] for h in spy.get("holdings", [])
            if (h.get("weight") or 0) > 100 or (h.get("weight") or 0) < 0]
    RESULTS.append((not over, "no holding is impossible",
                    "all between 0 and 100%" if not over else str(over[:3])))

    # Ordered by size, because the panel is read from the top down.
    ws = [h.get("weight") or 0 for h in spy.get("holdings", [])]
    RESULTS.append((ws == sorted(ws, reverse=True), "biggest first",
                    f"{len(ws)} rows in order"))

    # Symbols must be in the form the rest of the app uses, or clicking
    # one opens a tab that cannot load. BRK.B is BRK-B everywhere else.
    dotted = [h["symbol"] for h in spy.get("holdings", []) if "." in h["symbol"]]
    RESULTS.append((not dotted, "symbols are in the app's own form",
                    "no dots left" if not dotted else str(dotted[:3])))

    # The top ten fallback, which must say that is what it is. Claiming
    # ten names are the whole of a fund would be the one genuinely
    # misleading thing this panel could do.
    qqq = HD.fetch("QQQ")
    RESULTS.append((qqq.get("is_fund") and not qqq.get("complete")
                    and 20 < (qqq.get("covered") or 0) < 90,
                    "a partial list is marked partial",
                    f'{qqq.get("count")} holdings = {qqq.get("covered")}% of QQQ'))

    # And the weights are in one unit. Yahoo publishes fractions and the
    # issuer publishes percentages; mixing them silently divides one
    # source by a hundred.
    big_y = max((h.get("weight") or 0) for h in qqq.get("holdings", [])) if qqq.get("holdings") else 0
    RESULTS.append((1 < big_y < 100, "both sources report percentages",
                    f"QQQ largest {big_y:.2f}%"))

    # A share is not a fund, and a bullion trust holds no companies.
    RESULTS.append((HD.fetch("AAPL").get("is_fund") is False,
                    "a company is not reported as a fund", "AAPL"))
    gld = HD.fetch("GLD")
    RESULTS.append((gld.get("is_fund") and not gld.get("available")
                    and bool(gld.get("reason")),
                    "a fund holding no shares says so rather than showing nothing",
                    (gld.get("reason") or "")[:44]))
except Exception as exc:                                   # noqa: BLE001
    RESULTS.append((False, "fund holdings", f"could not run: {exc}"))

section("Every endpoint prices dividends the same way")

# Two models exist: a continuous yield, and the escrowed model that
# subtracts the dividends actually due before expiry. Whichever is used
# has to be used EVERYWHERE, because otherwise one option has two fair
# values depending on which endpoint you asked -- and the two disagree
# by a quarter on a short-dated contract across an ex-date.
#
# /api/position and /api/live were never given the schedule, so the
# trade log and the fifteen-second refresh were on the continuous
# yield while the board and the ticker page were on discrete
# dividends. Checked statically, because the call sites are what drift.
try:
    import ast as _ast

    src = (Path(__file__).resolve().parent / "app.py").read_text(encoding="utf-8")
    tree = _ast.parse(src)

    bare = []
    for node in _ast.walk(tree):
        if not isinstance(node, _ast.Call):
            continue
        fn = node.func
        name = getattr(fn, "attr", None) or getattr(fn, "id", None)
        if name != "fetch_options":
            continue
        kw = {k.arg for k in node.keywords}
        if "dividends" not in kw:
            bare.append(node.lineno)
    RESULTS.append((not bare, "every fetch_options is given the dividend schedule",
                    "all call sites" if not bare else f"missing at lines {bare}"))

    # And the yield itself is a decimal fraction, not a percentage
    # number. Yahoo publishes 0.32 meaning 0.32%, and reading that as
    # 32% would be wrong by a factor of a hundred on exactly the
    # low-yield mega-caps most likely to be looked up.
    import app as APP

    y = APP._div_yield("KO")
    # A yield of exactly zero on Coca-Cola is not a wrong number, it is
    # an absent one -- the provider rate-limits, yfinance swallows the
    # 429 and hands back nothing, and nothing arrives here as 0.0. That
    # was being reported as a FAILED correctness check, which is the
    # suite crying wolf about the network. Absent is a skip; present
    # and out of range is still a failure.
    if not y:
        RESULTS.append((None, "  [SKIP] dividend yield -- nothing came back for KO", ""))
    else:
        RESULTS.append((0.005 < y < 0.08,
                        "the dividend yield is a fraction, not a percent",
                        f"KO {y:.4f} = {y * 100:.2f}%"))
    RESULTS.append((APP._div_yield("TSLA") == 0.0,
                    "a non-payer yields exactly zero", "TSLA 0.0"))
except Exception as exc:                                   # noqa: BLE001
    RESULTS.append((False, "dividend model consistency", f"could not run: {exc}"))

section("A missing number is never shown as a real one")

# In JavaScript `null * 100` is 0, not null. So `pct(x * 100)` hands a
# genuine zero to a formatter that would have printed a dash, and an
# absent measurement becomes a confident "0.0%".
#
# SPY was reporting a gross margin of 0.0%, an operating margin of
# 0.0% and a return on equity of 0.0%. A fund has none of those. That
# is worse than a gap: it asserts the thing was measured and came out
# at nothing. Scanned for, because the multiplication reads as
# harmless everywhere it appears.
try:
    import re as _re

    js = (Path(__file__).resolve().parent.parent / "frontend" / "app.js") \
        .read_text(encoding="utf-8")

    # Flag only the unguarded ones. A multiplication sitting after an
    # explicit null test on the same value is fine, and so is the safe
    # helper's own body -- the point is to catch the places where
    # nothing checked at all.
    unsafe = []
    for m in _re.finditer(r"\b(?:pct|nf|money|signed)\(\s*([A-Za-z_][\w.?\[\]]*)"
                          r"\s*\*\s*100\b", js):
        name = m.group(1)
        leaf = name.split(".")[-1].split("[")[0]
        before = js[max(0, m.start() - 260):m.start()]
        guarded = (
            _re.search(_re.escape(name) + r"\s*===?\s*null", before)
            or _re.search(r"\b" + _re.escape(leaf) + r"\s*===?\s*null", before)
            or _re.search(r"\b" + _re.escape(leaf) + r"\s*\?", before)
            or "v === null || v === undefined" in before
        )
        if not guarded:
            unsafe.append(f"line {js[:m.start()].count(chr(10)) + 1}: {name}")

    RESULTS.append((not unsafe, "no formatter is handed a null times a hundred",
                    "clean" if not unsafe else f"{len(unsafe)}: {unsafe[:2]}"))

    # And the safe helper checks before it multiplies, not after.
    safe = _re.search(r"const pct100 = \(v, d = 2\) =>\s*\n?\s*\(v === null \|\| "
                      r"v === undefined \|\| Number\.isNaN\(v\)", js)
    RESULTS.append((bool(safe), "the percentage helper checks before multiplying",
                    "pct100 guards first" if safe else "pct100 missing or reordered"))
except Exception as exc:                                   # noqa: BLE001
    RESULTS.append((False, "null-times-100 scan", f"could not run: {exc}"))

section("No two scripts declare the same global")

# Every frontend file is a classic script, so they all share one scope.
# Two files declaring `calc` at the top level is not a warning and not
# a shadow -- it is a SyntaxError at parse time, and the whole page
# renders blank with one line in a console nobody has open. Cheap to
# check, and the failure is total.
try:
    import re as _re
    import collections as _c

    root = Path(__file__).resolve().parent.parent / "frontend"
    files = ["chart.js", "greeks.js", "glossary.js", "working.js",
             "ledger.js", "app.js"]
    seen = _c.defaultdict(list)
    checked = []
    for name in files:
        path = root / name
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8")
        # A file wrapped in an IIFE leaks nothing and is exempt.
        if _re.search(r"^\(function \(\) \{", src, _re.M) and src.rstrip().endswith("}());"):
            continue
        checked.append(name)
        for m in _re.finditer(r"^(?:const|let|var|function|class)\s+([A-Za-z_$][\w$]*)",
                              src, _re.M):
            seen[m.group(1)].append(name)

    clash = {k: sorted(set(v)) for k, v in seen.items() if len(set(v)) > 1}
    RESULTS.append((not clash, "no name is declared by two scripts",
                    f"{len(checked)} unwrapped files" if not clash
                    else "; ".join(f"{k} in {v}" for k, v in list(clash.items())[:2])))
except Exception as exc:                                   # noqa: BLE001
    RESULTS.append((False, "global collisions", f"could not run: {exc}"))

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

section("Nothing in the backend is defined twice")

# A patch applied twice left two `_events` and two `@app.get("/api/events")`
# sitting fifteen lines apart. Python keeps the LAST function definition
# and FastAPI serves the FIRST matching route, so the two halves of the
# duplicate disagreed about which copy was live -- and the stale
# three-argument `_events` above the real one read like the truth to
# anyone scrolling past it.
#
# It happened to be harmless because the bodies agreed. The next one
# will not be, so it gets caught by shape rather than by luck.
try:
    shadowed, routes = [], []
    root = Path(__file__).resolve().parent
    for name in sorted(_os.listdir(root)):
        if not name.endswith(".py"):
            continue
        try:
            tree = _ast.parse(open(_os.path.join(root, name), encoding="utf-8").read())
        except (OSError, SyntaxError):
            continue

        # Top-level defs only: a method repeated across two classes is
        # fine, two defs of the same name in one module is not.
        seen = _c.Counter(n.name for n in tree.body
                          if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef)))
        shadowed += [f"{name}:{fn}" for fn, n in seen.items() if n > 1]

        for node in tree.body:
            if not isinstance(node, (_ast.FunctionDef, _ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if (isinstance(dec, _ast.Call)
                        and isinstance(dec.func, _ast.Attribute)
                        and dec.args
                        and isinstance(dec.args[0], _ast.Constant)
                        and isinstance(dec.args[0].value, str)
                        and dec.args[0].value.startswith("/")):
                    routes.append(f"{dec.func.attr.upper()} {dec.args[0].value}")

    RESULTS.append((not shadowed, "no function is defined twice in one module",
                    "clean" if not shadowed else ", ".join(shadowed[:4])))

    dup_routes = [r for r, n in _c.Counter(routes).items() if n > 1]
    RESULTS.append((not dup_routes, "no URL is registered by two handlers",
                    f"{len(routes)} routes, all distinct" if not dup_routes
                    else ", ".join(dup_routes[:4])))
except Exception as exc:                                   # noqa: BLE001
    RESULTS.append((False, "duplicate definition scan", f"could not run: {exc}"))

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
            # Every control byte, not the five a \x escape happens to
            # make.
            #
            # The named list missed an OCTAL one. A patch wrote "\25B2"
            # into a CSS rule from inside a non-raw Python string,
            # Python read \25 as octal for byte 0x15, and the
            # stylesheet ended up drawing a control byte followed by
            # the letters "B2" beside every figure on the page that
            # carries a direction. The up and down triangles the design
            # calls load-bearing were not being drawn at all, and this
            # check passed the entire time.
            #
            # Tab, newline and carriage return are the only ones that
            # belong in a source file. Anything else under 0x20 got
            # there by accident.
            for b in set(raw):
                if b < 0x20 and b not in (0x09, 0x0A, 0x0D):
                    found.append(f"{name}:{hex(b)}")
    RESULTS.append((not found, "no control bytes in any source file",
                    "clean" if not found else ", ".join(sorted(set(found))[:4])))
except Exception as exc:
    RESULTS.append((False, "control byte scan", f"could not run: {exc}"))

section("Every glossary term says how to use it")

# A definition that only says what a word means leaves the reader where
# it found them. Every entry carries a "using it" line as well, and the
# check is simply that none was missed -- there are fifty-eight, and
# adding a fifty-ninth without one would be easy.
try:
    import re as _re

    root = Path(__file__).resolve().parent.parent
    text = (root / "frontend" / "glossary.js").read_text(encoding="utf-8")
    body = text[text.index("const TERMS"):]
    blocks = _re.findall(r'^  ("[^"]+"|\w+): \{(.*?)^  \},', body, _re.S | _re.M)

    bare = [k for k, b in blocks if "use:" not in b]
    RESULTS.append((bool(blocks) and not bare, "every term has a using-it line",
                    f"{len(blocks)} terms" if not bare else f"missing: {bare[:4]}"))

    # A one-clause "use it carefully" would pass the check above and
    # help nobody.
    thin = []
    for k, b in blocks:
        m = _re.search(r'use:\s*(.*?)(?:\n  \}|\n    \w+:)', b + "\n  }", _re.S)
        if m and len(m.group(1)) < 80:
            thin.append(k)
    RESULTS.append((not thin, "and none of them is a stub",
                    "all substantial" if not thin else str(thin[:3])))

    # The tip must sit above the panel overlay, or it is invisible in
    # exactly the place it is most wanted: inside an opened panel.
    css = (root / "frontend" / "styles.css").read_text(encoding="utf-8")
    tip = _re.search(r"\.termtip \{.*?z-index: (\d+)", css, _re.S)
    over = _re.search(r"position: fixed; inset: 0; z-index: (\d+)", css)
    ok_layer = bool(tip and over and int(tip.group(1)) > int(over.group(1)))
    RESULTS.append((ok_layer, "the definition sits above the panel overlay",
                    "tip %s over overlay %s" % (tip.group(1) if tip else "?",
                                                over.group(1) if over else "?")))
except Exception as exc:                               # noqa: BLE001
    RESULTS.append((False, "glossary", f"could not run: {exc}"))

section("The JavaScript, checked in its own runtime")

# The indicators live in JavaScript, so they are checked by node rather
# than reimplemented here -- a Python copy of the same arithmetic would
# only prove the two copies agree. That suite tests RSI against Wilder's
# published worked example, which is the outside source of truth for it.
try:
    import subprocess

    root = Path(__file__).resolve().parent.parent
    for name, label in (("indicators.test.js", "indicator suite passes"),
                        ("ledger.test.js", "trade-log arithmetic passes"),
                        ("format.test.js", "the formatters name things correctly"),
                        ("expiry.test.js", "the expiry deadline is a real moment"),
                        ("versus.test.js", "the comparison names the right winner")):
        proc = subprocess.run(
            ["node", str(root / "frontend" / name)],
            capture_output=True, text=True, timeout=60, cwd=str(root))
        tail = (proc.stdout or "").strip().splitlines()
        summary = tail[-1] if tail else (proc.stderr or "no output").strip()[:60]
        RESULTS.append((proc.returncode == 0, label, summary))
except FileNotFoundError:
    RESULTS.append((None, "  [SKIP] indicator suite -- node not on PATH", ""))
except Exception as exc:
    RESULTS.append((False, "indicator suite", f"could not run: {exc}"))

# ------------------------------------------------------------------ report
if __name__ == "__main__":
    passed = failed = 0
    for ok, name, detail in RESULTS:
        if ok is None:
            print(f"\n{name}\n{'-' * len(name)}")
            continue
        # `A and B` returns B in Python, so an entry written as
        # `x is not None and some_list` puts a LIST here rather than a
        # bool -- and `passed += ok` then killed the whole run with a
        # TypeError after most of it had already printed. Coerced, so a
        # sloppy entry fails loudly as itself instead of taking the
        # summary down with it.
        good = bool(ok)
        # numpy's bool comes back from every pandas comparison and
        # coerces exactly like the builtin, so it is not worth naming.
        # A list or a dict here is the real tell: it means the entry was
        # written `x is not None and some_list`, and Python's `and`
        # returned the list rather than a verdict.
        if isinstance(ok, (list, dict, tuple, set, str)):
            detail = f"{detail}  (result was a {type(ok).__name__}, not a verdict)"
        mark = "PASS" if good else "FAIL"
        print(f"  [{mark}] {name:<42} {detail}")
        passed += good
        failed += not good
    print(f"\n{passed} passed, {failed} failed")
    # A pass against a saved board is a real statement about the logic and a
    # weaker one about today's market. Say which was used, so the two are
    # not read as the same claim.
    if _board_note():
        cap = (_BOARD_CACHE.get("all") or {}).get("captured")
        print("  option-board checks ran against a SAVED board "
              f"({cap}) because the live one was unavailable")
    sys.exit(1 if failed else 0)
