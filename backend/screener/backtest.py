"""Did the rankings actually pick anything?

WHAT THE TEST IS

Walk-forward, out of sample. Pick a date in the past. Compute every metric
using ONLY the bars up to that date -- the same code the live screener runs,
fed a truncated history, so there is no way for it to see the future. Rank.
Take the top 20. Then look at what those twenty did over the next 5 and 21
sessions, and compare that against what EVERY eligible name did over the
same window. Step forward a fortnight and do it again, thirty times.

The comparison is the whole point. "The trend list returned +4%" means
nothing if the market returned +6%; the number that matters is the top
twenty against the median of everything you could have picked instead.

WHAT EACH RANKING IS SCORED ON

Only three of the seven are direction bets, and grading the other four on
return would be nonsense -- "gone quiet" is not a forecast that the stock
goes up, it is a forecast that it starts moving. So each ranking declares
its own objective:

  trend, thrust, snapback   forward return against the universe median.
                            These are the only ones claiming direction.

  coiled                    forward 21-day realised vol divided by trailing
                            21-day vol. Above 1 means volatility expanded,
                            which is the entire thesis of buying options on
                            a quiet stock. Graded against the same ratio for
                            the universe, because vol expands everywhere at
                            once when the market breaks.

  premium                   the same ratio, wanted BELOW 1. Selling rich
                            premium pays when volatility falls back.

  movement                  forward realised vol level. Not a prediction
                            that you make money -- a claim that these names
                            keep moving, which is what makes them worth
                            trading options on at all.

  tradeable                 persistence. Does a name that was liquid stay
                            liquid? Measured as the share of the top twenty
                            still in the top quintile of dollar volume a
                            month later.

WHAT THIS CANNOT TELL YOU

Twelve months and thirty overlapping windows is a small sample in one
market regime. Overlapping windows mean the observations are not
independent, so the spread is understated. There are no costs, no spreads,
no slippage, and options are not traded here at all -- this measures the
underlying, which is the input to an options decision rather than the
decision. Treat a result as a sanity check on whether a ranking is
measuring what it claims, not as evidence it makes money.
"""

from __future__ import annotations

import math
import time
import warnings
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from . import rank as R, scan as S, universe as U  # noqa: E402

import paths

PANEL = paths.CACHE / "panel.pkl"
REPORT = paths.CACHE / "backtest.json"

#: ranking -> what it claims, and therefore how it must be graded
OBJECTIVE = {
    "trend": "return",
    "thrust": "return",
    "snapback": "return",
    "coiled": "vol_expansion",
    "premium": "vol_contraction",
    "movement": "vol_level",
    "tradeable": "persistence",
}


def build_panel(symbols: List[str], period: str = "2y",
                chunk: int = 250, progress: bool = True) -> pd.DataFrame:
    """Download and cache the OHLCV panel the walk-forward replays over."""
    frames = []
    for i in range(0, len(symbols), chunk):
        batch = symbols[i:i + chunk]
        try:
            raw = S.yf.download(batch, period=period, interval="1d",
                                auto_adjust=True, threads=True, progress=False)
        except Exception:
            continue
        if raw is None or raw.empty:
            continue
        if not isinstance(raw.columns, pd.MultiIndex):
            raw.columns = pd.MultiIndex.from_product([raw.columns, batch[:1]])
        frames.append(raw)
        if progress:
            print(f"  panel {min(i + chunk, len(symbols))}/{len(symbols)}", flush=True)
    panel = pd.concat(frames, axis=1)
    panel = panel.loc[:, ~panel.columns.duplicated()]
    PANEL.parent.mkdir(parents=True, exist_ok=True)
    panel.to_pickle(PANEL)
    return panel


def load_panel() -> Optional[pd.DataFrame]:
    return pd.read_pickle(PANEL) if PANEL.exists() else None


def _forward(panel: pd.DataFrame, t: int, horizon: int) -> Dict[str, pd.Series]:
    """What happened AFTER the decision date, for every symbol."""
    close = panel["Close"]
    a, b = close.iloc[t], close.iloc[min(t + horizon, len(close) - 1)]
    ret = (b / a - 1) * 100

    rets = np.log(close / close.shift(1))
    fwd_vol = rets.iloc[t + 1: t + 1 + horizon].std() * math.sqrt(252) * 100
    back_vol = rets.iloc[max(0, t - horizon + 1): t + 1].std() * math.sqrt(252) * 100
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = fwd_vol / back_vol.replace(0, np.nan)
    return {"ret": ret, "fwd_vol": fwd_vol, "vol_ratio": ratio}


