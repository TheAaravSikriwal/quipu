"""Article discovery -- finding every URL worth reading about a ticker.

Discovery is the weak link, not extraction. A single feed returns whatever the
publisher felt like tagging; several feeds pooled and deduplicated by URL cover
far more ground. All of these are free and need no API key.
"""

from __future__ import annotations

import os
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import concurrent.futures as _cf

import feedparser
import requests

UA = "quipu/0.1 (personal research tool)"
TIMEOUT = 15


def _parse_date(entry: Any) -> Optional[str]:
    for key in ("published_parsed", "updated_parsed"):
        value = getattr(entry, key, None) or entry.get(key)
        if value:
            try:
                return datetime(*value[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                continue
    return None


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "").strip()


def _from_feed(url: str, source: str, limit: int) -> List[Dict[str, Any]]:
    """One feed, fetched with a deadline and then parsed.

    feedparser.parse(url) does its own fetch, and that fetch has NO
    TIMEOUT. With two feeds in series that was a slow page; with seven
    in parallel it is a hung one, because a single unresponsive host
    holds the whole pool open and the page waits on it forever.
    Requests does the fetching now, so every feed has a deadline, and
    a host that will not answer costs the reader fifteen seconds
    rather than the article list.
    """
    resp = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    items: List[Dict[str, Any]] = []
    for entry in feed.entries[:limit]:
        link = entry.get("link")
        if not link:
            continue
        items.append(
            {
                "url": link,
                "title": _strip_html(entry.get("title", "")),
                "summary": _strip_html(entry.get("summary", ""))[:600],
                "published": _parse_date(entry),
                "discovered_via": source,
                "publisher": (entry.get("source", {}) or {}).get("title")
                or urllib.parse.urlparse(link).netloc,
            }
        )
    return items


def yahoo_rss(symbol: str, limit: int = 25) -> List[Dict[str, Any]]:
    """Yahoo Finance per-ticker headline feed."""
    url = (
        "https://feeds.finance.yahoo.com/rss/2.0/headline"
        f"?s={urllib.parse.quote(symbol)}&region=US&lang=en-US"
    )
    return _from_feed(url, "yahoo_rss", limit)


def google_news_rss(symbol: str, company: str = "", limit: int = 25) -> List[Dict]:
    """Google News search feed. Wider reach than any single publisher."""
    query = f'"{company}" OR "{symbol}" stock' if company else f"{symbol} stock"
    url = (
        "https://news.google.com/rss/search?q="
        + urllib.parse.quote(query)
        + "&hl=en-US&gl=US&ceid=US:en"
    )
    return _from_feed(url, "google_news", limit)


def seeking_alpha(symbol: str, limit: int = 25) -> List[Dict[str, Any]]:
    """Seeking Alpha's per-ticker feed: news and analysis together.

    Carries commentary the wires do not, which is worth having and
    worth labelling -- an opinion piece and a filing are not the same
    kind of thing and the evidence class on the panel says so.
    """
    url = f"https://seekingalpha.com/api/sa/combined/{urllib.parse.quote(symbol)}.xml"
    return _from_feed(url, "seeking_alpha", limit)


def nasdaq_rss(symbol: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Nasdaq's own per-ticker feed."""
    url = ("https://www.nasdaq.com/feed/rssoutbound?symbol="
           + urllib.parse.quote(symbol))
    return _from_feed(url, "nasdaq", limit)


def bing_news(symbol: str, company: str = "", limit: int = 20) -> List[Dict[str, Any]]:
    """Bing's news index, as RSS.

    Indexes a different slice of the web from Google, which is the
    entire reason it is here: two search engines miss different things,
    and a story only one of them found is still a story.
    """
    query = f'"{company}" stock' if company else f"{symbol} stock"
    url = ("https://www.bing.com/news/search?q="
           + urllib.parse.quote(query) + "&format=RSS")
    return _from_feed(url, "bing_news", limit)


def investing_com(limit: int = 20) -> List[Dict[str, Any]]:
    """Investing.com's market news. Not per-ticker, so it is filtered
    by the caller against the symbol and the company name."""
    return _from_feed("https://www.investing.com/rss/news_25.rss",
                      "investing", limit)


def stocktwits(symbol: str, limit: int = 30) -> Dict[str, Any]:
    """Retail chatter and its bullish/bearish tag. Free, no key, rate-limited."""
    url = f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
    response = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    response.raise_for_status()
    payload = response.json()

    messages, bull, bear = [], 0, 0
    for message in (payload.get("messages") or [])[:limit]:
        sentiment = ((message.get("entities") or {}).get("sentiment") or {}).get("basic")
        if sentiment == "Bullish":
            bull += 1
        elif sentiment == "Bearish":
            bear += 1
        messages.append(
            {
                "body": (message.get("body") or "")[:400],
                "created_at": message.get("created_at"),
                "user": (message.get("user") or {}).get("username"),
                "followers": (message.get("user") or {}).get("followers"),
                "sentiment": sentiment,
            }
        )

    tagged = bull + bear
    return {
        "messages": messages,
        "bullish": bull,
        "bearish": bear,
        "bull_pct": round((bull / tagged) * 100, 1) if tagged else None,
        "total": len(messages),
    }


def finnhub_news(symbol: str, limit: int = 40) -> List[Dict[str, Any]]:
    """Company news from Finnhub. Skipped unless FINNHUB_API_KEY is set."""
    key = os.getenv("FINNHUB_API_KEY")
    if not key:
        raise RuntimeError("FINNHUB_API_KEY not set")

    today = datetime.now(timezone.utc).date()
    start = today.replace(day=1) if today.day > 7 else today.replace(month=max(today.month - 1, 1), day=1)
    url = (
        "https://finnhub.io/api/v1/company-news"
        f"?symbol={symbol}&from={start}&to={today}&token={key}"
    )
    response = requests.get(url, headers={"User-Agent": UA}, timeout=TIMEOUT)
    response.raise_for_status()

    items = []
    for row in (response.json() or [])[:limit]:
        published = None
        if row.get("datetime"):
            published = datetime.fromtimestamp(
                row["datetime"], tz=timezone.utc
            ).isoformat()
        items.append(
            {
                "url": row.get("url"),
                "title": row.get("headline", ""),
                "summary": (row.get("summary") or "")[:600],
                "published": published,
                "discovered_via": "finnhub",
                "publisher": row.get("source"),
            }
        )
    return [i for i in items if i["url"]]


def _headline_key(title: str) -> str:
    """A headline reduced to what makes it the same story.

    A wire piece runs on a dozen sites under one title, each with its
    own URL and its own trailing publisher name, so deduplicating by
    URL alone left the same sentence on the page a dozen times.
    """
    t = re.sub(r"[^a-z0-9 ]+", " ", (title or "").lower())
    words = [w for w in t.split() if len(w) > 2]
    return " ".join(words[:9])


def _about(items: List[Dict[str, Any]], symbol: str,
           company: str = "") -> List[Dict[str, Any]]:
    """Keep only the items that mention the company at all.

    Some good feeds are market-wide rather than per-ticker. Pooling one
    of those unfiltered would bury the company under general news,
    which is the opposite of what a ticker page is for.
    """
    names = [symbol.lower()]
    if company:
        names.append(company.lower().split()[0])
    out = []
    for it in items:
        hay = f'{it.get("title", "")} {it.get("summary", "")}'.lower()
        if any(n in hay for n in names if len(n) > 1):
            out.append(it)
    return out


#: Words that appear in a headline that moves ONE company's price,
#: as opposed to one that merely mentions it. Deliberately narrow: an
#: analyst's opinion piece and an earnings miss both mention a
#: company, and only one of them reprices it.
#:
#: Grouped by how hard each tends to hit, which is not a forecast --
#: it is what these words have historically been attached to.
MOVERS = {
    3: re.compile(
        r"\b(earnings|results|guidance|profit warning|beats|misses|"
        r"acquisition|acquire|merger|takeover|buyout|bankrupt|chapter 11|"
        r"fda|approval|recall|halted|halt|investigation|fraud|"
        r"restate|delist|short.?seller)\b", re.I),
    2: re.compile(
        r"\b(upgrade|downgrade|price target|initiated|dividend|buyback|"
        r"split|offering|dilut|lawsuit|settle|subpoena|ceo|cfo|resign|"
        r"steps down|layoff|contract|deal|partnership|patent)\b", re.I),
    1: re.compile(
        r"\b(outlook|forecast|analyst|rating|stake|insider|filing|"
        r"conference|launch|expansion)\b", re.I),
}


def price_moving(article: Dict[str, Any]) -> Dict[str, Any]:
    """How likely a headline is to have moved the price, and why.

    Three things, none of which requires reading the article:

    How many outlets ran it. The cheapest signal there is, and a
    surprisingly good one -- everybody carries an earnings surprise
    and nobody carries a sponsored post.

    What kind of words are in the headline. An acquisition and an
    analyst note are both news about a company; only one of them
    reprices it.

    How old it is. A repricing event stops being news once the price
    has already moved, so age is a discount and not a disqualifier --
    a reader who has been away for a week still wants to know.

    Returned as a score AND the reasons behind it, because a number
    on its own is another thing to take on trust.
    """
    title = f'{article.get("title") or ""} {article.get("excerpt") or ""}'
    why: List[str] = []
    score = 0

    hits = 0
    for weight, pattern in MOVERS.items():
        found = pattern.search(title)
        if found:
            score += weight
            hits += 1
            if len(why) < 2:
                why.append(found.group(0).lower())

    feeds = article.get("feed_count") or 1
    if feeds > 1:
        score += min(feeds, 4)
        why.append(f"{feeds} outlets ran it")

    age_h = _hours_since(article.get("published"))
    if age_h is not None:
        if age_h <= 6:
            score += 2
        elif age_h <= 24:
            score += 1
        elif age_h > 24 * 7:
            score -= 1

    return {"score": score, "why": why, "hits": hits}


def _hours_since(iso: Optional[str]) -> Optional[float]:
    if not iso:
        return None
    try:
        when = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - when).total_seconds() / 3600.0


def discover_all(symbol: str, company: str = "") -> List[Dict[str, Any]]:
    """Pool every discovery feed, deduplicated by URL, newest first.

    Feeds overlap heavily -- the same wire story shows up in three of them. We
    keep the first sighting of each URL and record which feeds also carried it,
    because a story every feed picked up is a different signal from one only
    Google News found.
    """
    # Fetched together rather than one after another. Two feeds in
    # series was a second or so; seven would be most of ten, and this
    # runs on every page load and every refresh.
    jobs = {
        "yahoo": lambda: yahoo_rss(symbol),
        "google": lambda: google_news_rss(symbol, company),
        "seeking_alpha": lambda: seeking_alpha(symbol),
        "nasdaq": lambda: nasdaq_rss(symbol),
        "bing": lambda: bing_news(symbol, company),
        "investing": lambda: _about(investing_com(), symbol, company),
        "finnhub": lambda: finnhub_news(symbol),      # optional, needs a key
    }

    pooled: List[Dict[str, Any]] = []
    reached: List[str] = []
    with _cf.ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {pool.submit(fn): name for name, fn in jobs.items()}
        for fut in _cf.as_completed(futures, timeout=TIMEOUT + 10):
            name = futures[fut]
            try:
                got = fut.result() or []
            except Exception:
                continue                       # a dead feed is not an error
            if got:
                reached.append(name)
            pooled.extend(got)

    # Deduplicated twice over.
    #
    # By URL first, which catches the same link arriving from three
    # feeds. Then by headline, because a wire story runs on a dozen
    # sites under one title at a dozen URLs, and a page showing the
    # same sentence twelve times is worse than one showing it once.
    #
    # How many feeds carried a story is kept. It is the closest thing
    # to a free importance signal there is: everybody picks up an
    # earnings miss and nobody picks up a sponsored post.
    by_url: Dict[str, Dict[str, Any]] = {}
    for item in pooled:
        key = item["url"].split("?")[0]
        if key in by_url:
            existing = by_url[key].setdefault("also_via", [])
            if item["discovered_via"] not in existing:
                existing.append(item["discovered_via"])
        else:
            by_url[key] = item

    by_title: Dict[str, Dict[str, Any]] = {}
    for item in by_url.values():
        key = _headline_key(item.get("title", ""))
        if not key:
            by_title[item["url"]] = item
            continue
        first = by_title.get(key)
        if first is None:
            by_title[key] = item
            continue
        carried = first.setdefault("also_via", [])
        for v in [item["discovered_via"]] + (item.get("also_via") or []):
            if v not in carried and v != first["discovered_via"]:
                carried.append(v)

    articles = list(by_title.values())
    for a in articles:
        a["feed_count"] = 1 + len(a.get("also_via") or [])
    articles.sort(key=lambda a: a.get("published") or "", reverse=True)
    if articles:
        articles[0]["_feeds_reached"] = sorted(reached)
    return articles
