"""The one door to Yahoo's crumb-gated endpoints -- quote summary and chains.

Every panel used to open its own. A single fifteen-second refresh asked
for `Ticker.info` three times (the quote, then the dividend yield asking
for fundamentals AND the quote again) plus the expiry list, for every open
tab and every visitor. Yahoo answered by refusing the crumb for the whole
IP, and yfinance, finding no crumb, asked for one again on every call --
so the refusal renewed itself for as long as anyone had a tab open.

Two things stop that here:

  - one `info` per symbol at a time, kept for a few seconds, so every
    caller in a refresh shares the same answer;
  - after a refusal, nobody asks again for five minutes. The callers get
    an empty answer at once and go to their fallbacks, which is what they
    would have ended up doing after a slow 401 anyway.

The chart endpoint needs no crumb and is not gated by any of this.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List

import yfinance as yf

import wire

INFO_TTL_S = 15
EXPIRIES_TTL_S = 300
COOL_S = 300

_LOCK = threading.Lock()
_SYMBOL_LOCKS: Dict[str, threading.Lock] = {}
_INFO: Dict[str, tuple] = {}
_EXPIRIES: Dict[str, tuple] = {}
_COOL_UNTIL = 0.0
_COOL_CODE = 0


def _repair_tz_cache() -> None:
    """yfinance keeps each ticker's timezone in a SQLite file, and a torn
    write leaves it "malformed" -- after which some calls raise and the
    rest quietly look the timezone up over the network every time. It is
    only a cache, so a broken one is removed and rebuilt."""
    try:
        from platformdirs import user_cache_dir
        folder = Path(user_cache_dir()) / "py-yfinance"
    except Exception:                                       # noqa: BLE001
        folder = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "py-yfinance"
    db = folder / "tkr-tz.db"
    if not db.exists():
        return
    try:
        con = sqlite3.connect(str(db))
        try:
            good = con.execute("pragma quick_check").fetchone()[0] == "ok"
        finally:
            con.close()
    except sqlite3.DatabaseError:
        good = False
    if good:
        return
    for f in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
        try:
            f.unlink()
        except OSError:
            pass


_repair_tz_cache()


def cooling() -> bool:
    return time.time() < _COOL_UNTIL


def cool_until() -> float:
    return _COOL_UNTIL


def resting() -> str:
    """Why the quote summary is not being asked, or "" if it is."""
    if not cooling():
        return ""
    return (f"refused (HTTP {_COOL_CODE}), resting until "
            f"{time.strftime('%H:%M', time.localtime(_COOL_UNTIL))}; backups in use")


def _trip(code: int) -> None:
    global _COOL_UNTIL, _COOL_CODE
    _COOL_UNTIL, _COOL_CODE = time.time() + COOL_S, code
    wire.mark("yahoo-quotes", False, resting(), code)


def _symbol_lock(symbol: str) -> threading.Lock:
    with _LOCK:
        return _SYMBOL_LOCKS.setdefault(symbol, threading.Lock())


def info(symbol: str, check: bool = False) -> Dict[str, Any]:
    """`Ticker.info`, shared. Empty while Yahoo is refusing us.

    `check` is the status light asking: it wants a real answer, not one
    kept from a few seconds ago, but still never while Yahoo is resting."""
    symbol = symbol.upper()
    hit = None if check else _INFO.get(symbol)
    if hit and time.time() - hit[0] < INFO_TTL_S:
        return hit[1]
    if cooling():
        return {}
    with _symbol_lock(symbol):
        hit = None if check else _INFO.get(symbol)
        if hit and time.time() - hit[0] < INFO_TTL_S:
            return hit[1]
        if cooling():
            return {}
        started = time.time()
        try:
            data = yf.Ticker(symbol).info or {}
        except Exception:                                   # noqa: BLE001
            data = {}
        refused = wire.failed_since("yahoo-quotes", started)
        if refused in (401, 429) and not data.get("regularMarketPrice"):
            _trip(refused)
            return {}
        if data.get("regularMarketPrice") or data.get("currentPrice"):
            wire.mark("yahoo-quotes", True, code=200)
        _INFO[symbol] = (time.time(), data)
        return data


def expiries(symbol: str) -> List[str]:
    """The listed expiry dates. They change once a week at most, so five
    minutes of keeping them costs nothing and saves a request a tick."""
    symbol = symbol.upper()
    hit = _EXPIRIES.get(symbol)
    if hit and time.time() - hit[0] < EXPIRIES_TTL_S:
        return list(hit[1])
    if cooling():
        return []
    started = time.time()
    try:
        listed = list(yf.Ticker(symbol).options or [])
    except Exception:                                       # noqa: BLE001
        listed = []
    refused = wire.failed_since("yahoo-quotes", started)
    if not listed and refused in (401, 429):
        _trip(refused)
        return []
    if listed:
        _EXPIRIES[symbol] = (time.time(), listed)
    return listed


def option_chain(symbol: str, expiry: str):
    """One board, or None. A refusal mid-way trips the rest too."""
    if cooling():
        return None
    started = time.time()
    try:
        return yf.Ticker(symbol).option_chain(expiry)
    except Exception:                                       # noqa: BLE001
        refused = wire.failed_since("yahoo-quotes", started)
        if refused in (401, 429):
            _trip(refused)
        return None