def run(panel: pd.DataFrame, every: int = 10, windows: int = 30,
        horizons=(5, 21), top: int = 20, progress: bool = True) -> Dict[str, Any]:
    """Replay the screener through history and score what it chose."""
    close = panel["Close"]
    n = len(close)
    longest = max(horizons)
    # Leave a year of history behind the first decision so the metrics that
    # need it -- vol rank, 12-1 momentum -- are computed the same way they
    # are live, and leave the longest horizon ahead of the last one.
    first, last = 260, n - longest - 1
    dates = list(range(last, first, -every))[:windows][::-1]
    if not dates:
        return {"error": "not enough history", "windows": 0}

    out: Dict[str, List[Dict[str, Any]]] = {k: [] for k in OBJECTIVE}

    for w, t in enumerate(dates):
        asof = panel.iloc[: t + 1]                 # strictly no lookahead
        try:
            metrics = S.measure(asof)
        except Exception:
            continue
        pool = R.eligible(metrics)
        if len(pool) < 100:
            continue
        fwd = _forward(panel, t, longest)
        fwd_short = _forward(panel, t, min(horizons))

        for name in OBJECTIVE:
            try:
                rows = R.rank(metrics, name, limit=top)
            except Exception:
                continue
            picks = [r["symbol"] for r in rows]
            if not picks:
                continue
            rec: Dict[str, Any] = {"date": str(close.index[t].date()), "picks": len(picks)}
            obj = OBJECTIVE[name]

            if obj == "return":
                for h, f in ((min(horizons), fwd_short), (longest, fwd)):
                    sel = f["ret"].reindex(picks).dropna()
                    base = f["ret"].reindex(pool.index).dropna()
                    if len(sel) and len(base):
                        rec[f"ret_{h}"] = float(sel.mean())
                        rec[f"base_{h}"] = float(base.median())
                        rec[f"edge_{h}"] = float(sel.mean() - base.median())
                        rec[f"beat_{h}"] = float((sel > base.median()).mean() * 100)
            elif obj in ("vol_expansion", "vol_contraction"):
                sel = fwd["vol_ratio"].reindex(picks).dropna()
                base = fwd["vol_ratio"].reindex(pool.index).dropna()
                if len(sel) and len(base):
                    rec["ratio"] = float(sel.median())
                    rec["base_ratio"] = float(base.median())
                    rec["edge"] = float(sel.median() - base.median())
                    want_up = obj == "vol_expansion"
                    rec["right_way"] = float(
                        ((sel > 1) == want_up).mean() * 100)
            elif obj == "vol_level":
                sel = fwd["fwd_vol"].reindex(picks).dropna()
                base = fwd["fwd_vol"].reindex(pool.index).dropna()
                if len(sel) and len(base):
                    rec["fwd_vol"] = float(sel.median())
                    rec["base_vol"] = float(base.median())
                    rec["ratio_to_base"] = float(sel.median() / base.median())
            elif obj == "persistence":
                later = panel.iloc[: min(t + longest, n - 1) + 1]
                try:
                    m2 = S.measure(later)
                except Exception:
                    m2 = None
                if m2 is not None and not m2.empty:
                    dv = m2["dollar_vol"].dropna()
                    if len(dv) > 50:
                        cut = dv.quantile(0.80)
                        still = dv.reindex(picks).dropna()
                        if len(still):
                            rec["still_liquid"] = float((still >= cut).mean() * 100)
            out[name].append(rec)

        if progress:
            print(f"  window {w + 1}/{len(dates)}  {close.index[t].date()}", flush=True)

    return {"windows": len(dates), "top": top, "horizons": list(horizons),
            "results": out}


