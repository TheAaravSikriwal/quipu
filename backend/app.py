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
from screener import backtest as screen_backtest, rank as screen_rank, store as screen_store, universe as screen_universe  # noqa: E402
from sources import deep, events, holdings, news_rss, options, quotes, sec_edgar, sec_xbrl, symbols  # noqa: E402

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
    put_at = {p["strike"]: p for p in puts}

    def _two_sided(r):
        return r.get("bid") and r.get("ask") and r["ask"] > r["bid"]

    spot = spot_ref
    spot_source = "quote"
    pairs = [(c, put_at[c["strike"]]) for c in calls
             if c["strike"] in put_at and _two_sided(c) and _two_sided(put_at[c["strike"]])]
    if pairs and spot_quoted:
        # The nearest-the-money pair, where the spread is tightest and the
        # parity read is therefore cleanest.
        c, p = min(pairs, key=lambda cp: abs(cp[0]["strike"] - spot_quoted))
        # Parity has to be written against whichever dividend model the
        # board was priced under, or the identity is being solved for the
        # wrong unknown. Escrowed:  C - P = S_adj - K.e^(-rT), and S_adj
        # already has the dividends removed. Continuous: the old form
        # with the e^(-qT) term.
        forward = (c["mark"] - p["mark"]) + c["strike"] * math.exp(-rate * years)
        implied = (forward if esc["model"] == "discrete"
                   else forward / math.exp(-div * years))
        # Only trust it if it is close; a wild number means a broken quote,
        # not a stale one.
        if spot_ref and abs(implied / spot_ref - 1) < 0.03:
            spot, spot_source = implied, f"put-call parity at {c['strike']:g}"

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
    analysis["vol_used"] = round(vol * 100, 2)
    analysis["rate"] = round(rate * 100, 3)
    analysis["div_yield"] = round(div * 100, 3)
    analysis["earnings"] = earnings
    analysis["marks_live"] = sum(
        1 for l in analysis["legs"]
        if l["kind"] != "stock"
        and f"{l['kind']}:{float(l['strike'])}:{l['expiry']}" in marks)
    analysis["at"] = time.strftime("%H:%M:%S", time.localtime())
    return analysis


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


def _events(symbol, earnings, fundamentals):
    """The calendar, or nothing. Never enough to fail the page over."""
    try:
        return events.upcoming(symbol, horizon=180, earnings=earnings,
                               fundamentals=fundamentals)
    except Exception as exc:                       # noqa: BLE001
        return {"events": [], "error": str(exc)}


@app.get("/api/events")
def market_events(horizon: int = 180) -> Dict[str, Any]:
    """The market-wide calendar on its own, with no ticker attached."""
    return events.upcoming(None, horizon=horizon)


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

    # Stage 3 -- full text, cheap tier first, bounded so no host gets hammered.
    to_fetch = discovered[:articles]
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
