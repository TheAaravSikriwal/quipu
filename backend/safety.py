"""What the engine accepts from strangers, checked in one place.

The engine is published to the internet from Aarav's PC (share.py), so
everything a request carries -- a ticker in the path, the Host it was sent
to, whether it came through the tunnel -- is decided here rather than
re-checked, slightly differently, in every route.

  ticker()       a stock symbol, or None. Letters, digits and . - ^ =
                 only (BRK.B, BRK-B, ^GSPC, EURUSD=X). A symbol ends up
                 in cache file names, and on Windows a backslash or a
                 drive letter in one would write outside the cache.
  cache_file()   a symbol's file in a cache folder, guaranteed to be
                 inside that folder.
  local_host()   whether a request was addressed to this computer
                 (127.0.0.1, localhost, ::1) on any port.
  known_host()   whether the engine answers a request sent to that Host at
                 all: this computer, or its public address. Anything else
                 is a page that has pointed its own domain at 127.0.0.1
                 (DNS rebinding) to reach the engine as if it were local.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

_TICKER = re.compile(r"[A-Z0-9^][A-Z0-9.\-^=]{0,11}")

# Windows reserves these as device names, with or without an extension.
_DEVICES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(10)), *(f"LPT{i}" for i in range(10))}

LOCAL = {"127.0.0.1", "localhost", "::1"}


def ticker(raw) -> Optional[str]:
    """The symbol, upper-cased, if it is one; otherwise None."""
    s = str(raw or "").strip().upper()
    return s if _TICKER.fullmatch(s) else None


def cache_file(folder: Path, symbol: str, suffix: str = ".json") -> Path:
    """`folder/SYMBOL.json`, refusing anything that would land elsewhere."""
    sym = ticker(symbol)
    if sym is None:
        raise ValueError(f"not a symbol: {symbol!r}")
    stem = f"_{sym}" if sym.split(".")[0] in _DEVICES else sym
    folder = Path(folder).resolve()
    path = (folder / f"{stem}{suffix}").resolve()
    if path.parent != folder:
        raise ValueError(f"not a symbol: {symbol!r}")
    return path


def _hostname(host: str) -> str:
    """The name part of a Host header, lower-cased: "LocalHost:8848" -> "localhost"."""
    return (urlsplit(f"//{host.strip()}").hostname or "").lower()


def public_hosts() -> set:
    """The engine's public address(es): QUIPU_PUBLIC, plus any in QUIPU_HOSTS."""
    names = [os.environ.get("QUIPU_PUBLIC", "https://quipu.wearechintu.com")]
    names += [h.strip() for h in os.environ.get("QUIPU_HOSTS", "").split(",") if h.strip()]
    return {_hostname(urlsplit(n).netloc or n) for n in names} - {""}


def local_host(host: str) -> bool:
    return _hostname(host) in LOCAL


def known_host(host: str) -> bool:
    return local_host(host) or _hostname(host) in public_hosts()
