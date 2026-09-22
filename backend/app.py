"""quipu API -- everything knowable about one ticker, in one response.

Pipeline for a single search:

  1. fan out across every source at once (quote, options, filings, social, news
     discovery) -- wide across sources, throttled within each
  2. extract full text for the discovered article URLs, bounded concurrency
  3. cluster the articles into stories, then diff their claims
  4. return the lot, with per-source timings so a slow provider is visible
"""

from __future__ import annotations

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
from screener import backtest as screen_backtest, rank as screen_rank, store as screen_store, universe as screen_universe  # noqa: E402
from sources import deep, news_rss, options, quotes, sec_edgar, symbols  # noqa: E402

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
        chains = options.fetch_options(symbol, max_expiries=8, div_yield=div)
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
                "options": lambda: options.fetch_options(
                    symbol, max_expiries=2, div_yield=_div_yield(symbol)),
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
                "options": lambda: options.fetch_options(symbol, div_yield=_div_yield(symbol)),
                "filings": lambda: sec_edgar.fetch_filings(symbol),
                "social": lambda: news_rss.stocktwits(symbol),
                "profile": lambda: deep.fetch_profile(symbol),
                "financials": lambda: deep.fetch_financials(symbol),
                "earnings": lambda: deep.fetch_earnings(symbol),
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
