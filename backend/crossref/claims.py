"""Claim-level diffing -- the part that actually earns the app its keep.

Clustering tells you forty outlets covered one story. That is not useful on its
own. What matters is the sentence that appears in exactly one of them.

For every cluster we split each article into claims, compare each claim against
every claim in the *other* articles, and sort them into:

  corroborated  several outlets say it -- probably true, probably priced in
  unique        one outlet says it -- either a scoop or an error, worth a look

Unique claims are then scored for how much they could matter to a trader. A
sentence with a dollar figure, a percentage and a forward-looking verb outranks
a sentence of background colour.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Set

from .cluster import jaccard, tokenize

SIMILARITY_THRESHOLD = 0.42  # above this, two sentences are "the same claim"
MIN_CLAIM_WORDS = 7
MAX_CLAIM_CHARS = 400

# Words that make a sentence matter more to someone about to take a position.
SIGNAL_TERMS = {
    "guidance", "forecast", "outlook", "expects", "expected", "raised",
    "lowered", "cut", "beat", "missed", "upgrade", "downgrade", "target",
    "warned", "warning", "investigation", "lawsuit", "recall", "resign",
    "acquisition", "merger", "buyback", "dividend", "layoffs", "delay",
    "approval", "contract", "partnership", "earnings", "revenue", "margin",
    "bankruptcy", "default", "subpoena", "settlement", "exclusive",
}

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'$])")


def split_claims(text: str) -> List[str]:
    """Split a body into sentence-sized claims, dropping boilerplate."""
    if not text:
        return []

    claims: List[str] = []
    for block in text.split("\n"):
        block = block.strip()
        if not block:
            continue
        for sentence in _SENTENCE_SPLIT.split(block):
            sentence = sentence.strip()
            if len(sentence.split()) < MIN_CLAIM_WORDS:
                continue
            if len(sentence) > MAX_CLAIM_CHARS:
                sentence = sentence[:MAX_CLAIM_CHARS].rsplit(" ", 1)[0] + "..."
            if _is_boilerplate(sentence):
                continue
            claims.append(sentence)
    return claims


def _is_boilerplate(sentence: str) -> bool:
    lowered = sentence.lower()
    patterns = (
        "all rights reserved", "subscribe to", "sign up for", "cookie",
        "terms of service", "privacy policy", "follow us on", "read more at",
        "this article was", "click here", "advertisement", "newsletter",
        "disclosure:", "disclaimer:", "the motley fool has", "seeking alpha",
    )
    return any(p in lowered for p in patterns)


def score_claim(sentence: str) -> float:
    """How much a claim could move a decision. Higher is more actionable."""
    score = 0.0
    lowered = sentence.lower()

    if re.search(r"\$\s?\d", sentence):
        score += 2.5                                   # a dollar figure
    score += 1.6 * len(re.findall(r"\d+(?:\.\d+)?\s?%", sentence))
    score += 0.8 * len(re.findall(r"\b\d[\d,]*(?:\.\d+)?\b", sentence)[:4])
    score += 1.4 * sum(1 for term in SIGNAL_TERMS if term in lowered)

    if '"' in sentence or "“" in sentence:
        score += 1.2                                   # a direct quote
    if re.search(r"\b(19|20)\d{2}\b|\bQ[1-4]\b|\bfiscal\b", sentence):
        score += 0.9                                   # anchored in time

    # Proper nouns beyond the first word suggest named people, firms, products.
    score += 0.35 * min(len(re.findall(r"(?<!^)(?<![.!?] )\b[A-Z][a-z]{2,}", sentence)), 6)

    return round(score, 2)


class _Indexed:
    __slots__ = ("text", "tokens", "article")

    def __init__(self, text: str, article: int) -> None:
        self.text = text
        self.tokens: Set[str] = set(tokenize(text))
        self.article = article


def diff_cluster(
    articles: Sequence[Dict[str, Any]],
    members: Sequence[int],
) -> Dict[str, Any]:
    """Work out which claims in a cluster are shared and which stand alone."""
    indexed: List[_Indexed] = []
    for member in members:
        for claim in split_claims(articles[member].get("text", "")):
            indexed.append(_Indexed(claim, member))

    if not indexed:
        return {"unique": [], "corroborated": [], "claim_count": 0}

    unique: List[Dict[str, Any]] = []
    corroborated: List[Dict[str, Any]] = []
    consumed: Set[int] = set()

    for i, claim in enumerate(indexed):
        if i in consumed:
            continue

        matches = []
        for j in range(i + 1, len(indexed)):
            other = indexed[j]
            if other.article == claim.article or j in consumed:
                continue
            if jaccard(claim.tokens, other.tokens) >= SIMILARITY_THRESHOLD:
                matches.append(j)

        sources = {claim.article} | {indexed[j].article for j in matches}

        if len(sources) > 1:
            consumed.update(matches)
            corroborated.append(
                {
                    "claim": claim.text,
                    "source_count": len(sources),
                    "publishers": sorted(
                        {articles[a].get("publisher") or "unknown" for a in sources}
                    ),
                    "score": score_claim(claim.text),
                }
            )
        else:
            unique.append(
                {
                    "claim": claim.text,
                    "publisher": articles[claim.article].get("publisher") or "unknown",
                    "url": articles[claim.article].get("url"),
                    "published": articles[claim.article].get("published"),
                    "score": score_claim(claim.text),
                }
            )

    unique.sort(key=lambda c: c["score"], reverse=True)
    corroborated.sort(key=lambda c: (c["source_count"], c["score"]), reverse=True)

    return {
        "unique": unique,
        "corroborated": corroborated,
        "claim_count": len(indexed),
    }


def cross_reference(
    articles: Sequence[Dict[str, Any]],
    clusters: Sequence[Dict[str, Any]],
    unique_limit: int = 40,
) -> Dict[str, Any]:
    """Run the diff over every cluster and roll the results up."""
    enriched: List[Dict[str, Any]] = []
    all_unique: List[Dict[str, Any]] = []
    all_corroborated: List[Dict[str, Any]] = []

    for group in clusters:
        diff = diff_cluster(articles, group["members"])

        for claim in diff["unique"]:
            claim["story"] = group["headline"]
        for claim in diff["corroborated"]:
            claim["story"] = group["headline"]

        all_unique.extend(diff["unique"])
        all_corroborated.extend(diff["corroborated"])

        enriched.append(
            {
                **{k: v for k, v in group.items() if k != "members"},
                "member_urls": [articles[i].get("url") for i in group["members"]],
                "claim_count": diff["claim_count"],
                "unique_count": len(diff["unique"]),
                "corroborated_count": len(diff["corroborated"]),
                "top_unique": diff["unique"][:5],
            }
        )

    all_unique.sort(key=lambda c: c["score"], reverse=True)
    all_corroborated.sort(key=lambda c: (c["source_count"], c["score"]), reverse=True)

    by_publisher: Dict[str, int] = {}
    for claim in all_unique:
        by_publisher[claim["publisher"]] = by_publisher.get(claim["publisher"], 0) + 1

    return {
        "stories": enriched,
        "unique_claims": all_unique[:unique_limit],
        "corroborated_claims": all_corroborated[:20],
        "stats": {
            "articles": len(articles),
            "stories": len(clusters),
            "total_claims": sum(c["claim_count"] for c in enriched),
            "unique_claims": len(all_unique),
            "corroborated_claims": len(all_corroborated),
            "exclusives": sum(1 for c in clusters if c.get("exclusive")),
            # Who is actually adding information rather than reprinting it.
            "unique_by_publisher": dict(
                sorted(by_publisher.items(), key=lambda kv: kv[1], reverse=True)[:12]
            ),
        },
    }
