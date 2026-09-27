"""Alpaca market data: the one free source with option-price history.

Yahoo shows today's chain and nothing before it, and every number the
curriculum compares "against the stock's own past year" -- IV Rank, IV
Percentile, where skew normally sits, the usual put/call -- needs the
chain as it stood on each of those days. Alpaca keeps expired contracts
(back to early 2024) and serves their daily bars on the free plan, so
the history can be rebuilt from real traded prices rather than recorded
from today or estimated.

Read-only. This module only ever calls market-data and contract-listing
endpoints; nothing here can place, change or see an order.

Credentials, first found wins:
  1. ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY in the environment
  2. the same two names in quipu/.env
  3. the PAPER keys in ../algotrader/.env, the project they were made for

Only paper keys are ever read. Live-account variables are ignored by
name, so a real-money key cannot be picked up by accident.
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import requests

DATA = "https://data.alpaca.markets"
# Contract listings live on the trading host. The paper one: the keys
# are paper keys, and listing contracts is the same data either way.
TRADING = "https://paper-api.alpaca.markets"

import paths

# In a checkout: quipu/.env, then the algotrader project's paper keys. In
# the engine a visitor installs: only the visitor's own QUIPU data folder.
_ENV_FILES = list(paths.ENV_FILES)
_KEY, _SECRET = "ALPACA_API_KEY_ID", "ALPACA_API_SECRET_KEY"


def _read_env(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return out


def _credentials() -> Optional[Dict[str, str]]:
    key, secret = os.environ.get(_KEY), os.environ.get(_SECRET)
    for path in _ENV_FILES:
        if key and secret:
            break
        env = _read_env(path)
        key, secret = env.get(_KEY), env.get(_SECRET)
    if not (key and secret):
        return None
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def available() -> bool:
    """Keys exist. Says nothing about whether the app should use them."""
    return _credentials() is not None


# ---- optional, and switchable --------------------------------------------
#
# Everything Alpaca adds is extra: the app works without it, and every
# number that needs it says so rather than guessing. Off by setting
# QUIPU_ALPACA=off (environment or quipu/.env), or from the app itself,
# which writes the choice to backend/cache/settings.json.

_SETTINGS = paths.CACHE / "settings.json"


def _switched_off() -> bool:
    flag = os.environ.get("QUIPU_ALPACA") or _read_env(_ENV_FILES[0]).get("QUIPU_ALPACA")
    if flag and flag.strip().lower() in ("0", "off", "false", "no"):
        return True
    try:
        import json
        return json.loads(_SETTINGS.read_text(encoding="utf-8")).get("alpaca") is False
    except (OSError, ValueError):
        return False


def set_enabled(on: bool) -> None:
    import json
    try:
        current = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        current = {}
    current["alpaca"] = bool(on)
    _SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS.write_text(json.dumps(current), encoding="utf-8")


def status() -> dict:
    """What the app should say about Alpaca, in one place."""
    keys, off = available(), _switched_off()
    return {
        "keys": keys,
        "enabled": keys and not off,
        "why": (None if keys and not off
                else "switched off" if keys
                else "no Alpaca keys (ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY in quipu/.env)"),
    }


def enabled() -> bool:
    return available() and not _switched_off()


# ---- a polite client -------------------------------------------------------
#
# The free plan allows 200 requests a minute. Rebuilding a year of one
# stock's options takes a few dozen, so this only matters when several
# stocks are being built at once -- but when it matters a 429 halfway
# through leaves a history with holes in it, which is worse than slow.

_LOCK = threading.Lock()
_STAMPS: List[float] = []
_PER_MINUTE = 180


def _throttle() -> None:
    with _LOCK:
        now = time.monotonic()
        while _STAMPS and now - _STAMPS[0] > 60:
            _STAMPS.pop(0)
        if len(_STAMPS) >= _PER_MINUTE:
            time.sleep(60 - (now - _STAMPS[0]) + 0.05)
        _STAMPS.append(time.monotonic())


def _get(url: str, params: Dict[str, Any]) -> Dict[str, Any]:
    head = _credentials()
    if head is None:
        raise RuntimeError("no Alpaca keys found")
    for attempt in range(4):
        _throttle()
        r = requests.get(url, headers=head, params=params, timeout=25)
        if r.status_code == 429:
            time.sleep(2 ** attempt)
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError("Alpaca kept rate-limiting")


def _paged(url: str, params: Dict[str, Any], key: str) -> Iterable[Any]:
    """Follow next_page_token until the listing ends."""
    params = dict(params)
    while True:
        body = _get(url, params)
        yield body.get(key)
        token = body.get("next_page_token") or body.get("page_token")
        if not token:
            return
        params["page_token"] = token


# ---- what exists -----------------------------------------------------------

def contracts(underlying: str, expiry: str, strike_lo: float, strike_hi: float,
              ) -> List[Dict[str, Any]]:
    """Every contract on one expiry inside a strike band, live or expired."""
    out: List[Dict[str, Any]] = []
    for status in ("inactive", "active"):
        for page in _paged(f"{TRADING}/v2/options/contracts", {
            "underlying_symbols": underlying, "status": status,
            "expiration_date": expiry,
            "strike_price_gte": f"{strike_lo:.2f}", "strike_price_lte": f"{strike_hi:.2f}",
            "limit": 10000,
        }, "option_contracts"):
            for c in page or []:
                out.append({"symbol": c["symbol"], "type": c["type"],
                            "strike": float(c["strike_price"]),
                            "expiry": c["expiration_date"]})
    # A contract can be listed under both statuses on its last day.
    seen, unique = set(), []
    for c in out:
        if c["symbol"] not in seen:
            seen.add(c["symbol"])
            unique.append(c)
    return unique


# ---- what it traded at -----------------------------------------------------

def _settled(end: str) -> str:
    """The free plan serves data only once it is 15 minutes old, and refuses
    the whole request otherwise -- so a range ending today is cut off just
    short of now."""
    from datetime import datetime, timedelta, timezone
    edge = datetime.now(timezone.utc) - timedelta(minutes=16)
    if end >= edge.date().isoformat():
        return edge.strftime("%Y-%m-%dT%H:%M:%SZ")
    return end


def option_bars(symbols: List[str], start: str, end: str,
                batch: int = 100) -> Dict[str, Dict[str, Dict[str, float]]]:
    """Daily bars per contract: {symbol: {date: {close, volume}}}."""
    out: Dict[str, Dict[str, Dict[str, float]]] = {}
    for i in range(0, len(symbols), batch):
        chunk = symbols[i:i + batch]
        for page in _paged(f"{DATA}/v1beta1/options/bars", {
            "symbols": ",".join(chunk), "timeframe": "1Day",
            "start": start, "end": _settled(end), "limit": 10000,
        }, "bars"):
            for sym, bars in (page or {}).items():
                day = out.setdefault(sym, {})
                for b in bars:
                    day[b["t"][:10]] = {"close": float(b["c"]), "volume": float(b["v"])}
    return out


def stock_bars(symbol: str, start: str, end: str) -> Dict[str, float]:
    """Daily closes, UNADJUSTED: {date: close}.

    Unadjusted on purpose. A strike is a price as it stood on the day, so
    the share price it is compared against has to be as well -- a close
    rescaled for a later split would put every pre-split contract a
    multiple away from the money.
    """
    end = _settled(end)
    out: Dict[str, float] = {}
    for page in _paged(f"{DATA}/v2/stocks/{symbol}/bars", {
        "timeframe": "1Day", "start": start, "end": end, "limit": 10000,
        "adjustment": "raw", "feed": "sip",
    }, "bars"):
        for b in page or []:
            out[b["t"][:10]] = float(b["c"])
    return out
