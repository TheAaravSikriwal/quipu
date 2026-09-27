"""Who the engine answers.

On a visitor's machine the engine listens on 127.0.0.1, and a web page on
ANY site the visitor has open can send requests to 127.0.0.1. So "only
local" is not a boundary by itself: without this, some other site could
make a visitor's engine run a 10,000-stock scan, flip its settings, or
frame the whole app under a page of its own.

The engine answers three kinds of caller and nobody else:

  its own page       (http://127.0.0.1:8848, same origin)
  wearechintu.com    (the front door that frames it and checks it is up)
  QUIPU_ORIGINS      (extra origins, comma-separated: a site preview, or
                      the site's own dev server while it is being built)

and it refuses the rest outright -- including the requests CORS lets
through anyway (a form POST, an <img> pointed at /api/...), which a
browser marks with Sec-Fetch-Site: cross-site.

It also answers the browser's local-network check: a public page reaching
into a visitor's machine is asked about first (Chrome and Edge prompt the
visitor for permission), and the engine has to say, in the preflight,
that it expects the site.
"""

from __future__ import annotations

import os
from typing import Iterable, Set

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

import paths

SITE = ("https://wearechintu.com", "https://www.wearechintu.com")
# QUIPU's own public address, through the tunnel. Behind cloudflared the
# engine sees plain http on localhost, so its own page arriving as https
# would not look like itself without being named here.
PUBLIC = os.environ.get("QUIPU_PUBLIC", "https://quipu.wearechintu.com")


def allowed_origins() -> Set[str]:
    extra = [o.strip().rstrip("/") for o in os.environ.get("QUIPU_ORIGINS", "").split(",") if o.strip()]
    dev = [] if paths.FROZEN else ["http://localhost:3000", "http://127.0.0.1:3000"]
    return set(SITE) | {PUBLIC} | set(extra) | set(dev)


def _self(request: Request) -> str:
    return f"{request.url.scheme}://{request.headers.get('host', '')}"


def _refuse(why: str) -> JSONResponse:
    return JSONResponse({"detail": why}, status_code=403)


def _frame_ancestors(origins: Iterable[str]) -> str:
    return "frame-ancestors 'self' " + " ".join(sorted(origins))


def decide(method: str, path: str, headers, self_origin: str):
    """What to do with one request: ("refuse", why), ("preflight", headers),
    or ("pass", headers to add). Pure, so it can be checked offline."""
    h = {k.lower(): v for k, v in headers.items()}
    allow = allowed_origins()
    origin = (h.get("origin") or "").rstrip("/")
    own = origin == self_origin
    ok_origin = own or origin in allow
    site, mode = h.get("sec-fetch-site", ""), h.get("sec-fetch-mode", "")

    # The preflight: only for callers we answer, and say yes to the
    # local-network question when the browser asks it.
    if method == "OPTIONS" and h.get("access-control-request-method"):
        if not ok_origin:
            return "refuse", "this engine only answers QUIPU pages"
        out = {"Access-Control-Allow-Origin": origin,
               "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
               "Access-Control-Allow-Headers": h.get("access-control-request-headers", "content-type"),
               "Access-Control-Max-Age": "600", "Vary": "Origin"}
        if h.get("access-control-request-private-network") == "true":
            out["Access-Control-Allow-Private-Network"] = "true"
        return "preflight", out

    if origin and not ok_origin:
        return "refuse", "this engine only answers QUIPU pages"
    # No Origin, but from another site: a form post or a tag pointed at the
    # API. Pages may be navigated to (that is how the site frames the app);
    # the API may not be poked at.
    if not origin and site == "cross-site" and mode != "navigate" and path.startswith("/api"):
        return "refuse", "this engine only answers QUIPU pages"

    out = {"Content-Security-Policy": _frame_ancestors(allow)}
    if origin and ok_origin and not own:
        out["Access-Control-Allow-Origin"] = origin
        out["Vary"] = "Origin"
    return "pass", out


def install(app) -> None:
    @app.middleware("http")
    async def guard(request: Request, call_next):
        what, detail = decide(request.method, request.url.path, request.headers, _self(request))
        if what == "refuse":
            return _refuse(detail)
        if what == "preflight":
            r = Response(status_code=204)
            r.headers.update(detail)
            return r
        response = await call_next(request)
        # Framed only by itself and the sites it answers -- nobody else can
        # put the app under a page of their own.
        response.headers.update(detail)
        return response
