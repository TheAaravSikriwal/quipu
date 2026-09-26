"""Step 4 -- Size, manage and review (Lessons 4.1 to 4.5).

The question: how much, when exactly do I get out, and what did I say
before I got in? Every exit is written before entry, from numbers the
earlier steps already produced -- the invalidation from Step 2, the max
loss from Step 3 -- because an exit decided afterwards is a hope.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from sources import options as O

from .read import fmt, line, money, pct, row, sum_of, table, term

RISK_TABLE = [row("0.5 to 1%", "Conservative, or speculative / high-IV trades"),
              row("1 to 2%", "Common standard"),
              row("3 to 5%", "Aggressive: only defined-risk, high-conviction setups")]


def _value_at(legs: List[Dict[str, Any]], s: float, days: int, vol: float, rate: float, q: float) -> float:
    """What the position is worth, per share, at price s with `days` left."""
    t = max(days, 0) / 365
    v = 0.0
    for l in legs:
        sg = 1 if l["side"] == "long" else -1
        v += sg * O.bs_price(s, l["strike"], t, vol, rate, l["kind"] == "call", q)
    return v


def build(ctx: Dict[str, Any], step2: Dict[str, Any], step3: Dict[str, Any],
          account: Optional[float], risk_pct: float) -> Dict[str, Any]:
    if not step3.get("legs"):
        return {"available": False, "why": step3.get("summary") or step3.get("why") or "No trade to size."}
    pay, legs = step3["payoff"], step3["legs"]
    v = step2["output"]
    s, vol, dte = step3["spot"], step3["vol"] / 100, step3["dte"]
    rate, q = ctx["rate"], ctx.get("div") or 0.0
    sells = step3["strategy"] in ("bull_put", "bear_call", "iron_condor")
    cost = pay.get("net_cost") or 0.0                 # dollars per contract, + debit / - credit
    per_share = abs(cost) / 100

    # ---- 4.1 sizing
    unbounded = pay.get("max_loss_unbounded")
    max_loss = abs(pay["max_loss"]) if pay.get("max_loss") is not None and not unbounded else None
    sizing: Dict[str, Any] = {"risk_pct": risk_pct, "account": account, "max_loss": max_loss,
                              "table": table(RISK_TABLE, 0 if risk_pct <= 1 else 1 if risk_pct <= 2 else 2)}
    if max_loss is None:
        sizing["why"] = "Undefined risk: the loss has no ceiling, so there is no max loss to size against."
    elif account:
        budget = account * risk_pct / 100
        n = math.floor(budget / max_loss) if max_loss else 0
        sizing.update({
            "budget": budget, "contracts": n,
            "actual_pct": n * max_loss / account * 100,
            "working": sum_of(n, [line("", term("account", account, 0)),
                                  line("x", term("risk per trade", risk_pct / 100, 3)),
                                  line("/", term("max loss per contract", max_loss)),
                                  line("whole", term("rounded down to whole contracts", n, 0))], unit=""),
            "note": (f"One contract risks {pct(max_loss / account * 100, 2)} of the account -- more than "
                     f"{pct(risk_pct, 1)}. Either the trade is too big for the account, or it needs a "
                     "narrower structure." if n == 0 else None),
        })
    else:
        sizing["why"] = "Enter your account size to get the contract count."
    n = sizing.get("contracts") or 1

    # Drawdown math, Lesson 4.1.
    recovery = [{"loss": x, "gain": x / (1 - x / 100)} for x in (10, 25, 50, 75)]

    # ---- 4.2 beta-weighted delta
    bw = None
    beta = (ctx.get("beta") or {}).get("value")
    spy = ctx.get("spy_price")
    net_delta = (step3["greeks"]["net"] or {}).get("delta")
    if beta and spy and net_delta is not None:
        val = net_delta * 100 * n * beta * s / spy
        bw = {"value": val, "working": sum_of(val, [
            line("", term("position delta, per share", net_delta, 3)),
            line("x", term("shares per contract", 100, 0)),
            line("x", term("contracts", n, 0)),
            line("x", term("beta", beta, 2)),
            line("x", term("share price / SPY price", s / spy, 4))], unit="",
            note="SPY-share equivalents. Add this up across every open trade to see your real market exposure.")}

    # ---- 4.3 stops
    inv = v.get("invalidation")
    stops = []
    long_vol = step3["strategy"] in ("straddle", "strangle")
    if not inv and not long_vol and v.get("support") and v.get("resistance"):
        stops.append({"kind": "price", "label": f"Range broken: {v.get('invalidation_text')}",
                      "detail": "A range trade is wrong the moment the range stops holding."})
    if inv:
        stops.append({"kind": "price", "label": f"Thesis broken: {v.get('invalidation_text')}",
                      "detail": "Underlying-based: exit on the close, not the intraday touch."})
        at_inv = _value_at(legs, inv, min(10, dte), vol, rate, q)
        stops.append({"kind": "reference", "label": f"Worth about {money(abs(at_inv))} a share at {money(inv)} with 10 days left",
                      "detail": "So you know what the price stop costs before it happens.", "value": at_inv})
    if sells:
        buyback = per_share * 3
        stops.append({"kind": "premium", "label": f"Loss reaches twice the credit: buy back at about {money(buyback)}",
                      "working": sum_of(buyback, [line("", term("credit C", per_share)),
                                                  line("+", term("twice the credit", 2 * per_share))], per_share=True),
                      "detail": "A credit trade's premium stop is a multiple of what you took in, commonly 1.5 to 2x."})
    else:
        half = per_share * 0.5
        stops.append({"kind": "premium", "label": f"Value falls to {money(half)} (-50% of the {money(per_share)} paid)",
                      "working": sum_of(half, [line("", term("paid", per_share)), line("x", term("half", 0.5, 1))], per_share=True),
                      "detail": "Premium-based: long premium is commonly cut at half its cost."})

    # ---- 4.4 profit target
    maxp = pay.get("max_profit")
    if sells:
        tgt_val = per_share * 0.5
        target = {"label": f"Buy it back at {money(tgt_val)}: half the credit kept",
                  "short": f"a {money(tgt_val)} buy-back (half the credit)",
                  "working": sum_of(tgt_val, [line("", term("credit C", per_share)), line("x", term("half", 0.5, 1))], per_share=True),
                  "detail": "Close credit trades at about 50% of the credit; the last half takes the most time and risk."}
    elif maxp and not pay.get("max_profit_unbounded"):
        gain = maxp / 100 * 0.5
        tgt_val = per_share + gain
        target = {"label": f"Close when it is worth {money(tgt_val)}: half the maximum profit",
                  "short": f"a {money(tgt_val)} value (half the max profit)",
                  "working": sum_of(tgt_val, [line("", term("paid", per_share)),
                                              line("+", term("max profit per share", maxp / 100), term("half", 0.5, 1))],
                                    per_share=True),
                  "detail": "Spreads: take 50 to 75% of max profit. A spread only reaches full value at expiry, "
                            "while theta and gamma risk grow in the last days."}
    else:
        t = v.get("target")
        at_t = _value_at(legs, t, min(10, dte), vol, rate, q) if t else None
        target = {"label": (f"At the Step 2 target {money(t)}: worth about {money(at_t)} a share with 10 days left"
                            if t else "Take half off at +100%, trail the rest"),
                  "short": f"the {money(t)} target" if t else "+100% on half",
                  "detail": "Long options: take profit at the target, or scale out -- close half at +50 to 100% and trail the rest.",
                  "value": at_t}

    # ---- 4.5 time exit
    time_exit = ({"days_left": 21, "label": "Close around 21 days left, before gamma risk grows"} if sells else
                 {"days_left": 10, "label": "Hard exit with 10 days left, unless deep in the money"})
    from datetime import date, timedelta
    exp = date.fromisoformat(step3["expiry"])
    time_exit["on"] = (exp - timedelta(days=time_exit["days_left"])).isoformat()

    shorts = [l for l in legs if l["side"] == "short"]
    ex_div = ctx.get("ex_dividend")
    assign = None
    if shorts and ex_div and ex_div <= step3["expiry"]:
        assign = (f"An ex-dividend date ({ex_div}) falls before expiry: a short call that is in the money "
                  "then can be assigned early. Close or roll it first.")

    # ---- the one sentence
    name = step3["name"].lower()
    legs_txt = "/".join(fmt(l["strike"], 2).rstrip("0").rstrip(".") for l in legs)
    words = ("move further than the options price in, either way" if long_vol else
             {"bullish": "rise", "bearish": "fall", "neutral": "stay in its range"}[v["direction"]])
    thesis = (f"I expect {ctx['symbol']} to {words}"
              + (f" toward {money(v['target'])}" if v.get("target") else "")
              + (f" within {v['timeframe']['low']}-{v['timeframe']['high']} days" if v.get("timeframe") else "")
              + f", so I'm {'selling' if sells else 'buying'} the {step3['dte']}-day {legs_txt} {name} for a "
              + f"{money(per_share)} {'credit' if sells else 'debit'}"
              + ((f", risking {money(max_loss * n, 0)}" + (f" ({pct(n * max_loss / account * 100, 1)} of my account)" if account else ""))
                 if max_loss and not (account and sizing.get("contracts") == 0) else "")
              + (f", exiting on {v['invalidation_text']}" if v.get("invalidation_text") and not long_vol else
                 ", exiting if it loses half its cost" if long_vol else "")
              + f", taking profits at {target['short']}"
              + f", and closing no later than {time_exit['days_left']} days before expiration."
              + (f" Sized to your rules this is zero contracts: one risks {money(max_loss, 0)}, "
                 f"{pct(max_loss / account * 100, 1)} of the account, over your {pct(risk_pct, 1)} limit."
                 if max_loss and account and sizing.get("contracts") == 0 else ""))

    return {"available": True, "question": "How much, when do I get out, and how will I know I was right?",
            "sizing": sizing, "recovery": recovery, "beta_weighted": bw, "stops": stops,
            "target": target, "time_exit": time_exit, "assignment": assign, "thesis": thesis,
            "contracts_used": n}
