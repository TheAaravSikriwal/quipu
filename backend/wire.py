"""Which data sources answered -- the lights along the bottom of a search.

Every outbound request, whichever library makes it (requests for most
sources, curl_cffi underneath yfinance), is noted against the provider
its host belongs to: when, and whether it came back. The page reads that
as one light per provider, green for answered and red for anything else.

A search only touches some providers -- the Fed's calendar is cached for
the day, SSGA only matters for a SPDR fund -- and a light with no recent
traffic behind it would be a guess. So a provider nobody has asked for a
while gets one small request of its own, at most every few minutes
however many people are looking, and its light says what that found.
"""

from __future__ import annotations

import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlsplit

#: How long a real answer stands before the provider is checked again.
STALE_S = 600
#: The least time between two checks of one provider.
CHECK_EVERY_S = 300

BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept": "application/json, text/xml, */*",
}
TOOL = {"User-Agent": "quipu/0.1 (personal research tool)"}

# (id, name, [(host, path prefixes or None for any path)], key env var)
#
# First match wins, so the narrow Yahoo rule sits above the broad one.
# Paths are pinned wherever a host also serves article pages: the article
# extractor reads cnbc.com and nasdaq.com stories too, and one paywalled
# story is not CNBC's feed being down.
PROVIDERS: List[Tuple[str, str, List[Tuple[str, Optional[Tuple[str, ...]]]], Optional[str]]] = [
    ("yahoo-quotes", "Yahoo quotes & options",
     [("finance.yahoo.com", ("/v10/finance/quoteSummary", "/v7/finance/options",
                             "/v7/finance/quote", "/v1/test/getcrumb"))], None),
    ("yahoo", "Yahoo Finance",
     [("query1.finance.yahoo.com", None), ("query2.finance.yahoo.com", None),
      ("feeds.finance.yahoo.com", None), ("finance.yahoo.com", ("/news/rssindex",))], None),
    ("cboe", "Cboe", [("cdn.cboe.com", ("/api/",))], None),
    ("nasdaq", "Nasdaq", [("api.nasdaq.com", None), ("www.nasdaq.com", ("/feed/",))], None),
    ("alpaca", "Alpaca", [("alpaca.markets", None)], None),
    ("edgar", "SEC EDGAR", [("www.sec.gov", ("/files/", "/cgi-bin/", "/news/")),
                            ("data.sec.gov", ("/submissions/",))], None),
    ("xbrl", "SEC XBRL", [("data.sec.gov", ("/api/xbrl/",))], None),
    ("fed", "Federal Reserve", [("federalreserve.gov", None)], None),
    ("bls", "BLS", [("bls.gov", None)], None),
    ("bea", "BEA", [("bea.gov", None)], None),
    ("forexfactory", "ForexFactory", [("faireconomy.media", None)], None),
    ("google", "Google News", [("news.google.com", ("/rss",))], None),
    ("bing", "Bing News", [("www.bing.com", ("/news/",))], None),
    ("marketwatch", "MarketWatch", [("feeds.content.dowjones.io", None)], None),
    ("cnbc", "CNBC", [("search.cnbc.com", None)], None),
    ("seekingalpha", "Seeking Alpha", [("seekingalpha.com", ("/api/",))], None),
    ("investing", "Investing.com", [("www.investing.com", ("/rss/",))], None),
    ("stocktwits", "StockTwits", [("api.stocktwits.com", None)], None),
    ("finnhub", "Finnhub", [("finnhub.io", None)], "FINNHUB_API_KEY"),
    ("ssga", "SSGA", [("www.ssga.com", None)], None),
    ("nasdaqtrader", "Nasdaq Trader", [("nasdaqtrader.com", None)], None),
    ("firecrawl", "Firecrawl", [("api.firecrawl.dev", None)], "FIRECRAWL_API_KEY"),
]
NAMES = {pid: name for pid, name, _, _ in PROVIDERS}


def provider_of(url: str) -> Optional[str]:
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host, path = (parts.hostname or "").lower(), parts.path or "/"
    for pid, _, rules, _ in PROVIDERS:
        for suffix, prefixes in rules:
            if host != suffix and not host.endswith("." + suffix):
                continue
            if prefixes is None or path.startswith(prefixes):
                return pid
    return None


# ---- the record --------------------------------------------------------

_LOCK = threading.Lock()
_LAST: Dict[str, Dict[str, Any]] = {}
_FAILS: Dict[str, Tuple[float, Optional[int]]] = {}
_CHECKED: Dict[str, float] = {}
_LOCAL = threading.local()


def answered(code: Optional[int]) -> bool:
    # A 404 is the provider answering "nothing for that symbol" -- an ETF
    # has no XBRL facts -- which is it working, not it being down.
    return code is not None and (code < 400 or code == 404)


def record(url: str, code: Optional[int], error: Optional[str] = None) -> None:
    pid = provider_of(url)
    if not pid:
        return
    now = time.time()
    ok = answered(code)
    with _LOCK:
        _LAST[pid] = {"ok": ok, "code": code, "error": None if ok else (error or f"HTTP {code}"),
                      "at": now, "check": bool(getattr(_LOCAL, "checking", False))}
        if not ok:
            _FAILS[pid] = (now, code)


def failed_since(pid: str, since: float) -> Optional[int]:
    """The status of the last refusal from `pid` after `since`, if any
    (0 when it failed without one, e.g. a timeout)."""
    with _LOCK:
        hit = _FAILS.get(pid)
    if hit and hit[0] >= since:
        return hit[1] or 0
    return None


def mark(pid: str, ok: bool, error: Optional[str] = None, code: Optional[int] = None) -> None:
    """Note an outcome that no single HTTP status carries -- Yahoo handing
    back 200 with an empty body after refusing the crumb."""
    with _LOCK:
        _LAST[pid] = {"ok": ok, "code": code, "error": None if ok else error,
                      "at": time.time(), "check": bool(getattr(_LOCAL, "checking", False))}


# ---- listening -----------------------------------------------------------

_INSTALLED = False


def install() -> None:
    """Wrap the two HTTP clients once, at the class, so every session any
    library makes -- including the ones yfinance builds itself -- reports in."""
    global _INSTALLED
    if _INSTALLED:
        return
    _INSTALLED = True

    import requests

    send = requests.Session.send

    def watched_send(self, request, **kwargs):
        try:
            resp = send(self, request, **kwargs)
        except Exception as exc:                            # noqa: BLE001
            record(request.url, None, type(exc).__name__)
            raise
        record(request.url, resp.status_code)
        return resp

    requests.Session.send = watched_send

    try:
        from curl_cffi import requests as curl
    except ImportError:
        return

    creq = curl.Session.request

    def watched_request(self, method, url, *args, **kwargs):
        try:
            resp = creq(self, method, url, *args, **kwargs)
        except Exception as exc:                            # noqa: BLE001
            record(url, None, type(exc).__name__)
            raise
        record(url, resp.status_code)
        return resp

    curl.Session.request = watched_request


# ---- checking the quiet ones ---------------------------------------------

def _get(url: str, headers: Optional[Dict[str, str]] = None) -> None:
    import requests
    # Streamed and dropped after the headers: the answer is the status,
    # and the Nasdaq Trader and SSGA files run to megabytes.
    with requests.get(url, headers=headers or BROWSER, timeout=8, stream=True):
        pass


def _yahoo_quotes() -> None:
    from sources import yahoo
    yahoo.info("SPY", check=True)


def _alpaca() -> None:
    from sources import alpaca
    st = alpaca.status()
    if not st["enabled"]:
        mark("alpaca", False, st["why"])
        return
    import requests
    head = alpaca._credentials() or {}
    with requests.get(f"{alpaca.DATA}/v2/stocks/SPY/snapshot?feed=iex",
                      headers=head, timeout=8, stream=True):
        pass


def _edgar() -> None:
    from sources import sec_edgar
    _get("https://www.sec.gov/files/company_tickers.json", sec_edgar.HEADERS)


def _xbrl() -> None:
    from sources import sec_xbrl
    _get("https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json", sec_xbrl.UA)


def _finnhub() -> None:
    _get(f"https://finnhub.io/api/v1/quote?symbol=SPY&token={os.getenv('FINNHUB_API_KEY')}")


def _firecrawl() -> None:
    # Reachability only: a scrape would spend credits to turn a light on.
    _get("https://api.firecrawl.dev/")
    with _LOCK:
        last = _LAST.get("firecrawl")
    if last and not last["ok"] and last["code"] in (401, 404, 405):
        mark("firecrawl", True, code=last["code"])


CHECKS: Dict[str, Callable[[], None]] = {
    "yahoo-quotes": _yahoo_quotes,
    "yahoo": lambda: _get("https://query1.finance.yahoo.com/v8/finance/chart/SPY?range=1d&interval=1d"),
    "cboe": lambda: _get("https://cdn.cboe.com/api/global/delayed_quotes/quotes/SPY.json"),
    "nasdaq": lambda: _get("https://api.nasdaq.com/api/quote/SPY/info?assetclass=etf"),
    "alpaca": _alpaca,
    "edgar": _edgar,
    "xbrl": _xbrl,
    "fed": lambda: _get("https://www.federalreserve.gov/feeds/press_all.xml", TOOL),
    "bls": lambda: _get("https://www.bls.gov/feed/bls_latest.rss", TOOL),
    "bea": lambda: _get("https://apps.bea.gov/rss/rss.xml", TOOL),
    "forexfactory": lambda: _get("https://nfs.faireconomy.media/ff_calendar_thisweek.json", TOOL),
    "google": lambda: _get("https://news.google.com/rss/search?q=SPY&hl=en-US&gl=US&ceid=US:en", TOOL),
    "bing": lambda: _get("https://www.bing.com/news/search?q=SPY&format=rss", TOOL),
    "marketwatch": lambda: _get("https://feeds.content.dowjones.io/public/rss/mw_topstories", TOOL),
    "cnbc": lambda: _get("https://search.cnbc.com/rs/search/combinedcms/view.xml"
                         "?partnerId=wrss01&id=100003114", TOOL),
    "seekingalpha": lambda: _get("https://seekingalpha.com/api/sa/combined/SPY.xml", TOOL),
    "investing": lambda: _get("https://www.investing.com/rss/news_25.rss", TOOL),
    "stocktwits": lambda: _get("https://api.stocktwits.com/api/2/streams/symbol/SPY.json", TOOL),
    "finnhub": _finnhub,
    "ssga": lambda: _get("https://www.ssga.com/us/en/intermediary/library-content/products/"
                         "fund-data/etfs/us/holdings-daily-us-en-spy.xlsx"),
    "nasdaqtrader": lambda: _get("https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqtraded.txt"),
    "firecrawl": _firecrawl,
}

# ForexFactory blocks anyone asking more than a couple of times in five
# minutes, and the calendar code already asks; checking it as often as the
# rest would be the thing that got it blocked.
CHECK_EVERY = {"forexfactory": 1800, "yahoo-quotes": 600}

_ROUND = threading.Lock()


def _run_check(pid: str) -> None:
    _LOCAL.checking = True
    try:
        CHECKS[pid]()
    except Exception as exc:                                # noqa: BLE001
        with _LOCK:
            last = _LAST.get(pid)
        # The request itself was recorded on the way out; only something
        # that failed before one was made needs noting here.
        if not last or time.time() - last["at"] > 30:
            mark(pid, False, type(exc).__name__)
    finally:
        _LOCAL.checking = False


def _keyless(pid: str) -> Optional[str]:
    for p, _, _, env in PROVIDERS:
        if p == pid and env and not os.getenv(env):
            return f"no key ({env} not set)"
    return None


def _due(now: float) -> List[str]:
    out = []
    with _LOCK:
        for pid, *_ in PROVIDERS:
            if _keyless(pid):
                continue
            last = _LAST.get(pid)
            if last and now - last["at"] < STALE_S:
                continue
            if now - _CHECKED.get(pid, 0) < CHECK_EVERY.get(pid, CHECK_EVERY_S):
                continue
            out.append(pid)
    return out


def check_quiet() -> None:
    """Ask every provider with nothing recent behind its light. One round
    at a time: a second caller waits for the first and reads its results."""
    with _ROUND:
        now = time.time()
        due = _due(now)
        if not due:
            return
        with _LOCK:
            for pid in due:
                _CHECKED[pid] = now
        with ThreadPoolExecutor(max_workers=min(len(due), 12)) as pool:
            list(pool.map(_run_check, due))


def snapshot() -> List[Dict[str, Any]]:
    now = time.time()
    rows = []
    with _LOCK:
        for pid, name, _, _ in PROVIDERS:
            why = _keyless(pid)
            last = _LAST.get(pid)
            if why:
                rows.append({"id": pid, "name": name, "ok": False, "error": why})
                continue
            if not last:
                rows.append({"id": pid, "name": name, "ok": False, "error": "not reached yet"})
                continue
            rows.append({
                "id": pid, "name": name, "ok": last["ok"], "code": last["code"],
                "error": last["error"], "ago": int(now - last["at"]),
                "via": "check" if last["check"] else "search",
            })
    return rows
