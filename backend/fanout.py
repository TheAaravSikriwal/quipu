"""Parallel fan-out with per-source rate limiting.

Every source runs at the same time; requests *within* a source are throttled to
that source's own limit. Free API tiers are rate-limited per key, so the
bottleneck is never "the network" -- it is one provider getting hammered. This
is the bounded-concurrency shape: wide across sources, narrow within each.
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional


@dataclass
class SourceResult:
    """What one source returned, plus how it went."""

    source: str
    ok: bool
    data: Any = None
    error: Optional[str] = None
    elapsed_ms: int = 0
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "ok": self.ok,
            "data": self.data,
            "error": self.error,
            "elapsed_ms": self.elapsed_ms,
            "meta": self.meta,
        }


class RateLimiter:
    """Minimum spacing between calls, per key. Thread-safe."""

    def __init__(self) -> None:
        self._locks: Dict[str, threading.Lock] = {}
        self._last: Dict[str, float] = {}
        self._guard = threading.Lock()

    def wait(self, key: str, min_interval_s: float) -> None:
        if min_interval_s <= 0:
            return
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        with lock:
            last = self._last.get(key, 0.0)
            gap = time.monotonic() - last
            if gap < min_interval_s:
                time.sleep(min_interval_s - gap)
            self._last[key] = time.monotonic()


LIMITER = RateLimiter()


class Semaphores:
    """Named concurrency caps -- how many requests a source may have in flight."""

    def __init__(self) -> None:
        self._sems: Dict[str, threading.Semaphore] = {}
        self._guard = threading.Lock()

    def get(self, key: str, limit: int) -> threading.Semaphore:
        with self._guard:
            if key not in self._sems:
                self._sems[key] = threading.Semaphore(limit)
            return self._sems[key]


SEMAPHORES = Semaphores()


def fanout(
    tasks: Dict[str, Callable[[], Any]],
    timeout_s: float = 45.0,
    max_workers: Optional[int] = None,
) -> List[SourceResult]:
    """Run every task concurrently. One task failing never sinks the others.

    A source that dies returns a SourceResult with ok=False rather than raising,
    so a dead provider degrades the page instead of blanking it.
    """
    if not tasks:
        return []

    results: List[SourceResult] = []
    workers = max_workers or min(len(tasks), 16)

    def run(name: str, fn: Callable[[], Any]) -> SourceResult:
        started = time.monotonic()
        try:
            data = fn()
            return SourceResult(
                source=name,
                ok=True,
                data=data,
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )
        except Exception as exc:  # a broken source must not break the page
            return SourceResult(
                source=name,
                ok=False,
                error=f"{type(exc).__name__}: {exc}",
                elapsed_ms=int((time.monotonic() - started) * 1000),
            )

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run, name, fn): name for name, fn in tasks.items()}
        try:
            for future in as_completed(futures, timeout=timeout_s):
                results.append(future.result())
        except TimeoutError:
            pass
        for future, name in futures.items():
            if not future.done():
                future.cancel()
                results.append(
                    SourceResult(source=name, ok=False, error="timed out")
                )

    return results


def bounded_map(
    fn: Callable[[Any], Any],
    items: Iterable[Any],
    limit: int,
    key: str = "default",
    min_interval_s: float = 0.0,
) -> List[Any]:
    """Map fn over items with at most `limit` running at once for this key.

    Used for the article-extraction stage: 40 URLs to fetch, but never more
    than `limit` at a time against any one domain.
    """
    items = list(items)
    if not items:
        return []

    sem = SEMAPHORES.get(key, limit)

    def guarded(item: Any) -> Any:
        with sem:
            LIMITER.wait(key, min_interval_s)
            try:
                return fn(item)
            except Exception:
                return None

    with ThreadPoolExecutor(max_workers=min(limit * 2, 24)) as pool:
        return [r for r in pool.map(guarded, items)]
