"""Step 1 -- Find the candidate (Lessons 1.1 to 1.5).

The question: is this worth trading, and is the options market a place to
buy premium or to sell it? Direction is not decided here.

Everything is read at the at-the-money strike of the listed expiry
nearest 30 days out -- the expiry the curriculum builds around -- so the
liquidity being judged is the liquidity of the contract you would
actually trade, not of the busiest strike on the board.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from . import data as D
from .read import (BEAR, BULL, NEUTRAL, first_hit, fmt, line, metric, missing,
                   money, pct, row, sum_of, table, term)


def atm_pair(board: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """The strike nearest the share price that has a quote on both sides."""
    spot = board["spot"]
    calls = {r["strike"]: r for r in board["calls"] if r.get("bid") and r.get("ask")}
    puts = {r["strike"]: r for r in board["puts"] if r.get("bid") and r.get("ask")}
    both = sorted(set(calls) & set(puts), key=lambda k: abs(k - spot))
    if not both:
        return None
    k = both[0]
    return {"strike": k, "call": calls[k], "put": puts[k]}


def hv(closes: List[float], n: int = 20) -> Optional[Dict[str, Any]]:
    """Lesson 0.5: stdev of daily log returns, annualised by sqrt(252)."""
    r = D.log_returns(closes[-(n + 1):])
    sd = D.stdev(r)
    if sd is None or len(r) < n:
        return None
    return {"value": sd * math.sqrt(252) * 100, "daily_sd": sd, "n": len(r)}


# ---- 1.1 liquidity ---------------------------------------------------------

def liquidity(atm: Dict[str, Any], board: Dict[str, Any]) -> List[Dict[str, Any]]:
    c = atm["call"]
    bid, ask = c["bid"], c["ask"]
    mid = (bid + ask) / 2
    spread = (ask - bid) / mid * 100
    k = atm["strike"]
    out = []

    hit = first_hit([spread < 5, spread <= 10, True])
    out.append(metric(
        "spread", "1.1", f"Bid-ask spread, ${fmt(k, 2)} call", spread, pct(spread, 1),
        working=sum_of(spread, [
            line("", term("ask", ask)), line("-", term("bid", bid)),
            line("/", term("mid, (bid + ask) / 2", mid)),
            line("x", term("as a percent", 100, 0)),
        ], unit="%"),
        formula="Spread % = (ask - bid) / mid x 100",
        against=table([row("under 5% of mid", "Good"),
                       row("5 to 10%", "Acceptable -- use a limit order at mid"),
                       row("over 10%", "Expensive -- your edge must be large")], hit),
        compare=[{"label": "round trip, one contract",
                  "show": money((ask - bid) * 100),
                  "working": sum_of((ask - bid) * 100, [
                      line("", term("ask", ask)), line("-", term("bid", bid)),
                      line("x", term("shares per contract", 100, 0))])}],
        stance="pass" if spread <= 10 else "fail",
        means=("Tight enough that the spread will not eat the trade." if spread < 5 else
               "Workable, but place limit orders at the mid rather than paying the ask."
               if spread <= 10 else
               "Every entry and exit loses a real slice to the spread. The thesis has to "
               "be strong enough to pay for that twice."),
    ))

    oi_c, oi_p = c.get("open_interest") or 0, atm["put"].get("open_interest") or 0
    oi = min(oi_c, oi_p)
    typical = (c.get("oi_read") or {}).get("typical")
    hit = first_hit([oi < 100, oi < 500, oi < 1000, True])
    out.append(metric(
        "oi", "1.1", f"Open interest at ${fmt(k, 2)}", oi, f"{oi:,}",
        formula="Contracts currently open at this strike (the thinner of call and put)",
        against=table([row("under 100", "Avoid unless the spread is still tight"),
                       row("100 to 500", "Workable -- check the spread carefully"),
                       row("500+", "Comfortably liquid"), row("1,000+", "Very liquid")], hit),
        compare=[{"label": "call / put", "show": f"{oi_c:,} / {oi_p:,}"}]
        + ([{"label": "typical strike on this board", "show": f"{typical:,}"}] if typical else []),
        stance="pass" if oi >= 100 or spread < 5 else "fail",
        means=("The size of the crowd you would be selling back to. "
               + ("Plenty." if oi >= 500 else "Enough, if the spread holds." if oi >= 100
                  else "Thin: getting out early may cost more than the screen suggests.")),
    ))

    vol = c.get("volume") or 0
    if oi_c:
        ratio = vol / oi_c
        out.append(metric(
            "vol_oi", "1.1", "Volume / open interest, the call", ratio, fmt(ratio, 2),
            working=sum_of(ratio, [line("", term("today's volume", vol, 0)),
                                   line("/", term("open interest", oi_c, 0))], unit=""),
            formula="Volume/OI = today's volume / open interest",
            against=table([row("above 1", "New positions are being opened today"),
                           row("1 or below", "Mostly existing holders trading")],
                          0 if ratio > 1 else 1),
            means=("Fresh interest: more traded today than was open this morning."
                   if ratio > 1 else
                   "Ordinary turnover. High open interest with almost no volume would be stale."),
        ))
    return out


# ---- 1.2 the IV environment -------------------------------------------------

IVR_TABLE = [row("0 to 30", "Options cheap -- favour BUYING premium (long calls/puts, debit spreads)", "buy"),
             row("30 to 50", "Neutral -- debit spreads work well", "debit"),
             row("50 to 70", "Rich -- favour SELLING premium, or spreads that sell some back", "sell"),
             row("70 to 100", "Very rich -- credit strategies; beware the event causing it", "credit")]


def iv_column(ivr: Optional[float], iv_hv: Optional[float]) -> Dict[str, Any]:
    """Which column of the Lesson 3.1 matrix this stock sits in.

    IV Rank decides it when there is one. Without the history, IV/HV is
    the only honest stand-in, and the page says it is standing in."""
    if ivr is not None:
        col = "low" if ivr < 30 else "mid" if ivr < 50 else "high"
        return {"column": col, "by": "IV Rank", "value": ivr}
    if iv_hv is not None:
        col = "low" if iv_hv < 0.9 else "mid" if iv_hv <= 1.2 else "high"
        return {"column": col, "by": "IV/HV (no IV Rank without the history)", "value": iv_hv}
    return {"column": "mid", "by": "nothing to go on -- treated as neutral", "value": None}


def iv_environment(atm: Dict[str, Any], closes: List[float],
                   ivh: Dict[str, Any]) -> List[Dict[str, Any]]:
    out = []
    iv_now = (atm["call"]["iv"] + atm["put"]["iv"]) / 2          # percent
    h = hv(closes, 20)

    rk = ivh.get("iv_rank") if ivh.get("status") == "ready" else None
    if rk and rk.get("rank") is not None:
        r = rk["rank"]
        cur, lo, hi = rk["current"] * 100, rk["low"] * 100, rk["high"] * 100
        out.append(metric(
            "iv_rank", "1.2", "IV Rank", r, fmt(r, 1),
            working=sum_of(r, [
                line("", term("IV now (30-day, at the money)", cur, 1)),
                line("-", term(f"52-week low, {rk['low_on']}", lo, 1)),
                line("/", term("the year's range, high - low", hi - lo, 1)),
                line("x", term("to 0-100", 100, 0)),
            ], unit=""),
            formula="IV Rank = (IV - 52w low) / (52w high - 52w low) x 100",
            against=table(IVR_TABLE, first_hit([r < 30, r < 50, r < 70, True])),
            compare=[{"label": "52-week range", "show": f"{pct(lo)} to {pct(hi)}"},
                     {"label": "high was on", "show": rk["high_on"]}],
            stance=IVR_TABLE[first_hit([r < 30, r < 50, r < 70, True])]["reads"],
            source=f"Rebuilt from Alpaca option closes, {ivh.get('from')} to {ivh.get('to')}",
            means=("Where today's IV sits in its own year. One spike stretches the range and "
                   "drags this down, which is why IV Percentile sits beside it."),
        ))
        p = rk["percentile"]
        out.append(metric(
            "iv_pct", "1.2", "IV Percentile", p, fmt(p, 1),
            working=sum_of(p, [line("", term("sessions IV was below today", rk["below"], 0)),
                               line("/", term("sessions in the year", rk["days"], 0)),
                               line("x", term("to 0-100", 100, 0))], unit=""),
            formula="IV Percentile = days below today's IV / total days x 100",
            against=table(IVR_TABLE, first_hit([p < 30, p < 50, p < 70, True])),
            compare=[{"label": "IV Rank", "show": fmt(r, 1)}],
            stance=IVR_TABLE[first_hit([p < 30, p < 50, p < 70, True])]["reads"],
            means=("More robust than the rank to a single spike. "
                   + ("They agree." if abs(p - r) < 15 else
                      f"They disagree by {abs(p - r):.0f} points -- one extreme day is "
                      "distorting the rank; lean on the percentile.")),
        ))
    else:
        why = ivh.get("why") or {"building": "the year's history is still being rebuilt -- a few seconds",
                                 "failed": "the history could not be rebuilt"}.get(ivh.get("status"), "no history")
        out.append(missing("iv_rank", "1.2", "IV Rank", f"Needs a year of this stock's IV: {why}.",
                           formula="IV Rank = (IV - 52w low) / (52w high - 52w low) x 100"))
        out.append(missing("iv_pct", "1.2", "IV Percentile", f"Needs the same history: {why}.",
                           formula="IV Percentile = days below today's IV / total days x 100"))

    if h:
        h60 = hv(closes, 60)
        out.append(metric(
            "hv20", "1.2", "Historical volatility, 20 days", h["value"], pct(h["value"]),
            compare=[{"label": "IV now, at the money", "show": pct(iv_now)}]
            + ([{"label": "HV over 60 days", "show": pct(h60["value"]),
                 "reads": None}] if h60 else [])
            + ([{"label": "the last month against the last quarter",
                 "show": "calmer" if h["value"] < h60["value"] else "busier"}] if h60 else []),
            working=sum_of(h["value"], [
                line("", term("stdev of the last 20 daily log returns", h["daily_sd"], 5)),
                line("x", term("sqrt(252 trading days)", math.sqrt(252), 3)),
                line("x", term("as a percent", 100, 0))], unit="%"),
            formula="HV = stdev(ln(Pt / Pt-1)) x sqrt(252)",
            means="What the stock has actually been doing, in the same units as IV.",
        ))
        ratio = iv_now / h["value"]
        hit = first_hit([ratio > 1.2, ratio < 0.9, True])
        out.append(metric(
            "iv_hv", "1.2", "IV / HV", ratio, fmt(ratio, 2),
            working=sum_of(ratio, [line("", term("IV now, at the money", iv_now, 1)),
                                   line("/", term("HV20", h["value"], 1))], unit=""),
            formula="IV/HV = IV / HV20",
            against=table([row("above 1.2", "Rich: options priced above what the stock has been doing", "sell"),
                           row("below 0.9", "Cheap: priced below its realised movement", "buy"),
                           row("0.9 to 1.2", "Fair", "debit")], hit),
            compare=[{"label": "IV now", "show": pct(iv_now)}, {"label": "HV20", "show": pct(h["value"])}],
            stance=["sell", "buy", "debit"][hit],
            means=("The volatility risk premium. " + [
                "Buying options here means paying more for movement than the stock has been giving.",
                "Movement is on sale: the stock has been moving more than options charge for.",
                "Options are priced about in line with how the stock actually moves."][hit]),
        ))
    return out


# ---- 1.3 expected move and catalysts ----------------------------------------

def expected_move(atm: Dict[str, Any], board: Dict[str, Any]) -> List[Dict[str, Any]]:
    s, dte = board["spot"], board["days_to_expiry"]
    iv = (atm["call"]["iv"] + atm["put"]["iv"]) / 2 / 100
    model = s * iv * math.sqrt(dte / 365)
    straddle = atm["call"]["mark"] + atm["put"]["mark"]
    out = [metric(
        "em_model", "1.3", f"Expected move to {board['expiry']} (model)", model,
        "±" + money(model),
        working=sum_of(model, [line("", term("share price", s)),
                               line("x", term("IV", iv, 4)),
                               line("x", term(f"sqrt({dte} days / 365)", math.sqrt(dte / 365), 4))]),
        formula="Expected move = S x IV x sqrt(DTE / 365)",
        compare=[{"label": "68% range", "show": f"{money(s - model)} to {money(s + model)}"},
                 {"label": "95% range", "show": f"{money(s - 2 * model)} to {money(s + 2 * model)}"},
                 {"label": "as a percent", "show": pct(model / s * 100)}],
        means=("A one-standard-deviation move by that expiry. Any target you set in Step 2 "
               "is judged against this: expecting less than what is priced in makes buying "
               "options a bad bet even when you are right."),
        extra={"low": s - model, "high": s + model, "iv": iv * 100, "dte": dte},
    ), metric(
        "em_market", "1.3", "Expected move (market, the straddle)", straddle, "±" + money(straddle),
        working=sum_of(straddle, [line("", term(f"${fmt(atm['strike'])} call", atm["call"]["mark"])),
                                  line("+", term(f"${fmt(atm['strike'])} put", atm["put"]["mark"]))]),
        formula="Expected move ~ ATM call + ATM put",
        compare=[{"label": "0.8 x the model", "show": money(0.8 * model),
                  "working": sum_of(0.8 * model, [line("", term("sqrt(2/pi)", 0.8, 2)),
                                                  line("x", term("model move", model))])},
                 {"label": "priced in", "show": pct(straddle / s * 100)}],
        means=("What it actually costs to bet on movement either way. It should sit near "
               "0.8x the model; well above means the market is paying for an event."),
    ), metric(
        "daily_move", "0.5", "A normal day (rule of 16)", iv * 100 / 16, pct(iv * 100 / 16, 2),
        working=sum_of(iv * 100 / 16, [line("", term("IV", iv * 100, 1)),
                                       line("/", term("sqrt(256)", 16, 0))], unit="%"),
        formula="Typical daily move ~ IV / 16",
        compare=[{"label": "in dollars", "show": money(s * iv / 16)}],
        means="How far the share moves on an ordinary day at this IV. A day bigger than about "
              "twice this is news.",
    )]
    return out


def catalysts(earnings: Dict[str, Any], market: List[Dict[str, Any]],
              board: Dict[str, Any]) -> List[Dict[str, Any]]:
    exp, dte = board["expiry"], board["days_to_expiry"]
    nxt = earnings.get("next_date")
    out = []
    if nxt:
        days = D.days_to(nxt)
        inside = 0 <= days <= dte
        out.append(metric(
            "earnings_date", "1.3", "Next earnings", days, nxt,
            compare=[{"label": "days away", "show": str(days)},
                     {"label": f"inside the {exp} window", "show": "yes" if inside else "no"}],
            means=("Inside the window: IV will rise into it and collapse the morning after "
                   "(IV crush). Buying options through it is a bet on the move beating what "
                   "is priced in." if inside else
                   "Outside this expiry, so it cannot crush options bought for it."),
            extra={"inside": inside, "date": nxt},
        ))
    else:
        out.append(missing("earnings_date", "1.3", "Next earnings", "No confirmed date from Yahoo."))
    big = [e for e in market if (e.get("weight") or 0) >= 2 and 0 <= (e.get("days") or 99) <= dte]
    out.append(metric(
        "market_events", "1.3", "Market-wide events before expiry", len(big), str(len(big)),
        compare=[{"label": e["date"], "show": e["title"]} for e in big[:6]]
        or [{"label": "window checked", "show": f"today to {exp} ({dte} days)"},
            {"label": "counted", "show": "Fed decisions, CPI, jobs, GDP and other heavy releases"}],
        means=("Scheduled releases that move everything, not just this stock." if big else
               "Nothing heavy on the calendar before this expiry."),
        extra={"events": big[:6]},
    ))
    return out


# ---- 1.4 unusual activity, 1.5 put/call -------------------------------------

def unusual(board: Dict[str, Any]) -> Dict[str, Any]:
    ua = board.get("unusual_activity") or []
    top = sorted(ua, key=lambda r: -(r.get("vol_oi_ratio") or 0))[:4]
    checked = len(board.get("calls") or []) + len(board.get("puts") or [])
    return metric(
        "unusual", "1.4", "Unusual options activity", len(ua), str(len(ua)),
        formula="Flag: volume > open interest at a strike",
        compare=[{"label": f"${fmt(r['strike'])} {r['type']}",
                  "show": f"{r['volume']:,} vs {r['open_interest']:,} open ({fmt(r['vol_oi_ratio'], 1)}x)",
                  "reads": BULL if r["type"] == "call" else BEAR} for r in top]
        or [{"label": f"contracts checked on {board['expiry']}", "show": f"{checked:,}, none flagged"}],
        means=("A source of ideas to research, never a trade to copy: you cannot see whether "
               "it is a hedge, one leg of a spread, or small next to the trader's book."),
    )


def put_call_screen(board: Dict[str, Any]) -> Dict[str, Any]:
    st = board.get("stats") or {}
    pv, cv = st.get("put_volume") or 0, st.get("call_volume") or 0
    po, co = st.get("put_oi") or 0, st.get("call_oi") or 0
    if not cv:
        return missing("pc_screen", "1.5", "Put/call ratio", "No call volume on this expiry today.")
    r = pv / cv
    return metric(
        "pc_screen", "1.5", f"Put/call, {board['expiry']}", r, fmt(r, 2),
        working=sum_of(r, [line("", term("put volume", pv, 0)), line("/", term("call volume", cv, 0))], unit=""),
        formula="P/C (volume) = put volume / call volume",
        compare=[{"label": "by open interest", "show": fmt(po / co, 2) if co else "--"}],
        means="Noted here only for extreme positioning; it is read against its own normal in Step 2.",
    )


# ---- the step -----------------------------------------------------------------

def build(ctx: Dict[str, Any]) -> Dict[str, Any]:
    board = ctx["board30"]
    atm = atm_pair(board)
    if not atm:
        return {"available": False, "why": "No two-sided quotes at the money on the ~30-day expiry."}
    liq = liquidity(atm, board)
    ivm = iv_environment(atm, ctx["daily"]["close"], ctx["ivh"])
    em = expected_move(atm, board)
    cat = catalysts(ctx["earnings"], ctx["market_events"], board)
    ua, pcs = unusual(board), put_call_screen(board)

    by = {m["id"]: m for m in liq + ivm + em + cat + [ua, pcs]}
    ok = all(m.get("stance") != "fail" for m in liq)
    col = iv_column(by.get("iv_rank", {}).get("value") if by.get("iv_rank", {}).get("available") else None,
                    by.get("iv_hv", {}).get("value"))
    stance_row = IVR_TABLE[{"low": 0, "mid": 1, "high": 2}[col["column"]]]
    return {
        "available": True,
        "question": "Which stocks are worth analysing, and is this a place to buy or sell premium?",
        "expiry": board["expiry"], "dte": board["days_to_expiry"], "atm": atm["strike"],
        "sections": [
            {"lesson": "1.1", "title": "Liquidity: can I trade this cleanly?", "metrics": liq},
            {"lesson": "1.2", "title": "IV environment: are options cheap or expensive?", "metrics": ivm},
            {"lesson": "1.3", "title": "Expected move and catalysts: how big a move, and when?", "metrics": em + cat},
            {"lesson": "1.4-1.5", "title": "Unusual activity and put/call", "metrics": [ua, pcs]},
        ],
        "output": {
            "liquid": ok, "spread_pct": by["spread"]["value"],
            "iv_column": col, "stance": stance_row["read"],
            "expected_move": by["em_model"]["value"], "expected_pct": by["em_model"]["value"] / board["spot"] * 100,
            "earnings": ({"date": by["earnings_date"]["date"], "inside": by["earnings_date"]["inside"],
                          "days": by["earnings_date"]["value"]}
                         if by["earnings_date"]["available"] else None),
        },
    }
