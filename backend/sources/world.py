"""The market as a whole, rather than one company in it.

A ticker page answers "what is happening to this". Nothing answered
"what is happening", and that is the question you have first: whether
the tape is risk-on, whether the Fed spoke this morning, whether the
selling is in one name or in everything.

Every feed here was fetched before it was written down. A source list
assembled from memory is half dead links, and a dead link in a news
pipeline does not announce itself -- it just quietly returns nothing
while the page looks fine.

All free, none needs a key.
"""

from __future__ import annotations

import concurrent.futures as _cf
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import feedparser
import requests

UA = "quipu/0.1 (personal research tool)"
TIMEOUT = 12

#: Grouped by what the feed is FOR, because "news" covers a wire story
#: about a merger and a Federal Reserve rate decision, and those are
#: not the same kind of fact. The group travels with each item so the
#: page can weight them differently.
FEEDS: List[Dict[str, str]] = [
    # --- the policy that moves everything at once
    {"id": "fed_monetary", "group": "policy", "weight": "3",
     "name": "Federal Reserve, monetary policy",
     "url": "https://www.federalreserve.gov/feeds/press_monetary.xml"},
    {"id": "fed_all", "group": "policy", "weight": "2",
     "name": "Federal Reserve, all releases",
     "url": "https://www.federalreserve.gov/feeds/press_all.xml"},
    {"id": "sec_press", "group": "policy", "weight": "2",
     "name": "SEC press releases",
     "url": "https://www.sec.gov/news/pressreleases.rss"},

    # --- the numbers the policy responds to
    {"id": "bls", "group": "data", "weight": "3",
     "name": "Bureau of Labor Statistics",
     "url": "https://www.bls.gov/feed/bls_latest.rss"},
    {"id": "bea", "group": "data", "weight": "2",
     "name": "Bureau of Economic Analysis",
     "url": "https://apps.bea.gov/rss/rss.xml"},

    # --- the tape
    {"id": "cnbc_top", "group": "markets", "weight": "1",
     "name": "CNBC top news",
     "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml"
            "?partnerId=wrss01&id=100003114"},
    {"id": "cnbc_econ", "group": "markets", "weight": "2",
     "name": "CNBC economy",
     "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml"
            "?partnerId=wrss01&id=20910258"},
    {"id": "mw_top", "group": "markets", "weight": "1",
     "name": "MarketWatch top stories",
     "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories"},
    {"id": "mw_pulse", "group": "markets", "weight": "1",
     "name": "MarketWatch market pulse",
     "url": "https://feeds.content.dowjones.io/public/rss/mw_marketpulse"},
    {"id": "mw_realtime", "group": "markets", "weight": "1",
     "name": "MarketWatch real time",
     "url": "https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines"},
    {"id": "yahoo", "group": "markets", "weight": "1",
     "name": "Yahoo Finance",
     "url": "https://finance.yahoo.com/news/rssindex"},
    {"id": "investing_econ", "group": "markets", "weight": "1",
     "name": "Investing.com economy",
     "url": "https://www.investing.com/rss/news_14.rss"},

    # --- wires, reached through a search index because their own
    #     feeds are either gone or behind a key
    {"id": "reuters", "group": "wire", "weight": "2", "name": "Reuters business",
     "url": "https://news.google.com/rss/search?q="
            + urllib.parse.quote("site:reuters.com business OR markets")
            + "&hl=en-US&gl=US&ceid=US:en"},
    {"id": "ap", "group": "wire", "weight": "2", "name": "Associated Press business",
     "url": "https://news.google.com/rss/search?q="
            + urllib.parse.quote("site:apnews.com business OR economy")
            + "&hl=en-US&gl=US&ceid=US:en"},
    {"id": "ft", "group": "wire", "weight": "2", "name": "Financial Times markets",
     "url": "https://news.google.com/rss/search?q="
            + urllib.parse.quote("site:ft.com markets")
            + "&hl=en-US&gl=US&ceid=US:en"},
]

#: What the index tickers stand for. Shown as a row so "the market" is
#: a set of numbers rather than a word.
BAROMETER = [
    ("SPY", "S&P 500", "the broad US market"),
    ("QQQ", "Nasdaq 100", "the big technology names"),
    ("IWM", "Russell 2000", "smaller US companies"),
    ("DIA", "Dow Jones", "thirty large industrials"),
    ("^VIX", "VIX", "what options say the next month holds"),
    ("TLT", "20-year Treasuries", "the long end of the bond market"),
    ("GLD", "Gold", "where money goes when it is nervous"),
    ("USO", "Crude oil", "the input price for everything physical"),
]

