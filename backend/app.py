"""quipu API -- everything knowable about one ticker, in one response.

Pipeline for a single search:

  1. fan out across every source at once (quote, options, filings, social, news
     discovery) -- wide across sources, throttled within each
  2. extract full text for the discovered article URLs, bounded concurrency
  3. cluster the articles into stories, then diff their claims
  4. return the lot, with per-source timings so a slow provider is visible
"""

from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent))

from crossref.claims import cross_reference  # noqa: E402
from crossref.cluster import cluster  # noqa: E402
from extract.tiered import available_tiers, extract  # noqa: E402
from fanout import bounded_map, fanout  # noqa: E402
import position as position_engine  # noqa: E402
import presets as preset_engine  # noqa: E402
import working as show_working  # noqa: E402
from screener import backtest as screen_backtest, rank as screen_rank, store as screen_store, universe as screen_universe  # noqa: E402
from sources import deep, events, holdings, news_rss, options, quotes, sec_edgar, sec_xbrl, symbols  # noqa: E402
from sources import world as world_news  # noqa: E402

FRONTEND = Path(__file__).resolve().parent.parent / "frontend"

MAX_ARTICLES = int(os.getenv("QUIPU_MAX_ARTICLES", "22"))
EXTRACT_CONCURRENCY = int(os.getenv("QUIPU_EXTRACT_CONCURRENCY", "6"))

