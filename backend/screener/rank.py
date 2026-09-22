"""Turning measurements into rankings.

Every ranking here is a weighted blend of percentiles taken WITHIN the
filtered universe, never of raw numbers. That matters: 40% annualised
volatility is enormous for a utility and sleepy for a biotech, and a raw
threshold would fill every list with the same forty small caps. A percentile
asks the only question that transfers between names -- where does this sit
relative to everything else you could have traded instead.

Each ranking states its components and their weights, and every row carries
the component percentiles back to the caller, so the interface can always
answer "why is this here" with the actual numbers rather than a black box.

None of these are buy signals and none of them predict anything. They are
sort orders over public measurements, which is all a screener has ever been.
"""

from __future__ import annotations

from typing import Any, Dict, List

import numpy as np
import pandas as pd

# The floor for everything. Below this an option is either unquotable or the
# spread eats the trade, which is the one point every experienced options
# trader makes before any other.
GATE = {"price": 5.0, "dollar_vol": 20_000_000, "bars": 200}

# A stock under an agreed takeover stops trading on its own merits: the price
# pins to the offer and volatility collapses toward nothing. That is a real
# measurement, and it topped the "gone quiet" list with names whose quiet is
# permanent -- there is no coiled spring, the deal just closed the question.
# Anything running this far below its own yearly volatility is treated as
# pinned rather than resting.
PINNED_RATIO = 0.15


def _pct(series: pd.Series, invert: bool = False) -> pd.Series:
    """Percentile within the universe, 0-100."""
    r = series.rank(pct=True) * 100
    return (100 - r) if invert else r


def _band(series: pd.Series, lo: float, hi: float) -> pd.Series:
    """Score 100 inside a range, tapering outside it.

    Used for share price. Options are sold in lots of a hundred shares, so a
    $900 stock prices most accounts out of a single contract, while a $6 one
    has a spread measured in whole percent. Neither end is wrong, both are
    worse, and a percentile cannot say that -- it has no notion of a middle
    being best.
    """
    x = series.astype(float)
    below = (x / lo).clip(upper=1.0)
    above = (hi / x).clip(upper=1.0)
    return (below * above * 100).clip(lower=0)


#: name -> (label, one-line purpose, components as (metric, weight, invert))
RANKINGS: Dict[str, Dict[str, Any]] = {
    "tradeable": {
        "label": "Easiest to trade",
        "note": "Where you can get in and back out without the spread taking the trade.",
        "parts": [
            ("dollar_vol", 0.55, False),
            ("price_band", 0.25, False),
            ("avg_move", 0.20, False),
        ],
    },
    "movement": {
        "label": "Most movement",
        "note": "The ones that actually travel. Big premiums, and they are big for a reason.",
        "parts": [
            ("vol20", 0.50, False),
            ("atr_pct", 0.30, False),
            ("gap", 0.20, False),
        ],
    },
    "coiled": {
        "label": "Gone quiet",
        "note": "Capable of moving, currently still. Where long options are cheapest.",
        "drop_pinned": True,
        "parts": [
            ("vol_rank", 0.45, True),
            ("vol_ratio", 0.30, True),
            ("vol252", 0.25, False),
        ],
    },
    "premium": {
        "label": "Richest premium",
        "note": "Volatility high against its own history. Where selling is paid the most.",
        "parts": [
            ("vol_rank", 0.60, False),
            ("vol_ratio", 0.40, False),
        ],
    },
    "trend": {
        "label": "Strongest trend",
        "note": "A year of orderly gains, not one lucky gap. The long-horizon list.",
        "parts": [
            ("mom_12_1", 0.40, False),
            ("trend_r2", 0.30, False),
            ("from_200", 0.20, False),
            ("drawdown", 0.10, True),
        ],
    },
    "thrust": {
        "label": "Moving now",
        "note": "Recent return on unusual volume. The short-horizon list.",
        "parts": [
            ("ret_1m", 0.40, False),
            ("rvol", 0.25, False),
            ("from_20", 0.20, False),
            ("ret_3m", 0.15, False),
        ],
    },
    "snapback": {
        "label": "Pulled back",
        "note": "Well off the highs and under the 50-day, but the year is still up.",
        "parts": [
            ("drawdown", 0.35, False),
            ("from_50", 0.30, True),
            ("mom_12_1", 0.35, False),
        ],
    },
}

