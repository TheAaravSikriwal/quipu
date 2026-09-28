"""Tiered article extraction -- cheap first, expensive only when cheap fails.

Three tiers, tried in order:

  1. trafilatura   free, fast, pure Python. Handles most plain article pages.
  2. news-please   free, heavier. Runs several extractors and compares their
                   answers, so it rescues pages trafilatura reads badly.
  3. Firecrawl     paid. Renders JavaScript and parses PDFs, which neither of
                   the free tiers can do at all.

Cost is proportional to the hard cases rather than to total volume: the paid
tier only ever sees pages the free tiers could not read.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import safety

MIN_BODY_CHARS = 400  # below this we treat the extraction as failed

_HAS_TRAFILATURA = False
_HAS_NEWSPLEASE = False

try:
    import trafilatura

    _HAS_TRAFILATURA = True
except ImportError:
    pass

try:
    from newsplease import NewsPlease

    _HAS_NEWSPLEASE = True
except ImportError:
    pass


@dataclass
class Article:
    url: str
    title: Optional[str] = None
    text: str = ""
    authors: List[str] = field(default_factory=list)
    published: Optional[str] = None
    publisher: Optional[str] = None
    tier: Optional[str] = None
    chars: int = 0
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _clean_authors(authors: Any) -> List[str]:
    """Extractors pick up share buttons as bylines. Drop anything domain-shaped."""
    if not authors:
        return []
    if isinstance(authors, str):
        authors = [authors]
    out = []
    for author in authors:
        name = str(author).strip()
        if not name or "." in name.split()[-1] or len(name) > 60:
            continue
        if re.search(r"(facebook|twitter|linkedin|www\.|\.com|\.net)", name, re.I):
            continue
        out.append(name)
    return out


def _tier_trafilatura(url: str) -> Optional[Article]:
    if not _HAS_TRAFILATURA:
        return None
    # Fetched with a deadline. trafilatura.fetch_url has no timeout
    # argument and will wait on a host far longer than a reader will:
    # of twenty-two articles attempted on one page, thirteen failed,
    # and it was the failures rather than the successes that took two
    # minutes. A page that cannot be read in eight seconds is not
    # going to be read.
    # Through safety.fetch_page: a feed's link (and every redirect it
    # takes) must be on the public internet, never this PC or its network.
    try:
        downloaded = safety.fetch_page(
            url, timeout=8,
            headers={"User-Agent": "Mozilla/5.0 (compatible; quipu/0.1)"})
    except Exception:
        downloaded = None
    if not downloaded:
        return None

    text = trafilatura.extract(
        downloaded, include_comments=False, include_tables=True, favor_precision=True
    )
    if not text or len(text) < MIN_BODY_CHARS:
        return None

    meta = trafilatura.extract_metadata(downloaded)
    return Article(
        url=url,
        title=getattr(meta, "title", None),
        text=text,
        authors=_clean_authors(getattr(meta, "author", None)),
        published=getattr(meta, "date", None),
        publisher=getattr(meta, "sitename", None) or urlparse(url).netloc,
        tier="trafilatura",
        chars=len(text),
    )


def _tier_newsplease(url: str) -> Optional[Article]:
    if not _HAS_NEWSPLEASE:
        return None
    article = NewsPlease.from_url(url, request_args={"timeout": 20})
    if not article or not getattr(article, "maintext", None):
        return None

    text = article.maintext
    if len(text) < MIN_BODY_CHARS:
        return None

    return Article(
        url=url,
        title=article.title,
        text=text,
        authors=_clean_authors(article.authors),
        published=str(article.date_publish) if article.date_publish else None,
        publisher=article.source_domain or urlparse(url).netloc,
        tier="news-please",
        chars=len(text),
    )


def _tier_firecrawl(url: str) -> Optional[Article]:
    """Only runs when FIRECRAWL_API_KEY is set. This is the tier that costs money."""
    key = os.getenv("FIRECRAWL_API_KEY")
    if not key:
        return None

    try:
        from firecrawl import Firecrawl
    except ImportError:
        return None

    result = Firecrawl(api_key=key).scrape(url, formats=["markdown"])
    markdown = (
        result.get("markdown") if isinstance(result, dict) else getattr(result, "markdown", None)
    )
    if not markdown or len(markdown) < MIN_BODY_CHARS:
        return None

    metadata = (
        result.get("metadata", {}) if isinstance(result, dict)
        else getattr(result, "metadata", {}) or {}
    )
    return Article(
        url=url,
        title=metadata.get("title"),
        text=markdown,
        authors=_clean_authors(metadata.get("author")),
        published=metadata.get("publishedTime"),
        publisher=metadata.get("ogSiteName") or urlparse(url).netloc,
        tier="firecrawl",
        chars=len(markdown),
    )


def extract(url: str) -> Article:
    """Walk the tiers until one returns a usable body."""
    # A link that points anywhere but the public internet is not read at
    # all, by any tier (news-please fetches for itself).
    if not safety.public_url(url):
        return Article(url=url, publisher=urlparse(url).netloc, error="not a public web address")
    errors: List[str] = []
    for tier in (_tier_trafilatura, _tier_newsplease, _tier_firecrawl):
        try:
            article = tier(url)
            if article:
                return article
        except Exception as exc:
            errors.append(f"{tier.__name__}: {type(exc).__name__}")

    return Article(
        url=url,
        publisher=urlparse(url).netloc,
        error="; ".join(errors) if errors else "no tier produced a usable body",
    )


def available_tiers() -> Dict[str, bool]:
    return {
        "trafilatura": _HAS_TRAFILATURA,
        "news-please": _HAS_NEWSPLEASE,
        "firecrawl": bool(os.getenv("FIRECRAWL_API_KEY")),
    }