app = FastAPI(title="quipu", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _div_schedule(symbol: str):
    """Upcoming ex-dividend dates, for the escrowed pricing model.

    Wrapped because it must never be the reason a chain fails to load:
    a company with no dividend history and a company whose history
    could not be fetched both correctly price as if nothing is due.
    """
    try:
        return (deep.fetch_dividends(symbol) or {}).get("schedule") or []
    except Exception:                                  # noqa: BLE001
        return []


def _div_yield(symbol: str) -> float:
    """Dividend yield as a decimal fraction, for the greeks.

    Derived from the annual rate over the price wherever possible, because
    that is unambiguous. Yahoo's own dividendYield field is a PERCENTAGE
    NUMBER -- AAPL comes back as 0.32 meaning 0.32%, not 32% -- and guessing
    at the units from magnitude gets it wrong by a hundred times on exactly
    the low-yield mega-caps most likely to be looked up here.
    """
    try:
        f = quotes.fetch_fundamentals(symbol)
        div = f.get("dividend") or {}
        rate = div.get("rate")
        price = (quotes.fetch_quote(symbol) or {}).get("price")
        if rate and price and price > 0:
            y = float(rate) / float(price)
        elif div.get("yield") is not None:
            y = float(div["yield"]) / 100.0
        else:
            return 0.0
        # Nothing legitimate pays more than 25%; beyond that it is bad data.
        return y if 0.0 <= y < 0.25 else 0.0
    except Exception:
        return 0.0


@app.get("/api/health")
def health() -> Dict[str, Any]:
    return {
        "ok": True,
        "extraction_tiers": available_tiers(),
        "optional_keys": {
            "finnhub": bool(os.getenv("FINNHUB_API_KEY")),
            "firecrawl": bool(os.getenv("FIRECRAWL_API_KEY")),
        },
        "max_articles": MAX_ARTICLES,
    }


def _result_map(results: List[Any]) -> Dict[str, Any]:
    return {r.source: r for r in results}


@app.get("/api/search")
def symbol_search(q: str) -> Dict[str, Any]:
    """Resolve a company name to candidate tickers, for the search box."""
    try:
        return {"query": q, "results": symbols.search(q)}
    except Exception as exc:
        return {"query": q, "results": [], "error": str(exc)}


@app.get("/api/screen/rankings")
def screen_rankings() -> Dict[str, Any]:
    """The rankings on offer, and how fresh the measurements behind them are."""
    screen_store.ensure()
    # Each ranking carries its own walk-forward result, so the interface can
    # say what the thing actually did rather than only what it claims to do.
    study = screen_backtest.report() or {}
    by_rank = {r["rank"]: r for r in study.get("rows", [])}
    cat = screen_rank.catalogue()
    for r in cat:
        r["study"] = by_rank.get(r["id"])
    return {
        "rankings": cat,
        "meta": screen_store.meta(),
        "study": {k: study.get(k) for k in ("ran_at", "windows", "top", "horizons")}
                 if study else None,
    }


@app.get("/api/screen")
def screen(rank: str = "tradeable", limit: int = 40,
           min_price: float = None, min_dollar_vol: float = None) -> Dict[str, Any]:
    """One ranking over the whole US universe.

    The scan behind this takes about three minutes and runs in a thread, so
    the first call after a cold start answers `scanning` with a count rather
    than blocking. Once it is warm every ranking is instant, because they are
    all sort orders over the same measured table.
    """
    screen_store.ensure()
    df = screen_store.frame()
    meta = screen_store.meta()
    if df is None:
        return {"rank": rank, "rows": [], "meta": meta}

    try:
        rows = screen_rank.rank(df, rank, limit=limit,
                                min_price=min_price, min_dollar_vol=min_dollar_vol)
    except KeyError:
        raise HTTPException(status_code=400, detail=f"unknown ranking: {rank}")

    # Names come from the listing file, not from a per-symbol lookup: at forty
    # rows that would be forty more requests for something already on disk.
    names = screen_universe.index()
    for r in rows:
        info = names.get(r["symbol"], {})
        r["name"] = info.get("name")
        r["exchange"] = info.get("exchange")
        r["etf"] = info.get("etf", False)

    spec = screen_rank.RANKINGS[rank]
    meta["eligible"] = int(len(screen_rank.eligible(
        df, min_price=min_price, min_dollar_vol=min_dollar_vol)))
    return {
        "rank": rank,
        "label": spec["label"],
        "note": spec["note"],
        "parts": [{"metric": m, "weight": w, "invert": inv} for m, w, inv in spec["parts"]],
        "rows": rows,
        "meta": meta,
    }


@app.post("/api/screen/refresh")
def screen_refresh() -> Dict[str, Any]:
    screen_store.ensure(force=True)
    return screen_store.meta()


def _realised_vol(symbol: str) -> Dict[str, Any]:
    """What the stock has actually been doing, annualised."""
    import math as _m
    out: Dict[str, Any] = {}
    try:
        frame = quotes.yf.Ticker(symbol).history(period="6mo", interval="1d")
        closes = [float(c) for c in frame["Close"].tolist() if c == c]
        rets = [_m.log(b / a) for a, b in zip(closes, closes[1:]) if a > 0]
        for label, n in (("rv20", 20), ("rv60", 60)):
            tail = rets[-n:]
            if len(tail) >= max(10, n // 2):
                mean = sum(tail) / len(tail)
                var = sum((r - mean) ** 2 for r in tail) / (len(tail) - 1)
                out[label] = round(_m.sqrt(var) * _m.sqrt(252) * 100, 2)
    except Exception:
        pass
    return out


def _parity_spot(calls, puts, spot_quoted, spot_ref, rate, years,
                 discrete: bool, div: float):
    """What the option board says the share is worth, and how it says it.

    One answer to "what is this share worth", for every endpoint that
    needs one.

    It used to be worked out inside the chain endpoint and nowhere
    else, so the board priced a stock leg off the parity reading while
    the position engine marked the same leg off the raw quote. On a
    thinly quoted name those are different numbers -- 16.31 against
    16.02 on FRVO -- and a hundred shares recorded at one and valued
    at the other showed a $29 loss the moment it was opened, before
    anything had happened. A tenth of the risk on the trade, invented
    by two halves of the app disagreeing.

    Returns the quoted price unchanged when the board cannot improve
    on it, which is the common case.
    """
    put_at = {p["strike"]: p for p in puts}

    def two_sided(r):
        return r.get("bid") and r.get("ask") and r["ask"] > r["bid"]

    pairs = [(c, put_at[c["strike"]]) for c in calls
             if c["strike"] in put_at and two_sided(c)
             and two_sided(put_at[c["strike"]])]
    if not pairs or not spot_quoted or not spot_ref:
        return spot_ref, "quote"

    # The nearest-the-money pair, where the spread is tightest and the
    # parity read is therefore cleanest.
    c, p = min(pairs, key=lambda cp: abs(cp[0]["strike"] - spot_quoted))
    # Parity has to be written against whichever dividend model the
    # board was priced under, or the identity is being solved for the
    # wrong unknown. Escrowed:  C - P = S_adj - K.e^(-rT), and S_adj
    # already has the dividends removed. Continuous: the old form with
    # the e^(-qT) term.
    forward = (c["mark"] - p["mark"]) + c["strike"] * math.exp(-rate * years)
    implied = forward if discrete else forward / math.exp(-div * years)

    # Only trust it if it is close; a wild number means a broken quote,
    # not a stale one.
    if abs(implied / spot_ref - 1) < 0.03:
        return implied, f"put-call parity at {c['strike']:g}"
    return spot_ref, "quote"


@app.get("/api/chain/{symbol}")
def chain(symbol: str, expiry: str = None, vol: float = None,
          basis: str = "atm") -> Dict[str, Any]:
    """One board of contracts, for building a position against.

    Deliberately light. The full ticker route pulls news, filings and five
    years of history; picking a strike needs none of that, and making the
    builder wait six seconds to show a ladder would be the difference
    between a tool you click around in and one you fill in.
    """
    symbol = symbol.strip().upper()
    if not symbol or len(symbol) > 12:
        raise HTTPException(status_code=400, detail="invalid symbol")

    div = _div_yield(symbol)
    sched = _div_schedule(symbol)
    data = options.fetch_options(symbol, max_expiries=1, div_yield=div,
                                 only=expiry, dividends=sched)
    if not data.get("available"):
        raise HTTPException(status_code=404,
                            detail=data.get("reason", f"no options for {symbol}"))

    board = (data.get("expiries") or [{}])[0]
    quote = quotes.fetch_quote(symbol) or {}

    # ---- what the options themselves say the stock is worth -------------
    #
    # The quoted spot lags the options tape. Put-call parity is an identity,
    # not a model -- C - P = S*e^-qT - K*e^-rT must hold or there is free
    # money -- so the board can be asked directly what spot it is pricing
    # off, and it disagreed with the quote by about a dollar.
    #
    # That one dollar was not cosmetic. Solving each contract's implied vol
    # against a stale spot pushed every call's IV up and every put's IV
    # down by three to four points AT THE SAME STRIKE, which cannot happen:
    # a call and a put on one strike and one expiry share a volatility.
    # The whole put side then read as systematically cheap, which looked
    # like an opportunity and was an arithmetic error.
    spot_quoted = data.get("spot") or quote.get("price") or 0
    rate = options.risk_free_rate()
    years = max((board.get("trading_days") or 0) / 252.0, 1 / 252.0)

    # Everything below prices in the same currency the board was priced
    # in. Where the dividend dates are known that is the escrowed spot --
    # the share price less the payments due before expiry -- and mixing
    # the two would apply the dividend twice or not at all.
    esc = options.escrowed_spot(spot_quoted, sched, expiry or board.get("expiry"), rate)
    use_q = 0.0 if esc["model"] == "discrete" else div
    spot_ref = esc["spot"]

    calls = board.get("calls") or []
    puts = board.get("puts") or []

    spot, spot_source = _parity_spot(
        calls, puts, spot_quoted, spot_ref, rate, years,
        esc["model"] == "discrete", div)

    # Re-solve every implied vol against that spot, because the ones on the
    # rows were solved against the stale one.
    if abs(spot - spot_ref) > 0.005:
        for side, rows in (("call", calls), ("put", puts)):
            for r in rows:
                mk = r.get("mark") or r.get("last")
                if not mk:
                    continue
                iv = options.implied_vol(mk, spot, float(r["strike"]), years,
                                         rate, side == "call", use_q)
                if iv:
                    r["iv"] = round(iv * 100, 2)
                    r["iv_source"] = "solved"
        atm_call = min((c for c in calls if c.get("iv")),
                       key=lambda c: abs(c["strike"] - spot), default=None)
        if atm_call:
            board.setdefault("stats", {})["atm_iv"] = atm_call["iv"]

    # ---- a fair value for every strike ---------------------------------
    #
    # The reference volatility must not come from the contract being judged:
    # each row's IV was solved backwards out of its own price, so pricing a
    # strike with it returns that price and compares a number with itself.
    #
    #   atm       the at-the-money vol for this expiry. Differences are then
    #             the SKEW -- what the market charges for this strike over
    #             the money. Expected, not irrational.
    #   realised  what the stock has actually done over 20 sessions.
    #             Differences are the variance risk premium.
    rv = _realised_vol(symbol)
    atm_iv = (board.get("stats") or {}).get("atm_iv")
    if vol and vol > 0:
        ref, ref_label = float(vol), f"your {float(vol):.0f}%"
    elif basis == "realised" and rv.get("rv20"):
        ref, ref_label = rv["rv20"], f"realised {rv['rv20']:.0f}%"
    elif atm_iv:
        ref, ref_label = float(atm_iv), f"at-the-money {float(atm_iv):.0f}%"
    else:
        ref, ref_label = (rv.get("rv20") or 30.0), "realised"

    for side, rows in (("call", calls), ("put", puts)):
        for r in rows:
            mark = r.get("mark") or r.get("last")
            if not (mark and spot and r.get("strike")):
                r["fair"] = r["edge"] = r["edge_vol"] = None
                continue
            fair = options.bs_price(spot, float(r["strike"]), years,
                                    ref / 100.0, rate, side == "call", use_q)
            r["fair"] = round(fair, 4)
            r["edge"] = round(mark - fair, 4)
            # The same mispricing in volatility terms. Dollars alone cannot
            # be compared across strikes: a far out-of-the-money contract has
            # almost no vega, so four points of extra vol shows up as a cent,
            # while at the money it is worth half a dollar. Points are the
            # comparable unit; dollars are what you actually pay.
            r["edge_vol"] = round(r["iv"] - ref, 2) if r.get("iv") else None

    return {
        "symbol": symbol,
        "name": quote.get("name"),
        "spot": round(spot, 4) if spot else None,
        "change_pct": quote.get("change_pct"),
        "all_expiries": data.get("all_expiries") or [],
        "expiry": board.get("expiry"),
        "days": board.get("days_to_expiry"),
        "trading_days": board.get("trading_days"),
        "stats": board.get("stats"),
        "calls": board.get("calls") or [],
        "puts": board.get("puts") or [],
        "spot_quoted": round(spot_quoted, 4) if spot_quoted else None,
        "spot_source": spot_source,
        "presets": preset_engine.build(calls, puts, board.get("expiry"),
                                       spot, ref / 100.0, rate, div),
        "fair_basis": basis if not vol else "custom",
        "fair_vol": round(ref, 2),
        "fair_label": ref_label,
        "atm_iv": atm_iv,
        "realised": rv,
    }


@app.post("/api/working")
def working(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """How one price was arrived at, written out as the sum it is.

    Takes the inputs rather than fetching them: the client already has
    the spot, the strike and the volatility off the board it is looking
    at, so this is arithmetic with no network in it and it can be asked
    again every time the selection changes.

    It lives on the server rather than being reimplemented in the
    browser so that there is one Black-Scholes in this codebase. A
    second copy would agree on the day it was written.
    """
    kind = str(payload.get("kind") or "option")

    def f(name, default=0.0):
        try:
            return float(payload.get(name, default))
        except (TypeError, ValueError):
            return default

    if kind == "option":
        return show_working.option_price(
            f("spot"), f("strike"), f("years"), f("vol"), f("rate"),
            bool(payload.get("is_call", True)), f("div_yield"))
    if kind == "intrinsic":
        return show_working.intrinsic(f("spot"), f("strike"),
                                      bool(payload.get("is_call", True)))
    if kind == "edge":
        return show_working.edge(f("market"), f("fair"))
    if kind == "breakeven":
        return show_working.breakeven_single(
            f("strike"), f("premium"), bool(payload.get("is_call", True)))
    raise HTTPException(status_code=400, detail=f"unknown working: {kind}")


@app.post("/api/position")
def position(payload: Dict[str, Any] = Body(...)) -> Dict[str, Any]:
    """Analyse a trade that is already on.

    Marks come from the live chain where the exact contract is listed, and
    fall back to Black-Scholes only when it is not -- a model price is a
    reasonable stand-in for a missing quote but a poor substitute for a real
    one, and the difference is the spread you would actually pay to close.
    """
    symbol = str(payload.get("symbol", "")).strip().upper()
    legs = payload.get("legs") or []
    if not symbol or not legs:
        raise HTTPException(status_code=400, detail="symbol and legs required")

    quote = quotes.fetch_quote(symbol) or {}
    spot = float(payload.get("spot") or quote.get("price") or 0)
    if not spot:
        raise HTTPException(status_code=400, detail=f"no price for {symbol}")

    div = _div_yield(symbol)
    rate = options.risk_free_rate()
    spot_source = "quote"

    # Pull only the expiries this position actually uses.
    wanted = sorted({(l.get("expiry") or "") for l in legs if l.get("expiry")})
    marks: Dict[str, float] = {}
    atm_iv = None
    try:
        # The same dividend model the board is priced under. Without the
        # schedule this fell back to the continuous yield while /api/chain
        # used discrete dividends, so one option had two fair values
        # depending on which endpoint asked -- and the position engine,
        # which is what the trade log totals, was on the less exact one.
        chains = options.fetch_options(symbol, max_expiries=8, div_yield=div,
                                       dividends=_div_schedule(symbol))
        for exp in (chains.get("expiries") or []):
            if exp["expiry"] not in wanted:
                continue
            if atm_iv is None:
                atm_iv = (exp.get("stats") or {}).get("atm_iv")
                # The same share price the BOARD is priced off, not the
                # raw quote.
                #
                # The two used to disagree: the chain endpoint solved
                # the spot out of put-call parity and the position
                # engine took the quote, so a hundred shares recorded
                # off the board at 16.31 were marked at 16.02 and
                # showed a $29 loss the instant the trade was opened.
                # A tenth of the risk on it, invented by two halves of
                # the app answering one question differently.
                years_here = max(exp.get("trading_days") or 1, 1) / 252.0
                sched = _div_schedule(symbol)
                esc_here = options.escrowed_spot(spot, sched, exp["expiry"], rate)
                implied, src = _parity_spot(
                    exp["calls"], exp["puts"], spot, esc_here["spot"],
                    rate, years_here, esc_here["model"] == "discrete", div)
                if src != "quote":
                    spot, spot_source = implied, src
            for side, rows in (("call", exp["calls"]), ("put", exp["puts"])):
                for r in rows:
                    mk = r.get("mark") or r.get("last")
                    if mk:
                        marks[f"{side}:{float(r['strike'])}:{exp['expiry']}"] = float(mk)
    except Exception:
        pass

    vol = (atm_iv / 100.0) if atm_iv else 0.30
    analysis = position_engine.analyse(legs, spot, vol, rate, div, marks)
    if not analysis.get("ok"):
        raise HTTPException(status_code=400, detail=analysis.get("reason", "bad legs"))

    earnings = None
    try:
        earnings = (deep.fetch_earnings(symbol) or {}).get("next_date")
    except Exception:
        pass

    analysis["guidance"] = position_engine.guidance(analysis, vol, rate, div, earnings)
    analysis["plain"] = position_engine.describe(
        analysis, quote.get("name") or symbol, symbol)
    analysis["symbol"] = symbol
    analysis["name"] = quote.get("name")
    analysis["change_pct"] = quote.get("change_pct")
    analysis["spot_source"] = spot_source
    analysis["vol_used"] = round(vol * 100, 2)
    analysis["rate"] = round(rate * 100, 3)
    analysis["div_yield"] = round(div * 100, 3)

    # The working comes back from analyse() with the analysis it explains.
    #
    # It used to be rebuilt here as well, and the rebuild -- three keys
    # where the engine produces five -- overwrote the richer one on its
    # way out. So "most you can make" and "most you can lose", the two
    # figures on the page in the largest type, were the only ones with
    # no arithmetic behind them: it existed, and this line dropped it.
    analysis["earnings"] = earnings
    analysis["marks_live"] = sum(
        1 for l in analysis["legs"]
        if l["kind"] != "stock"
        and f"{l['kind']}:{float(l['strike'])}:{l['expiry']}" in marks)
    analysis["at"] = time.strftime("%H:%M:%S", time.localtime())
    return analysis


@app.get("/api/news/{symbol}")
def news_only(symbol: str, company: str = "") -> Dict[str, Any]:
    """Headlines, and nothing else -- for the loop that watches for more.

    The fifteen-second refresh deliberately leaves news alone, because
    re-scraping two dozen article bodies on a timer would get us
    rate-limited within the hour. But DISCOVERY is not scraping: it is
    five RSS feeds fetched in parallel, about a second and a half, and
    a story that breaks at ten past does not need to wait for a reload
    to appear.

    So this is discovery only. No extraction, no cross-referencing, no
    financials. The page merges what comes back into the list it
    already has and says how many are new.
    """
    symbol = symbol.strip().upper()
    if not symbol or len(symbol) > 12:
        raise HTTPException(status_code=400, detail="bad symbol")

    started = time.monotonic()
    try:
        found = news_rss.discover_all(symbol, company)
    except Exception as exc:                               # noqa: BLE001
        raise HTTPException(status_code=502, detail=str(exc))

    return {
        "symbol": symbol,
        "at": time.strftime("%H:%M:%S", time.localtime()),
        "ms": int((time.monotonic() - started) * 1000),
        "count": len(found),
        "articles": [
            {
                "url": a["url"],
                "title": a.get("title"),
                "excerpt": (a.get("summary") or "")[:320],
                "publisher": a.get("publisher"),
                "published": a.get("published"),
                "discovered_via": a.get("discovered_via"),
                "also_via": a.get("also_via", []),
                "feed_count": a.get("feed_count") or 1,
                "chars": 0,
                "tier": None,
            }
            for a in found
        ],
    }


@app.get("/api/live/{symbol}")
def live(symbol: str) -> Dict[str, Any]:
    """The fast-moving numbers only, for the refresh loop.

    Deliberately excludes news and financials. Re-scraping 45 articles every
    fifteen seconds would get us rate-limited within the hour, and quarterly
    figures cannot change between ticks anyway.
    """
    symbol = symbol.strip().upper()
    started = time.monotonic()

    results = _result_map(
        fanout(
            {
                "quote": lambda: quotes.fetch_quote(symbol),
                "intraday": lambda: quotes.fetch_intraday(symbol),
                "series_1d": lambda: quotes.fetch_series_live(symbol),
                # The refresh overwrites the options the page was built
                # with, so it has to price them the same way. It did not,
                # which meant the ticker page quietly switched from
                # discrete dividends to a continuous yield fifteen
                # seconds after it loaded.
                "options": lambda: options.fetch_options(
                    symbol, max_expiries=2, div_yield=_div_yield(symbol),
                    dividends=_div_schedule(symbol)),
            },
            timeout_s=30,
        )
    )

    return {
        "symbol": symbol,
        "at": time.strftime("%H:%M:%S", time.localtime()),
        "quote": results["quote"].data if results["quote"].ok else None,
        "intraday": results["intraday"].data if results["intraday"].ok else None,
        "series_1d": results["series_1d"].data if results["series_1d"].ok else None,
        "options": results["options"].data if results["options"].ok else None,
        "ms": int((time.monotonic() - started) * 1000),
    }


def _events(symbol, earnings, fundamentals, dividends=None, filings=None):
    """The calendar, or nothing. Never enough to fail the whole page."""
    try:
        return events.upcoming(symbol, horizon=180, earnings=earnings,
                               fundamentals=fundamentals, dividends=dividends,
                               filings=filings)
    except Exception as exc:                       # noqa: BLE001
        return {"events": [], "error": str(exc)}


@app.get("/api/events")
def market_events(horizon: int = 180) -> Dict[str, Any]:
    """The market-wide calendar on its own, with no ticker attached."""
    return events.upcoming(None, horizon=horizon)


@app.get("/api/target/{symbol}")
def by_target(symbol: str, price: float, expiry: str = "") -> Dict[str, Any]:
    """What to trade if you think the share lands on a particular price.

    A different question from "what setups exist", and it deserves
    different strikes. The catalogue picks its by delta, which is the
    right way to build a position when the view is about DIRECTION.
    When the view is about a PRICE, the strikes should come from it.
    """
    symbol = symbol.strip().upper()
    if not symbol or len(symbol) > 12:
        raise HTTPException(status_code=400, detail="bad symbol")
    if not price or price <= 0:
        raise HTTPException(status_code=400, detail="a target price is required")

    div = _div_yield(symbol)
    rate = options.risk_free_rate()
    board = options.fetch_options(symbol, max_expiries=8, div_yield=div,
                                  dividends=_div_schedule(symbol),
                                  only=expiry or None)
    if not board.get("available") or not board.get("expiries"):
        raise HTTPException(status_code=404,
                            detail=board.get("reason", "no chain"))

    want = expiry or ""
    exp = next((e for e in board["expiries"] if e["expiry"] == want),
               board["expiries"][0])
    spot = board.get("spot") or 0.0
    if not spot:
        raise HTTPException(status_code=400, detail=f"no price for {symbol}")

    vol = ((exp.get("stats") or {}).get("atm_iv") or 30.0) / 100.0
    out = preset_engine.by_target(exp["calls"], exp["puts"], exp["expiry"],
                                  spot, float(price), vol, rate, div)
    out["all_expiries"] = board.get("all_expiries") or []
    out["trading_days"] = exp.get("trading_days")
    out["vol_used"] = round(vol * 100, 2)
    return out


@app.get("/api/world")
def world(horizon: int = 30) -> Dict[str, Any]:
    """What is happening, rather than what is happening to one company.

    A ticker page answers the second question. Nothing answered the
    first, and it is the one you have before you open a ticker at all:
    whether the tape is risk-on, whether the Fed spoke this morning,
    whether the selling is in one name or in all of them.

    Three things, fetched together because none depends on the others:
    a row of index levels so "the market" is a set of numbers rather
    than a word, the headlines from fifteen market-wide feeds ranked
    by how much they look like they move everything at once, and the
    dates already known to be coming.
    """
    started = time.monotonic()

    def barometer() -> List[Dict[str, Any]]:
        rows: List[Dict[str, Any]] = []
        for sym, label, what in world_news.BAROMETER:
            try:
                q = quotes.fetch_quote(sym) or {}
            except Exception:                              # noqa: BLE001
                q = {}
            rows.append({
                "symbol": sym,
                "label": label,
                "what": what,
                "price": q.get("price"),
                "change_pct": q.get("change_pct"),
                # Said rather than left to be inferred: a reader should
                # not have to know that a rising VIX is the market
                # pricing more movement, not less.
                "note": ("higher means options are pricing a bigger month"
                         if sym == "^VIX" else ""),
            })
        return rows

    results = _result_map(
        fanout(
            {
                "news": world_news.headlines,
                "barometer": barometer,
                "calendar": lambda: events.upcoming(None, horizon=horizon),
            },
            timeout_s=30,
        )
    )

    news = results["news"].data if results["news"].ok else {}
    return {
        "at": time.strftime("%H:%M:%S", time.localtime()),
        "ms": int((time.monotonic() - started) * 1000),
        "barometer": results["barometer"].data if results["barometer"].ok else [],
        "headlines": news.get("items", [])[:60],
        "feeds_reached": news.get("feeds_reached", []),
        "feeds_failed": news.get("feeds_failed", []),
        "feeds_total": news.get("feeds_total", 0),
        "found": news.get("count", 0),
        "calendar": results["calendar"].data if results["calendar"].ok else None,
    }


@app.get("/api/ticker/{symbol}")
def ticker(symbol: str, articles: int = MAX_ARTICLES) -> Dict[str, Any]:
    """The whole picture for one ticker."""
    symbol = symbol.strip().upper()
    if not symbol or len(symbol) > 12:
        raise HTTPException(status_code=400, detail="invalid symbol")

    started = time.monotonic()

    # Stage 1 -- every source at once. A dead source degrades one tile.
    stage1 = _result_map(
        fanout(
            {
                "quote": lambda: quotes.fetch_quote(symbol),
                "fundamentals": lambda: quotes.fetch_fundamentals(symbol),
                "history": lambda: quotes.fetch_history(symbol),
                "intraday": lambda: quotes.fetch_intraday(symbol),
                "options": lambda: options.fetch_options(
                    symbol, div_yield=_div_yield(symbol),
                    dividends=_div_schedule(symbol)),
                "filings": lambda: sec_edgar.fetch_filings(symbol),
                "sec": lambda: sec_xbrl.fetch(symbol, sec_edgar.lookup_cik),
                "edgar_cal": lambda: sec_edgar.fetch_calendar(symbol),
                "holdings": lambda: holdings.fetch(symbol),
                "social": lambda: news_rss.stocktwits(symbol),
                "profile": lambda: deep.fetch_profile(symbol),
                "financials": lambda: deep.fetch_financials(symbol),
                "earnings": lambda: deep.fetch_earnings(symbol),
                "dividends": lambda: deep.fetch_dividends(symbol),
                "ownership": lambda: deep.fetch_ownership(symbol),
                "volume": lambda: deep.fetch_volume_profile(symbol),
                "long_history": lambda: deep.fetch_price_history_long(symbol),
                "series": lambda: quotes.fetch_series(symbol),
            },
            timeout_s=75,
        )
    )

    quote_data = stage1["quote"].data if stage1["quote"].ok else {}
    company = (quote_data or {}).get("name", "")

    # Stage 2 -- discovery needs the company name, so it follows the quote.
    discovery = fanout(
        {"discovery": lambda: news_rss.discover_all(symbol, company)}, timeout_s=40
    )[0]
    discovered = discovery.data if discovery.ok else []

    # Stage 3 -- full text, cheap tier first, bounded so no host gets
    # hammered.
    #
    # Ordered by how many feeds carried the story before it is cut to
    # the budget. Seven feeds now find sixty-odd articles and only a
    # couple of dozen can be read in the time a page has, so the ones
    # that get read should be the ones several outlets thought worth
    # running -- everybody carries an earnings miss and nobody carries
    # a sponsored post. Recency breaks the tie.
    ranked = sorted(
        discovered,
        key=lambda a: (a.get("feed_count") or 1, a.get("published") or ""),
        reverse=True)
    to_fetch = ranked[:articles]
    extract_started = time.monotonic()
    extracted = bounded_map(
        lambda item: extract(item["url"]).to_dict(),
        to_fetch,
        limit=EXTRACT_CONCURRENCY,
        key="article-extraction",
        min_interval_s=0.15,
    )

    usable: List[Dict[str, Any]] = []
    for item, result in zip(to_fetch, extracted):
        if not result:
            continue
        # Feed metadata is often better than scraped metadata -- keep both.
        result["published"] = result.get("published") or item.get("published")
        result["publisher"] = result.get("publisher") or item.get("publisher")
        result["title"] = result.get("title") or item.get("title")
        result["discovered_via"] = item.get("discovered_via")
        result["also_via"] = item.get("also_via", [])
        # How many feeds carried it. Rebuilt results only copied across
        # the fields that were named, so this was computed in discovery
        # and then dropped on the floor before anything could use it.
        result["feed_count"] = item.get("feed_count") or 1
        # A readable standfirst: the feed's own blurb if it wrote one, else the
        # opening of the article we extracted.
        feed_summary = (item.get("summary") or "").strip()
        body = (result.get("text") or "").replace("\n", " ").strip()
        result["excerpt"] = feed_summary or (body[:320] + ("..." if len(body) > 320 else ""))
        if result.get("text") and not result.get("error"):
            usable.append(result)

    extract_ms = int((time.monotonic() - extract_started) * 1000)

    # Stage 4 -- the part nothing off the shelf does.
    crossref: Dict[str, Any] = {"stories": [], "unique_claims": [], "stats": {}}
    if usable:
        crossref = cross_reference(usable, cluster(usable))

    tier_counts: Dict[str, int] = {}
    for article in usable:
        tier = article.get("tier") or "failed"
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    # Every article we found gets listed, including ones whose body we could
    # not extract -- a headline, a blurb and a working link is still a lead.
    extracted_by_url = {a["url"]: a for a in usable}
    feed: List[Dict[str, Any]] = []
    for item in discovered:
        got = extracted_by_url.get(item["url"])
        feed.append(
            {
                "url": item["url"],
                "title": (got or {}).get("title") or item.get("title"),
                "excerpt": (got or {}).get("excerpt") or (item.get("summary") or "")[:320],
                "publisher": (got or {}).get("publisher") or item.get("publisher"),
                "published": (got or {}).get("published") or item.get("published"),
                "authors": (got or {}).get("authors") or [],
                "chars": (got or {}).get("chars", 0),
                "tier": (got or {}).get("tier"),
                "discovered_via": item.get("discovered_via"),
                "also_via": item.get("also_via", []),
                # How many of the seven feeds carried this story.
                # Computed in discovery, and dropped twice on the way
                # out -- once by the extractor rebuild and again here,
                # where the response is a third projection listing only
                # the fields somebody remembered to name.
                "feed_count": item.get("feed_count") or 1,
                # How likely this headline is to have moved the price,
                # and the reasons behind the number -- a score on its
                # own is one more thing to take on trust.
                "moving": news_rss.price_moving({
                    "title": (got or {}).get("title") or item.get("title"),
                    "excerpt": item.get("summary"),
                    "feed_count": item.get("feed_count"),
                    "published": (got or {}).get("published") or item.get("published"),
                }),
                "full_text": bool(got),
            }
        )

    return {
        "symbol": symbol,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "quote": quote_data,
        "fundamentals": stage1["fundamentals"].data if stage1["fundamentals"].ok else None,
        "history": stage1["history"].data if stage1["history"].ok else None,
        "intraday": stage1["intraday"].data if stage1["intraday"].ok else None,
        "options": stage1["options"].data if stage1["options"].ok else None,
        "filings": stage1["filings"].data if stage1["filings"].ok else None,
        "sec": stage1["sec"].data if stage1["sec"].ok else None,
        "holdings": stage1["holdings"].data if stage1["holdings"].ok else None,
        "social": stage1["social"].data if stage1["social"].ok else None,
        "profile": stage1["profile"].data if stage1["profile"].ok else None,
        "financials": stage1["financials"].data if stage1["financials"].ok else None,
        "earnings": stage1["earnings"].data if stage1["earnings"].ok else None,
        "ownership": stage1["ownership"].data if stage1["ownership"].ok else None,
        "volume": stage1["volume"].data if stage1["volume"].ok else None,
        "long_history": stage1["long_history"].data if stage1["long_history"].ok else None,
        "series": stage1["series"].data if stage1["series"].ok else None,
        "news": {
            "discovered": len(discovered),
            "extracted": len(usable),
            "failed": len(to_fetch) - len(usable),
            "articles": feed,
        },
        "dividends": stage1["dividends"].data if stage1["dividends"].ok else None,
        "events": _events(
            symbol,
            stage1["earnings"].data if stage1["earnings"].ok else None,
            stage1["fundamentals"].data if stage1["fundamentals"].ok else None,
            stage1["dividends"].data if stage1["dividends"].ok else None,
            stage1["edgar_cal"].data if stage1["edgar_cal"].ok else None,
        ),
        "crossref": crossref,
        "diagnostics": {
            "total_ms": int((time.monotonic() - started) * 1000),
            "extract_ms": extract_ms,
            "sources": [r.to_dict() | {"data": None} for r in stage1.values()],
            "discovery_ms": discovery.elapsed_ms,
            "tiers_used": tier_counts,
            "errors": [
                {"source": r.source, "error": r.error}
                for r in stage1.values()
                if not r.ok
            ],
        },
    }


@app.middleware("http")
async def no_cache_static(request, call_next):
    """Serve the front-end uncached.

    This is a local tool served off disk, so there is nothing to gain from
    caching and everything to lose: a stale app.js silently shows you old
    behaviour and you debug a bug you already fixed.
    """
    response = await call_next(request)
    if request.url.path.startswith("/static") or request.url.path == "/":
        response.headers["Cache-Control"] = "no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
    return response


if FRONTEND.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND)), name="static")

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(FRONTEND / "index.html"))
