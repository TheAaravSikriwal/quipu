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
                        ("ledger.test.js", "trade-log arithmetic passes")):
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
        mark = "PASS" if ok else "FAIL"
        print(f"  [{mark}] {name:<42} {detail}")
        passed += ok
        failed += not ok
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