#: Words that tend to appear in a headline that moves a whole market
#: rather than one company. Used only to rank, never to exclude.
LOUD = re.compile(
    r"\b(fed|fomc|rate cut|rate hike|inflation|cpi|ppi|jobs report|payroll|"
    r"unemployment|gdp|recession|tariff|sanction|default|downgrade|"
    r"shutdown|stimulus|yield|treasur|powell|ecb|boj|opec|war|strike)\b",
    re.I)


def _strip(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _when(entry: Any) -> Optional[str]:
    for key in ("published_parsed", "updated_parsed"):
        value = getattr(entry, key, None) or entry.get(key)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                continue
    return None


def _one(feed: Dict[str, str], limit: int) -> List[Dict[str, Any]]:
    """One feed, fetched with a deadline.

    feedparser does its own fetch and that fetch has no timeout, which
    is fine until one of fifteen hosts stops answering and takes the
    whole page with it.
    """
    resp = requests.get(feed["url"], headers={"User-Agent": UA}, timeout=TIMEOUT)
    resp.raise_for_status()
    parsed = feedparser.parse(resp.content)

    out = []
    for entry in parsed.entries[:limit]:
        link = entry.get("link")
        title = _strip(entry.get("title", ""))
        if not link or not title:
            continue
        # Several feeds put the headline in the summary field as
        # well. Printing it twice under itself is not a standfirst,
        # it is the same sentence taking up two lines.
        summary = _strip(entry.get("summary", ""))
        if _key(summary) == _key(title):
            summary = ""

        out.append({
            "url": link,
            "title": title,
            "summary": summary[:400],
            "published": _when(entry),
            "source": feed["name"],
            "source_id": feed["id"],
            "group": feed["group"],
            "weight": int(feed["weight"]),
            "publisher": urllib.parse.urlparse(link).netloc.replace("www.", ""),
        })
    return out


def _key(title: str) -> str:
    """A headline reduced to what makes it the same story."""
    t = re.sub(r"[^a-z0-9 ]+", " ", (title or "").lower())
    return " ".join([w for w in t.split() if len(w) > 2][:9])


def headlines(limit_per_feed: int = 20) -> Dict[str, Any]:
    """Every market-wide feed, pooled, deduplicated and ranked."""
    pooled: List[Dict[str, Any]] = []
    reached: List[str] = []
    failed: List[str] = []

    with _cf.ThreadPoolExecutor(max_workers=len(FEEDS)) as pool:
        jobs = {pool.submit(_one, f, limit_per_feed): f for f in FEEDS}
        for fut in _cf.as_completed(jobs, timeout=TIMEOUT + 8):
            f = jobs[fut]
            try:
                got = fut.result() or []
            except Exception:
                failed.append(f["id"])
                continue
            if got:
                reached.append(f["id"])
            pooled.extend(got)

    # One story, however many places ran it. The count of places is
    # kept, because it is the cheapest measure of whether a headline
    # matters that does not require reading it.
    merged: Dict[str, Dict[str, Any]] = {}
    for item in pooled:
        k = _key(item["title"])
        if not k:
            continue
        first = merged.get(k)
        if first is None:
            item["carried_by"] = [item["source"]]
            merged[k] = item
            continue
        if item["source"] not in first["carried_by"]:
            first["carried_by"].append(item["source"])
        # Keep the heaviest provenance: a Fed release and a blog post
        # about it are the same story, and the release is the source.
        if item["weight"] > first["weight"]:
            first.update({k2: item[k2] for k2 in
                          ("url", "source", "source_id", "group", "weight",
                           "publisher", "summary")})

    items = list(merged.values())
    for it in items:
        it["feeds"] = len(it["carried_by"])
        # Ranked, not filtered. A headline nobody else ran can still be
        # the one that matters, so a low score buries it rather than
        # dropping it.
        it["loud"] = bool(LOUD.search(it["title"]))
        it["score"] = it["weight"] * 2 + it["feeds"] + (3 if it["loud"] else 0)

    items.sort(key=lambda a: (a["score"], a.get("published") or ""), reverse=True)
    return {
        "items": items,
        "count": len(items),
        "feeds_reached": sorted(reached),
        "feeds_failed": sorted(failed),
        "feeds_total": len(FEEDS),
    }