#: Plain-English reasons, keyed by metric. `v` is the raw value.
PHRASE = {
    "dollar_vol": lambda v: f"{v/1e6:,.0f}M traded a day",
    "price_band": lambda v: "price suits round lots",
    "avg_move": lambda v: f"moves {v:.1f}% on an average day",
    "vol20": lambda v: f"{v:.0f}% volatility",
    "atr_pct": lambda v: f"{v:.1f}% daily range",
    "gap": lambda v: f"gaps {v:.1f}% overnight",
    "vol_rank": lambda v: f"vol at the {v:.0f}th percentile of its own year",
    "vol_ratio": lambda v: f"running at {v:.2f}x its yearly volatility",
    "vol252": lambda v: f"{v:.0f}% volatility over the year",
    "mom_12_1": lambda v: f"{v:+.0f}% over the year to last month",
    "trend_r2": lambda v: f"{v:.2f} trend fit",
    "from_200": lambda v: f"{v:+.0f}% from its 200-day",
    "from_50": lambda v: f"{v:+.0f}% from its 50-day",
    "from_20": lambda v: f"{v:+.0f}% from its 20-day",
    "drawdown": lambda v: f"{v:.0f}% off the high",
    "ret_1m": lambda v: f"{v:+.0f}% in a month",
    "ret_3m": lambda v: f"{v:+.0f}% in three months",
    "rvol": lambda v: f"{v:.1f}x normal volume",
}


def eligible(df: pd.DataFrame, min_price: float = None,
             min_dollar_vol: float = None) -> pd.DataFrame:
    g = dict(GATE)
    if min_price is not None:
        g["price"] = min_price
    if min_dollar_vol is not None:
        g["dollar_vol"] = min_dollar_vol
    return df[(df.price >= g["price"])
              & (df.dollar_vol >= g["dollar_vol"])
              & (df.bars >= g["bars"])].copy()


def rank(df: pd.DataFrame, which: str, limit: int = 40,
         **gates: Any) -> List[Dict[str, Any]]:
    """Score the universe on one ranking and return the top rows."""
    spec = RANKINGS.get(which)
    if spec is None:
        raise KeyError(which)

    pool = eligible(df, **gates)
    if spec.get("drop_pinned"):
        pool = pool[pool["vol_ratio"] >= PINNED_RATIO]
    if pool.empty:
        return []
    pool["price_band"] = _band(pool["price"], 20.0, 400.0)

    score = pd.Series(0.0, index=pool.index)
    parts: Dict[str, pd.Series] = {}
    for metric, weight, invert in spec["parts"]:
        p = _pct(pool[metric], invert) if metric != "price_band" else pool[metric]
        p = p.fillna(p.median())
        parts[metric] = p
        score += p * weight
    pool["score"] = score

    top = pool.sort_values("score", ascending=False).head(limit)

    rows: List[Dict[str, Any]] = []
    for sym, r in top.iterrows():
        # The reasons, strongest component first -- that is the honest answer
        # to "why is this on the list", in the order it actually mattered.
        contrib = sorted(
            ((m, parts[m].loc[sym] * w) for m, w, _ in spec["parts"]),
            key=lambda kv: kv[1], reverse=True)
        why = [PHRASE[m](r[m]) for m, _ in contrib[:3] if m in PHRASE and pd.notna(r.get(m))]

        rows.append({
            "symbol": sym,
            "score": round(float(r["score"]), 1),
            "why": why,
            "price": _num(r["price"]),
            "dollar_vol": _num(r["dollar_vol"]),
            "vol20": _num(r["vol20"]),
            "vol60": _num(r["vol60"]),
            "vol252": _num(r["vol252"]),
            "avg_move": _num(r["avg_move"]),
            "gap": _num(r["gap"]),
            "vol_rank": _num(r["vol_rank"]),
            "vol_ratio": _num(r["vol_ratio"], 3),
            "atr_pct": _num(r["atr_pct"]),
            "rvol": _num(r["rvol"], 2),
            "ret_1m": _num(r["ret_1m"]),
            "ret_3m": _num(r["ret_3m"]),
            "ret_12m": _num(r["ret_12m"]),
            "mom_12_1": _num(r["mom_12_1"]),
            "trend_r2": _num(r["trend_r2"], 3),
            "from_20": _num(r["from_20"]),
            "from_50": _num(r["from_50"]),
            "from_200": _num(r["from_200"]),
            "drawdown": _num(r["drawdown"]),
        })
    return rows


def _num(v: Any, places: int = 2) -> Any:
    try:
        f = float(v)
        return None if (f != f or f in (float("inf"), float("-inf"))) else round(f, places)
    except (TypeError, ValueError):
        return None


def catalogue() -> List[Dict[str, str]]:
    return [{"id": k, "label": v["label"], "note": v["note"]}
            for k, v in RANKINGS.items()]
