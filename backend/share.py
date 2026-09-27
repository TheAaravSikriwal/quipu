"""Sharing one PC with the public, fairly.

QUIPU is published from Aarav's own computer through a Cloudflare Tunnel
(quipu.wearechintu.com). Everything a visitor asks for is fetched by that
one machine, over its one connection, against Yahoo's and the SEC's limits
for that one connection -- so without some care, one busy visitor would
use up QUIPU for everybody else.

This applies ONLY to requests that came in through the tunnel. Cloudflare
marks every one of those with CF-Connecting-IP (the visitor's address); a
request without it came from this computer itself, and is left exactly as
it always was -- no cache, no limits, every control.

For tunnel requests:

  shared answers   the same question asked twice within a short window gets
                   one fetch: prices for 10 seconds, a stock's page for two
                   minutes. Ten people watching AAPL cost what one does, and
                   ten arriving at once wait on the same fetch rather than
                   starting ten.
  fair use         per visitor: 120 requests a minute overall, 20 a minute
                   of the heavy pages. A page load is a handful; the live
                   price poll is four a minute. The limits are there for
                   scripts, not people.
  a queue          at most three heavy jobs run at once on the PC; the rest
                   wait their turn rather than all running slowly together.
  Aarav's switches the Alpaca switch and the 10,000-stock rescan answer
                   "only Aarav can do that".
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict, deque
from typing import Dict, Optional, Tuple

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

# Seconds a shared answer lasts, by path prefix. Anything not listed is
# never shared.
TTL = [
    ("/api/live/", 10),
    ("/api/chain/", 30),
    ("/api/news/", 60),
    ("/api/ticker/", 120),
    ("/api/course/", 120),
    ("/api/target/", 60),
    ("/api/world", 120),
    ("/api/events", 600),
    ("/api/screen", 60),
    ("/api/search", 300),
    ("/api/ivhistory/", 30),
    ("/api/health", 5),
]
HEAVY = ("/api/ticker/", "/api/course/", "/api/target/", "/api/ivhistory/",
         "/api/position", "/api/world", "/api/screen")
OWNER_ONLY = {("POST", "/api/settings/alpaca"), ("POST", "/api/screen/refresh")}

PER_MINUTE, HEAVY_PER_MINUTE, AT_ONCE = 120, 20, 3


def visitor(headers) -> Optional[str]:
    """The visitor's address if this came through the tunnel, else None."""
    return headers.get("cf-connecting-ip") or None


def ttl_for(path: str) -> Optional[int]:
    for prefix, seconds in TTL:
        if path == prefix.rstrip("/") or path.startswith(prefix):
            return seconds
    return None


class Limits:
    """Sliding one-minute windows, per visitor."""

    def __init__(self):
        self.hits: Dict[Tuple[str, str], deque] = defaultdict(deque)

    def allow(self, who: str, kind: str, limit: int, now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        q = self.hits[(who, kind)]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= limit:
            return False
        q.append(now)
        return True


LIMITS = Limits()
_ANSWERS: Dict[str, Tuple[float, int, bytes, str]] = {}
_INFLIGHT: Dict[str, asyncio.Future] = {}
_QUEUE: Optional[asyncio.Semaphore] = None


def _queue() -> asyncio.Semaphore:
    global _QUEUE
    if _QUEUE is None:
        _QUEUE = asyncio.Semaphore(AT_ONCE)
    return _QUEUE


def install(app) -> None:
    @app.middleware("http")
    async def share(request: Request, call_next):
        who = visitor(request.headers)
        if who is None:                          # this computer: untouched
            return await call_next(request)

        path, method = request.url.path, request.method
        if (method, path) in OWNER_ONLY:
            return JSONResponse({"detail": "only Aarav can do that"}, status_code=403)

        heavy = path.startswith(HEAVY)
        if path.startswith("/api/"):
            if not LIMITS.allow(who, "all", PER_MINUTE) or (heavy and not LIMITS.allow(who, "heavy", HEAVY_PER_MINUTE)):
                return JSONResponse({"detail": "a lot of requests from you in the last minute -- give it a moment"},
                                    status_code=429, headers={"Retry-After": "20"})

        ttl = ttl_for(path) if method == "GET" else None
        key = f"{path}?{request.url.query}" if ttl else None
        if key:
            hit = _ANSWERS.get(key)
            if hit and time.monotonic() - hit[0] < ttl:
                return Response(hit[2], status_code=hit[1], media_type=hit[3], headers={"X-QUIPU-Shared": "hit"})
            waiting = _INFLIGHT.get(key)
            if waiting is not None:
                try:
                    status, body, media = await asyncio.wait_for(asyncio.shield(waiting), timeout=90)
                    return Response(body, status_code=status, media_type=media, headers={"X-QUIPU-Shared": "joined"})
                except Exception:                                 # noqa: BLE001
                    pass                                          # fetch it ourselves
            fut = asyncio.get_running_loop().create_future()
            # Read any failure off it even when nobody joined, so a failed
            # fetch is not also reported as an unhandled one.
            fut.add_done_callback(lambda f: f.cancelled() or f.exception())
            _INFLIGHT[key] = fut

        try:
            if heavy:
                async with _queue():
                    response = await call_next(request)
            else:
                response = await call_next(request)
            if not key:
                return response
            body = b"".join([chunk async for chunk in response.body_iterator])
            media = response.headers.get("content-type", "application/json")
            if response.status_code == 200:
                _ANSWERS[key] = (time.monotonic(), 200, body, media)
                if len(_ANSWERS) > 2000:                          # keep it bounded
                    for k in sorted(_ANSWERS, key=lambda k: _ANSWERS[k][0])[:500]:
                        _ANSWERS.pop(k, None)
            out = dict(response.headers)
            out.pop("content-length", None)
            if not fut.done():
                fut.set_result((response.status_code, body, media))
            return Response(body, status_code=response.status_code, headers={**out, "X-QUIPU-Shared": "miss"})
        except Exception as exc:
            if key and not fut.done():
                fut.set_exception(exc)
            raise
        finally:
            if key:
                _INFLIGHT.pop(key, None)
