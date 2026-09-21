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
    feed = feedparser.parse(url)
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


def discover_all(symbol: str, company: str = "") -> List[Dict[str, Any]]:
    """Pool every discovery feed, deduplicated by URL, newest first.

    Feeds overlap heavily -- the same wire story shows up in three of them. We
    keep the first sighting of each URL and record which feeds also carried it,
    because a story every feed picked up is a different signal from one only
    Google News found.
    """
    pooled: List[Dict[str, Any]] = []
    for fetch in (
        lambda: yahoo_rss(symbol),
        lambda: google_news_rss(symbol, company),
    ):
        try:
            pooled.extend(fetch())
        except Exception:
            continue

    try:
        pooled.extend(finnhub_news(symbol))
    except Exception:
        pass  # optional source

    by_url: Dict[str, Dict[str, Any]] = {}
    for item in pooled:
        key = item["url"].split("?")[0]
        if key in by_url:
            existing = by_url[key].setdefault("also_via", [])
            if item["discovered_via"] not in existing:
                existing.append(item["discovered_via"])
        else:
            by_url[key] = item

    articles = list(by_url.values())
    articles.sort(key=lambda a: a.get("published") or "", reverse=True)
    return articles
