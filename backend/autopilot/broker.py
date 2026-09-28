"""Orders, for the autopilot and nothing else.

sources/alpaca.py is read-only by design -- market data and contract
listings, never an order. This is the one module in QUIPU that can place
one, and it is only ever driven by a bot the owner started (every route
that reaches it refuses visitors; see app.py and share.py).

Paper by default. The live account is used only when BOTH are true:
  - ALPACA_LIVE_API_KEY_ID / ALPACA_LIVE_API_SECRET_KEY exist (the owner
    adds them; same .env files as the paper keys), and differ from the
    paper keys, so a paper key can never be mistaken for a live one;
  - the owner has switched live on (settings.json "autopilot_live"),
    which the page only does after he types LIVE to confirm.
A bot also has to be set to Live mode itself. Nothing else can reach it.

Market data (bars, the latest trade) comes from Alpaca's free IEX feed
with the paper keys, whichever account trades: the data is the same.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

import paths
from sources import alpaca

PAPER = "https://paper-api.alpaca.markets"
LIVE = "https://api.alpaca.markets"
DATA = "https://data.alpaca.markets"
LIVE_KEY, LIVE_SECRET = "ALPACA_LIVE_API_KEY_ID", "ALPACA_LIVE_API_SECRET_KEY"
TIMEOUT = 12

_SETTINGS = paths.CACHE / "settings.json"


class BrokerError(RuntimeError):
    pass


# ---- which account ---------------------------------------------------------

def _live_headers() -> Optional[Dict[str, str]]:
    import os
    key, secret = os.environ.get(LIVE_KEY), os.environ.get(LIVE_SECRET)
    for path in paths.ENV_FILES:
        if key and secret:
            break
        env = alpaca._read_env(path)
        key, secret = env.get(LIVE_KEY), env.get(LIVE_SECRET)
    if not (key and secret):
        return None
    paper = alpaca._credentials() or {}
    if key == paper.get("APCA-API-KEY-ID"):
        return None                     # a paper key filed under the live name
    return {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}


def live_available() -> bool:
    return _live_headers() is not None


def live_enabled() -> bool:
    try:
        on = json.loads(_SETTINGS.read_text(encoding="utf-8")).get("autopilot_live") is True
    except (OSError, ValueError):
        on = False
    return on and live_available()


def set_live(on: bool) -> None:
    try:
        current = json.loads(_SETTINGS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        current = {}
    current["autopilot_live"] = bool(on)
    _SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS.write_text(json.dumps(current), encoding="utf-8")


# ---- the account itself ----------------------------------------------------

class Broker:
    """One Alpaca trading account, paper or live."""

    def __init__(self, live: bool = False) -> None:
        if live and not live_enabled():
            raise BrokerError("live trading is switched off")
        self.live = live
        self.base = LIVE if live else PAPER
        self.head = _live_headers() if live else alpaca._credentials()
        if not self.head:
            raise BrokerError("no Alpaca keys")

    def _call(self, method: str, path: str, **kw) -> Any:
        r = requests.request(method, self.base + path, headers=self.head, timeout=TIMEOUT, **kw)
        if r.status_code == 404 and method == "GET":
            return None
        if r.status_code >= 400:
            try:
                msg = r.json().get("message") or r.text
            except ValueError:
                msg = r.text
            raise BrokerError(f"{r.status_code}: {msg[:200]}")
        return r.json() if r.content else None

    def account(self) -> Dict[str, Any]:
        return self._call("GET", "/v2/account") or {}

    def clock(self) -> Dict[str, Any]:
        return self._call("GET", "/v2/clock") or {}

    def position(self, symbol: str) -> Optional[Dict[str, Any]]:
        return self._call("GET", f"/v2/positions/{symbol}")

    def positions(self) -> List[Dict[str, Any]]:
        return self._call("GET", "/v2/positions") or []

    def order(self, order_id: str) -> Optional[Dict[str, Any]]:
        return self._call("GET", f"/v2/orders/{order_id}", params={"nested": "true"})

    def open_orders(self, symbol: str) -> List[Dict[str, Any]]:
        return self._call("GET", "/v2/orders", params={"status": "open", "symbols": symbol,
                                                       "nested": "true"}) or []

    def bracket(self, symbol: str, qty: int, side: str, take_profit: float, stop_loss: float,
                tif: str, client_id: str) -> Dict[str, Any]:
        """A market entry with its take-profit and stop-loss attached, so the
        exits sit at the broker and hold even if this PC goes off."""
        if qty < 1:
            raise BrokerError("size rounds to zero shares")
        return self._call("POST", "/v2/orders", json={
            "symbol": symbol, "qty": str(int(qty)), "side": side, "type": "market",
            "time_in_force": tif, "order_class": "bracket", "client_order_id": client_id[:48],
            "take_profit": {"limit_price": f"{take_profit:.2f}"},
            "stop_loss": {"stop_price": f"{stop_loss:.2f}"},
        })

    def move_stop(self, order_id: str, stop: float) -> Dict[str, Any]:
        return self._call("PATCH", f"/v2/orders/{order_id}", json={"stop_price": f"{stop:.2f}"})

    def cancel(self, order_id: str) -> None:
        try:
            self._call("DELETE", f"/v2/orders/{order_id}")
        except BrokerError as exc:
            if not str(exc).startswith(("404", "422")):  # already gone / already filled
                raise

    def close(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Cancel whatever is resting on the symbol and flatten it at market."""
        return self._call("DELETE", f"/v2/positions/{symbol}", params={"cancel_orders": "true"})


# ---- market data -------------------------------------------------------------

_BARS: Dict[str, tuple] = {}


def bars(symbol: str, timeframe: str = "1Min", days: int = 1) -> List[Dict[str, Any]]:
    """Today's bars (and `days` back), oldest first, kept ten seconds so
    every bot on one symbol shares one request per cycle."""
    key = f"{symbol}:{timeframe}:{days}"
    hit = _BARS.get(key)
    if hit and time.time() - hit[0] < 10:
        return hit[1]
    head = alpaca._credentials()
    if not head:
        raise BrokerError("no Alpaca keys for market data")
    start = (datetime.now(timezone.utc) - timedelta(days=days + 3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out: List[Dict[str, Any]] = []
    params = {"timeframe": timeframe, "start": start, "limit": 10000, "feed": "iex",
              "adjustment": "raw"}
    for _ in range(5):
        r = requests.get(f"{DATA}/v2/stocks/{symbol}/bars", headers=head, params=params, timeout=TIMEOUT)
        if r.status_code >= 400:
            raise BrokerError(f"bars {r.status_code}: {r.text[:120]}")
        body = r.json()
        out += [{"t": b["t"], "o": b["o"], "h": b["h"], "l": b["l"], "c": b["c"], "v": b["v"]}
                for b in body.get("bars") or []]
        if not body.get("next_page_token"):
            break
        params["page_token"] = body["next_page_token"]
    _BARS[key] = (time.time(), out)
    return out


def latest_price(symbol: str) -> Optional[float]:
    head = alpaca._credentials()
    if not head:
        return None
    r = requests.get(f"{DATA}/v2/stocks/{symbol}/trades/latest", headers=head,
                     params={"feed": "iex"}, timeout=TIMEOUT)
    if r.status_code >= 400:
        return None
    return ((r.json() or {}).get("trade") or {}).get("p")
