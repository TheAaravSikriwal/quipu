"""The shape every number on the search page takes.

The curriculum's rule is that each step answers one question and none
may be skipped. Its lessons each produce a number, compare it with a
table, and say what that means for the trade. So every number here
carries the same four things, and the page draws them the same way:

    value     the figure, and the sum it came from (working.py's
              vocabulary, so it can be hovered or laid out)
    against   what it is compared with: the curriculum's table, with
              the row it lands in marked, and any other figure it is
              read against (IV against HV, the stock against SPY)
    reads     which way it points -- bullish, bearish or neutral for a
              direction signal; buy or sell premium for an IV one
    means     one or two sentences on what to do with it

A number that cannot be worked out says why, instead of being filled in.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional, Sequence

from working import line, sum_of, term

__all__ = ["metric", "missing", "row", "table", "line", "sum_of", "term",
           "fmt", "pct", "money", "bull", "bear", "neutral"]

BULL, BEAR, NEUTRAL = "bullish", "bearish", "neutral"
bull, bear, neutral = BULL, BEAR, NEUTRAL


def row(when: str, read: str, reads: Optional[str] = None) -> Dict[str, Any]:
    """One row of a curriculum table: the condition, and what it means."""
    return {"when": when, "read": read, "reads": reads}


def table(rows: Sequence[Dict[str, Any]], hit: Optional[int]) -> Dict[str, Any]:
    return {"rows": list(rows), "hit": hit}


def metric(id: str, lesson: str, label: str, value: Any, show: str,
           means: str, working: Optional[Dict[str, Any]] = None,
           against: Optional[Dict[str, Any]] = None,
           compare: Optional[List[Dict[str, Any]]] = None,
           reads: Optional[str] = None, stance: Optional[str] = None,
           score: Optional[int] = None, weight: Optional[int] = None,
           formula: Optional[str] = None, source: Optional[str] = None,
           extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """One number, with everything needed to read it."""
    out = {
        "id": id, "lesson": lesson, "label": label,
        "available": True, "value": value, "show": show,
        "working": working, "formula": formula,
        "against": against, "compare": compare or [],
        "reads": reads, "stance": stance,
        "score": score, "weight": weight,
        "means": means, "source": source,
    }
    if extra:
        out.update(extra)
    return out


def missing(id: str, lesson: str, label: str, why: str,
            weight: Optional[int] = None, formula: Optional[str] = None
            ) -> Dict[str, Any]:
    """A number the app cannot honestly give, and the reason."""
    return {"id": id, "lesson": lesson, "label": label, "available": False,
            "why": why, "value": None, "show": "--", "reads": NEUTRAL if weight else None,
            "score": 0 if weight else None, "weight": weight, "formula": formula,
            "means": why, "compare": [], "against": None, "working": None}


# ---- formatting, for the `show` strings ------------------------------------

def fmt(v: Optional[float], dp: int = 2) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "--"
    return f"{v:,.{dp}f}"


def pct(v: Optional[float], dp: int = 1, sign: bool = False) -> str:
    if v is None:
        return "--"
    return (f"{v:+,.{dp}f}" if sign else f"{v:,.{dp}f}") + "%"


def money(v: Optional[float], dp: int = 2) -> str:
    if v is None:
        return "--"
    return ("-$" if v < 0 else "$") + f"{abs(v):,.{dp}f}"


def first_hit(bands: Sequence[bool]) -> Optional[int]:
    for i, b in enumerate(bands):
        if b:
            return i
    return None