def summarise(res: Dict[str, Any]) -> List[Dict[str, Any]]:
    """One line per ranking: did it do the thing it says it does?"""
    rows = []
    for name, recs in (res.get("results") or {}).items():
        if not recs:
            continue
        df = pd.DataFrame(recs)
        obj = OBJECTIVE[name]
        row: Dict[str, Any] = {"rank": name, "objective": obj, "windows": len(df)}
        if obj == "return":
            for h in res["horizons"]:
                if f"edge_{h}" in df:
                    row[f"edge_{h}d"] = round(df[f"edge_{h}"].mean(), 2)
                    row[f"ret_{h}d"] = round(df[f"ret_{h}"].mean(), 2)
                    row[f"base_{h}d"] = round(df[f"base_{h}"].mean(), 2)
                    # How often the whole window beat the median, not how
                    # often a single name did -- one moonshot should not be
                    # able to carry a ranking.
                    row[f"win_{h}d"] = round((df[f"edge_{h}"] > 0).mean() * 100, 0)
        elif obj in ("vol_expansion", "vol_contraction"):
            row["vol_ratio"] = round(df["ratio"].mean(), 3)
            row["universe"] = round(df["base_ratio"].mean(), 3)
            row["edge"] = round(df["edge"].mean(), 3)
            row["right_way_pct"] = round(df["right_way"].mean(), 0)
        elif obj == "vol_level":
            row["fwd_vol"] = round(df["fwd_vol"].mean(), 1)
            row["universe"] = round(df["base_vol"].mean(), 1)
            row["times_universe"] = round(df["ratio_to_base"].mean(), 2)
        elif obj == "persistence":
            if "still_liquid" in df:
                row["still_top_quintile_pct"] = round(df["still_liquid"].mean(), 0)
        rows.append(row)
    return rows


def report() -> Optional[Dict[str, Any]]:
    """The last saved study, for the screener to show beside each ranking."""
    import json
    if not REPORT.exists():
        return None
    try:
        return json.loads(REPORT.read_text(encoding="utf-8"))
    except Exception:
        return None


#: How each objective reads in one line, given its summary row.
def verdict(row: Dict[str, Any]) -> str:
    o = row["objective"]
    if o == "return":
        return (f"beat the median stock by {row.get('edge_5d', 0):+.2f}% over a week "
                f"({row.get('win_5d', 0):.0f}% of windows) and "
                f"{row.get('edge_21d', 0):+.2f}% over a month "
                f"({row.get('win_21d', 0):.0f}%)")
    if o == "vol_expansion":
        return (f"volatility expanded to {row['vol_ratio']:.2f}x its prior level against "
                f"{row['universe']:.2f}x for the universe, the right way "
                f"{row['right_way_pct']:.0f}% of windows")
    if o == "vol_contraction":
        return (f"volatility fell to {row['vol_ratio']:.2f}x its prior level against "
                f"{row['universe']:.2f}x for the universe, the right way "
                f"{row['right_way_pct']:.0f}% of windows")
    if o == "vol_level":
        return (f"kept moving: {row['fwd_vol']:.0f}% realised volatility over the next "
                f"month against {row['universe']:.0f}% for the universe "
                f"({row['times_universe']:.1f}x)")
    if o == "persistence":
        return (f"{row.get('still_top_quintile_pct', 0):.0f}% were still in the top "
                f"quintile of dollar volume a month later")
    return ""


if __name__ == "__main__":
    import json
    import sys

    t0 = time.time()
    panel = load_panel()
    if panel is None:
        # Replay only over names that clear a loose liquidity bar today.
        #
        # This is the one place the study is not clean: a name is in the
        # panel because it is liquid NOW, which quietly excludes anything
        # that was liquid two years ago and has since died. The bar is set
        # well below the screener's own $20m gate so that eligibility can
        # still be re-decided from as-of data at each window rather than
        # fixed in advance, but the survivorship tilt is real and it flatters
        # every return figure below.
        scan_df = pd.read_pickle(paths.CACHE / "scan.pkl")
        syms = sorted(scan_df[scan_df.dollar_vol > 5e6].index)
        print(f"building panel for {len(syms)} names...")
        panel = build_panel(syms)
    print(f"panel {panel['Close'].shape} loaded in {time.time() - t0:.0f}s")

    res = run(panel, every=int(sys.argv[1]) if len(sys.argv) > 1 else 10,
              windows=int(sys.argv[2]) if len(sys.argv) > 2 else 30)
    rows = summarise(res)
    for row in rows:
        row["verdict"] = verdict(row)
    REPORT.write_text(json.dumps({
        "ran_at": time.time(), "windows": res["windows"], "top": res["top"],
        "horizons": res["horizons"], "rows": rows,
    }, indent=1), encoding="utf-8")


    print(f"\n{res['windows']} windows, top {res['top']}, horizons {res['horizons']}\n")
    for row in rows:
        print(f"  {row['rank']:<10} {row['verdict']}")
    print(f"\nsaved  |  total {time.time() - t0:.0f}s")
