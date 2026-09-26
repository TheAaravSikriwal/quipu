"""From chart to trade: the curriculum, run on one stock.

Four steps, each consuming the output of the one before it -- the same
chain the curriculum walks XYZ through:

  1  find      liquidity, the IV environment, expected move, catalysts
  2  direction nine weighted signals -> direction, conviction, target,
               invalidation, timeframe
  3  build     strategy from the matrix, expiry, strikes, payoff, odds
  4  size      contracts, exposure, stops, target, time exit, the thesis

Inputs are fetched once, in parallel, and every step is arithmetic on
them. A source that fails becomes a named gap in the step that needed
it; the rest still runs.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime
from typing import Any, Dict, Optional

import ivhistory
from sources import deep, events

from . import data as D
from . import step1, step2, step3, step4


def _iv(symbol: str, rate: float, div: float) -> Dict[str, Any]:
    h = ivhistory.get(symbol, rate, div)
    if h.get("status") == "ready":
        h = {**h, "iv_rank": ivhistory.rank(h["iv30"]),
             "rr25_norm": ivhistory.zscore(h["rr25"], 252),
             "pc_norm": ivhistory.zscore(h["pc"])}
    return h


def build(symbol: str, rate: float, div: float, dividends=None,
          account: Optional[float] = None, risk_pct: float = 2.0) -> Dict[str, Any]:
    symbol = symbol.upper()
    with ThreadPoolExecutor(max_workers=10) as pool:
        jobs = {
            "daily": pool.submit(D.daily, symbol),
            "spy": pool.submit(D.daily, "SPY"),
            "all": pool.submit(D.expiries, symbol, div),
            "earnings": pool.submit(deep.fetch_earnings, symbol),
            "events": pool.submit(events.upcoming, None, 120),
            "info": pool.submit(D.info, symbol),
            "eps": pool.submit(D.eps_trend, symbol),
            "peers": pool.submit(D.peers, symbol),
            "scan": pool.submit(D.scan_frame),
            "ivh": pool.submit(_iv, symbol, rate, div),
        }
        got: Dict[str, Any] = {}
        for k, f in jobs.items():
            try:
                got[k] = f.result(timeout=60)
            except Exception as exc:                          # noqa: BLE001
                got[k] = None
                got[f"{k}_error"] = str(exc)[:160]

    daily, all_exp = got["daily"], got["all"] or []
    if not daily or len(daily["close"]) < 60:
        return {"symbol": symbol, "available": False, "why": "No price history for this symbol."}
    if not all_exp:
        return {"symbol": symbol, "available": False,
                "why": "No listed options came back (none listed, or the data provider declined the request)."}

    e30 = D.expiry_near(all_exp, 30, at_least=21) or D.expiry_near(all_exp, 30)
    board_for = lambda e: D.board(symbol, e, div, dividends)
    b30 = board_for(e30)
    if not b30:
        return {"symbol": symbol, "available": False, "why": f"The {e30} board did not load."}

    earnings = got["earnings"] or {}
    implied = None
    nxt = earnings.get("next_date")
    if nxt and 0 <= D.days_to(nxt) <= 120:
        post_e = next((e for e in all_exp if e > nxt), None)
        pre_e = next((e for e in reversed(all_exp) if e < nxt and D.days_to(e) >= 3), None)
        post, pre = (board_for(post_e) if post_e else None), (board_for(pre_e) if pre_e else None)
        implied = step2.implied_event(pre, post, step1.atm_pair)

    info = got["info"] or {}
    exd = info.get("exDividendDate")
    ex_div = None
    if isinstance(exd, (int, float)):
        d0 = datetime.utcfromtimestamp(exd).date()
        ex_div = d0.isoformat() if d0 >= date.today() else None

    ctx = {
        "symbol": symbol, "rate": rate, "div": div,
        "daily": daily, "spy": got["spy"], "all_expiries": all_exp,
        "board30": b30, "board_for": board_for,
        "earnings": earnings, "market_events": (got["events"] or {}).get("events", []),
        "info": info, "eps": got["eps"], "peers": got["peers"] or {"peers": []},
        "scan": got["scan"], "ivh": got["ivh"] or {"status": "failed"},
        "implied_event": implied, "ex_dividend": ex_div,
        "spy_price": (got["spy"] or {}).get("close", [None])[-1],
    }

    s1 = step1.build(ctx)
    if not s1.get("available"):
        return {"symbol": symbol, "available": False, "why": s1.get("why")}
    s2 = step2.build(ctx, s1)
    rs = next((m for sec in s2["sections"] for m in sec["metrics"] if m["id"] == "rs"), {})
    ctx["beta"] = {"value": rs.get("beta")}
    s3 = step3.build(ctx, s1, s2)
    s4 = step4.build(ctx, s2, s3, account, risk_pct)
    return {
        "symbol": symbol, "available": True, "spot": b30["spot"],
        "as_of": datetime.now().isoformat(timespec="minutes"),
        "iv_history": {k: ctx["ivh"].get(k) for k in ("status", "why", "from", "to", "built", "stale")},
        "steps": {"1": s1, "2": s2, "3": s3, "4": s4},
        "gaps": {k: v for k, v in got.items() if k.endswith("_error")},
    }
