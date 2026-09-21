"""Group articles that cover the same story.

This is a grouping step, never a filtering one. The usual approach -- compare
headlines, throw away anything similar -- destroys precisely what this app
exists to find. The fourth outlet's version of a story is often the only one
that mentioned the guidance cut.

So: cluster articles by what they actually say, keep every one of them, and
hand the cluster to the claim differ to work out who said what uniquely.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set

SHINGLE_SIZE = 4
SIMHASH_BITS = 64
HAMMING_THRESHOLD = 12  # out of 64; tuned for "same story, reworded"

# Two different similarity signals, because there are two different ways for
# articles to cover one story:
#   SHINGLE  shared 4-word phrases -- catches wire copy reprinted verbatim
#   TOKEN    shared vocabulary -- catches a genuine rewrite, where the phrasing
#            is all new but the names, numbers and nouns are necessarily the same
# Shingles alone miss paraphrases, which is the failure that matters: it would
# report a rewritten wire story as an exclusive.
JACCARD_THRESHOLD = 0.28
TOKEN_THRESHOLD = 0.33
# Two articles about the same ticker always share generic vocabulary -- shares,
# revenue, quarter. What they only share when covering the same event is the
# specific figures. Shared hard numbers are therefore worth more than shared
# words, and carry a lower bar.
NUMERIC_TOKEN_THRESHOLD = 0.22
MIN_SHARED_FIGURES = 3

STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by", "for",
    "from", "has", "have", "he", "her", "his", "in", "is", "it", "its", "of",
    "on", "or", "said", "she", "that", "the", "their", "they", "this", "to",
    "was", "were", "will", "with", "would", "we", "you", "not", "can", "also",
}


def tokenize(text: str) -> List[str]:
    """Lowercase word tokens with stopwords dropped, numbers kept.

    Numbers stay because in financial copy they carry most of the meaning --
    "$4.2 billion" is the story, "the company announced" is filler.
    """
    words = re.findall(r"[a-z0-9$%.,]+", (text or "").lower())
    out = []
    for word in words:
        cleaned = word.strip(".,")
        if not cleaned or cleaned in STOPWORDS or len(cleaned) < 2:
            continue
        out.append(cleaned)
    return out


def shingles(tokens: Sequence[str], size: int = SHINGLE_SIZE) -> Set[str]:
    """Overlapping n-grams. Two texts sharing many n-grams share phrasing."""
    if len(tokens) < size:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i : i + size]) for i in range(len(tokens) - size + 1)}


def simhash(features: Iterable[str], bits: int = SIMHASH_BITS) -> int:
    """Locality-sensitive hash: similar inputs give hashes a few bits apart."""
    vector = [0] * bits
    for feature in features:
        digest = int(hashlib.md5(feature.encode("utf-8")).hexdigest(), 16)
        for bit in range(bits):
            vector[bit] += 1 if (digest >> bit) & 1 else -1
    result = 0
    for bit in range(bits):
        if vector[bit] > 0:
            result |= 1 << bit
    return result


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _is_figure(token: str) -> bool:
    """A token carrying a hard number -- $35.1, 94%, 2026, 30.8."""
    return any(ch.isdigit() for ch in token)


def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass
class Fingerprint:
    index: int
    url: str
    publisher: Optional[str]
    published: Optional[str]
    title: Optional[str]
    simhash: int
    shingles: Set[str] = field(repr=False, default_factory=set)
    tokens: Set[str] = field(repr=False, default_factory=set)


class UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a: int, b: int) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self.parent[root_b] = root_a


def fingerprint(articles: Sequence[Dict[str, Any]]) -> List[Fingerprint]:
    prints: List[Fingerprint] = []
    for i, article in enumerate(articles):
        body = f"{article.get('title') or ''} {article.get('text') or ''}"
        tokens = tokenize(body)
        shingle_set = shingles(tokens)
        prints.append(
            Fingerprint(
                index=i,
                url=article.get("url", ""),
                publisher=article.get("publisher"),
                published=article.get("published"),
                title=article.get("title"),
                simhash=simhash(shingle_set or tokens),
                shingles=shingle_set,
                tokens=set(tokens),
            )
        )
    return prints


def cluster(articles: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Group articles into stories. Every article lands in exactly one cluster.

    Two passes: SimHash Hamming distance is cheap and catches reprints, then
    Jaccard on shingles confirms, which stops unrelated short pieces from being
    merged just because their hashes happen to sit close together.
    """
    prints = fingerprint(articles)
    union = UnionFind(len(prints))

    for i in range(len(prints)):
        for j in range(i + 1, len(prints)):
            close = hamming(prints[i].simhash, prints[j].simhash) <= HAMMING_THRESHOLD
            phrase = jaccard(prints[i].shingles, prints[j].shingles)
            vocab = jaccard(prints[i].tokens, prints[j].tokens)

            shared_figures = len(
                {t for t in prints[i].tokens & prints[j].tokens if _is_figure(t)}
            )

            same_story = (
                phrase >= JACCARD_THRESHOLD                    # reprinted copy
                or vocab >= TOKEN_THRESHOLD                    # rewritten copy
                or (vocab >= NUMERIC_TOKEN_THRESHOLD and shared_figures >= MIN_SHARED_FIGURES)
                or (close and phrase >= JACCARD_THRESHOLD * 0.6)
            )
            if same_story:
                union.union(i, j)

    groups: Dict[int, List[int]] = {}
    for i in range(len(prints)):
        groups.setdefault(union.find(i), []).append(i)

    clusters: List[Dict[str, Any]] = []
    for members in groups.values():
        members.sort(key=lambda i: articles[i].get("published") or "")
        dated = [i for i in members if articles[i].get("published")]
        first = dated[0] if dated else members[0]

        publishers = []
        for i in members:
            name = articles[i].get("publisher") or "unknown"
            if name not in publishers:
                publishers.append(name)

        clusters.append(
            {
                "size": len(members),
                "members": members,
                "publishers": publishers,
                # Who carried it first. With one source, "exclusive so far".
                "first_seen": {
                    "publisher": articles[first].get("publisher"),
                    "published": articles[first].get("published"),
                    "url": articles[first].get("url"),
                },
                "headline": articles[first].get("title"),
                "exclusive": len(publishers) == 1,
            }
        )

    clusters.sort(key=lambda c: c["size"], reverse=True)
    return clusters
