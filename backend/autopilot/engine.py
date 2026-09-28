"""Autopilot: bots that trade one stock by rules the owner built.

A bot watches one symbol. When its entry conditions for a side are met
(rules.py) and nothing it has been told forbids it -- the time window, the
day's trade count, the day's loss limit, the cooldown since its last exit,
the cash in its pot -- it opens a position. Exits:

  take-profit and stop-loss   sent WITH the entry as one bracket order, so
                              they rest at the broker and hold if this PC
                              goes off or QUIPU stops
  trailing stop               the engine raises the resting stop as the
                              price moves its way
  time stop                   closed after N minutes whatever the price
  flatten                     closed N minutes before the close, unless the
                              bot is allowed to hold overnight

Three modes, per bot:
  watch   no orders at all: fills at the last price, exits the same way.
          The practice run, and the honest way to see a rule before money
  paper   Alpaca's paper account
  live    the real account; only when broker.live_enabled()

Each bot has a POT -- the money set aside for it. A trade is sized from
it, its profit or loss goes back into it, and cash can be added or pulled
at any time. Pulling cash does not move money at Alpaca; it lowers what
the bot is allowed to use.

Stored in the cache folder as autopilot.json. Runs in one background
thread, every ten seconds while any bot has something to do.
"""

from __future__ import annotations

import json
import math
import threading
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import paths
import safety

from . import broker as B
from . import rules as R

ET = ZoneInfo("America/New_York")
STORE = paths.CACHE / "autopilot.json"
TICK_S = 10
KEEP_TRADES = 500
KEEP_EVENTS = 80

_LOCK = threading.RLock()
_DATA: Dict[str, Any] = {}
_STARTED = [False]
_ENGINE: Dict[str, Any] = {"state": "idle", "at": 0.0, "error": None, "market": None}


# ---- storage -----------------------------------------------------------------

def _load() -> Dict[str, Any]:
    global _DATA
    if not _DATA:
        try:
            _DATA = json.loads(STORE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            _DATA = {}
        _DATA.setdefault("bots", {})
        _DATA.setdefault("trades", [])
    return _DATA


def _save() -> None:
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(_DATA, indent=1), encoding="utf-8")
    tmp.replace(STORE)


def _event(bot: Dict[str, Any], kind: str, say: str) -> None:
    ev = bot["state"].setdefault("events", [])
    ev.append({"at": time.time(), "kind": kind, "say": say})
    del ev[:-KEEP_EVENTS]


# ---- what a bot is -------------------------------------------------------------

def _f(v: Any, lo: float, hi: float, default: float) -> float:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return default
    if math.isnan(x):
        return default
    return min(max(x, lo), hi)


def _hm(v: Any, default: str) -> str:
    s = str(v or default)
    try:
        h, m = (int(p) for p in s.split(":"))
        if 0 <= h < 24 and 0 <= m < 60:
            return f"{h:02d}:{m:02d}"
    except ValueError:
        pass
    return default


def _clean_side(raw: Any) -> Dict[str, Any]:
    raw = raw if isinstance(raw, dict) else {}
    conds = []
    for c in (raw.get("conditions") or [])[:12]:
        if not isinstance(c, dict) or c.get("type") not in R.TYPES:
            continue
        # Only the settings a block reads, each bounded; nothing else survives.
        keep = {"type": c["type"]}
        for k in ("dir", "op", "timeframe"):
            if isinstance(c.get(k), str) and len(c[k]) <= 16:
                keep[k] = c[k]
        for k, lo, hi in (("pct", -50, 50), ("minutes", 1, 120), ("vol_x", 0, 50), ("level", 0, 1e6),
                          ("value", -1e6, 1e6), ("period", 2, 100)):
            if k in c:
                keep[k] = _f(c[k], lo, hi, 0)
        for k in ("from", "to"):
            if k in c:
                keep[k] = _hm(c[k], "09:30" if k == "from" else "16:00")
        conds.append(keep)
    return {"enabled": bool(raw.get("enabled")) and bool(conds),
            "match": "any" if raw.get("match") == "any" else "all", "conditions": conds}


def clean(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """A bot's settings as the page sent them, checked and bounded. Raises
    ValueError on anything that cannot be traded."""
    symbol = safety.ticker(cfg.get("symbol"))
    if not symbol:
        raise ValueError("a valid symbol is required")
    mode = cfg.get("mode") if cfg.get("mode") in ("watch", "paper", "live") else "watch"
    if mode == "live" and not B.live_enabled():
        raise ValueError("live trading is switched off -- turn it on in the Autopilot panel first")
    ex, lim, ses, size = (cfg.get(k) if isinstance(cfg.get(k), dict) else {}
                          for k in ("exits", "limits", "session", "size"))
    bot = {
        "name": str(cfg.get("name") or f"{symbol} bot")[:60],
        "symbol": symbol,
        "mode": mode,
        "long": _clean_side(cfg.get("long")),
        "short": _clean_side(cfg.get("short")),
        "size": {"dollars": _f(size.get("dollars"), 1, 1e6, 500)},
        "exits": {
            "take_profit_pct": _f(ex.get("take_profit_pct"), 0.05, 50, 1.0),
            "stop_loss_pct": _f(ex.get("stop_loss_pct"), 0.05, 50, 0.5),
            "trail_pct": _f(ex.get("trail_pct"), 0, 50, 0),
            "max_minutes": _f(ex.get("max_minutes"), 0, 60 * 24 * 30, 0),
        },
        "limits": {
            "max_trades_day": int(_f(lim.get("max_trades_day"), 1, 200, 5)),
            "max_loss_day": _f(lim.get("max_loss_day"), 1, 1e6, 100),
            "cooldown_min": _f(lim.get("cooldown_min"), 0, 600, 5),
        },
        "session": {
            "from": _hm(ses.get("from"), "09:35"),
            "to": _hm(ses.get("to"), "15:50"),
            "flatten": ses.get("flatten", True) is not False,
            "flatten_min": _f(ses.get("flatten_min"), 1, 120, 5),
        },
    }
    if not bot["long"]["enabled"] and not bot["short"]["enabled"]:
        raise ValueError("switch on a long or a short entry, with at least one condition")
    return bot


def _fresh_state() -> Dict[str, Any]:
    return {"position": None, "pending": None, "closing": None, "today": {}, "last_exit": 0.0,
            "last_check": None, "events": []}


# ---- the market, once per symbol per cycle -----------------------------------------

def market(symbol: str) -> Dict[str, Any]:
    price = B.latest_price(symbol)
    return R.context(B.bars(symbol, "1Min", 1), B.bars(symbol, "5Min", 1), price)


def _clock() -> Dict[str, Any]:
    hit = _ENGINE.get("market")
    if hit and time.time() - hit["_at"] < 30:
        return hit
    c = B.Broker(live=False).clock()
    c["_at"] = time.time()
    _ENGINE["market"] = c
    return c


def _close_at(clock: Dict[str, Any]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(clock["next_close"]).astimezone(ET)
    except (KeyError, ValueError):
        return None


# ---- deciding ----------------------------------------------------------------------

def _today(bot: Dict[str, Any]) -> Dict[str, Any]:
    st, d = bot["state"], datetime.now(ET).date().isoformat()
    if st.get("today", {}).get("date") != d:
        st["today"] = {"date": d, "trades": 0, "pnl": 0.0}
    return st["today"]


def _flatten_due(bot: Dict[str, Any], clock: Dict[str, Any]) -> bool:
    ses = bot["session"]
    if not ses["flatten"] or not clock.get("is_open"):
        return False
    now = datetime.now(ET)
    close = _close_at(clock)
    end_h, end_m = (int(p) for p in ses["to"].split(":"))
    end = now.replace(hour=end_h, minute=end_m, second=0, microsecond=0)
    if close:
        end = min(end, close.replace(second=0, microsecond=0) - _mins(ses["flatten_min"]))
    return now >= end


def _mins(m: float):
    from datetime import timedelta
    return timedelta(minutes=m)


def _may_enter(bot: Dict[str, Any], clock: Dict[str, Any]) -> Optional[str]:
    """Why the bot may not open a position right now, or None."""
    if bot["status"] != "running":
        return "not running"
    if not clock.get("is_open"):
        return "market closed"
    now = datetime.now(ET)
    a = tuple(int(p) for p in bot["session"]["from"].split(":"))
    z = tuple(int(p) for p in bot["session"]["to"].split(":"))
    if not (a <= (now.hour, now.minute) < z):
        return f"outside its hours ({bot['session']['from']}-{bot['session']['to']} ET)"
    if _flatten_due(bot, clock):
        return "inside the flatten window before the close"
    t = _today(bot)
    if t["trades"] >= bot["limits"]["max_trades_day"]:
        return f"{t['trades']} trades today, its limit"
    if t["pnl"] <= -bot["limits"]["max_loss_day"]:
        return "down its daily loss limit"
    wait = bot["limits"]["cooldown_min"] * 60 - (time.time() - bot["state"].get("last_exit", 0))
    if wait > 0:
        return f"cooling down {int(wait // 60)}m{int(wait % 60):02d}s after its last exit"
    if bot["pot"] < 1:
        return "no cash in its pot"
    return None


def _levels(side: str, price: float, ex: Dict[str, float]) -> Tuple[float, float]:
    tp, sl = ex["take_profit_pct"] / 100, ex["stop_loss_pct"] / 100
    if side == "long":
        return round(price * (1 + tp), 2), round(price * (1 - sl), 2)
    return round(price * (1 - tp), 2), round(price * (1 + sl), 2)


def size_for(bot: Dict[str, Any], price: float) -> int:
    dollars = min(bot["size"]["dollars"], bot["pot"])
    return int(dollars // price) if price else 0


# ---- recording -------------------------------------------------------------------

def _record_exit(bot: Dict[str, Any], price: float, reason: str) -> None:
    st, pos = bot["state"], bot["state"]["position"]
    sign = 1 if pos["side"] == "long" else -1
    pnl = round((price - pos["entry"]) * pos["qty"] * sign, 2)
    trade = {
        "id": pos.get("trade_id") or uuid.uuid4().hex[:12], "bot": bot["id"], "bot_name": bot["name"],
        "symbol": bot["symbol"], "mode": bot["mode"], "side": pos["side"], "qty": pos["qty"],
        "entry": pos["entry"], "entry_at": pos["at"], "exit": round(price, 4), "exit_at": time.time(),
        "reason": reason, "pnl": pnl,
        "pnl_pct": round((price / pos["entry"] - 1) * 100 * sign, 3) if pos["entry"] else None,
    }
    _DATA["trades"].append(trade)
    del _DATA["trades"][:-KEEP_TRADES]
    bot["pot"] = round(bot["pot"] + pnl, 2)
    t = _today(bot)
    t["pnl"] = round(t["pnl"] + pnl, 2)
    st["position"], st["closing"], st["last_exit"] = None, None, time.time()
    _event(bot, "exit", f"closed {pos['side']} {pos['qty']} @ {price:.2f} ({reason}): "
                        f"{'+' if pnl >= 0 else '-'}${abs(pnl):,.2f}")
    if t["pnl"] <= -bot["limits"]["max_loss_day"] and bot["status"] == "running":
        bot["status"] = "paused"
        _event(bot, "state", f"paused: down ${-t['pnl']:,.2f} today, past its "
                             f"${bot['limits']['max_loss_day']:,.0f} daily limit")


def _open_position(bot, side, qty, entry, tp, sl, **extra) -> None:
    bot["state"]["position"] = {"side": side, "qty": qty, "entry": round(entry, 4), "at": time.time(),
                                "tp": tp, "stop": sl, "water": entry, "trade_id": uuid.uuid4().hex[:12],
                                **extra}
    _today(bot)["trades"] += 1


# ---- one bot, one cycle ------------------------------------------------------------

def _entries(bot: Dict[str, Any], x: Dict[str, Any]) -> Optional[str]:
    """Which side's entry is met now, recording what every condition read."""
    check = {"at": time.time(), "price": x.get("price")}
    hit = None
    for side in ("long", "short"):
        if not bot[side]["enabled"]:
            continue
        met, got = R.check(bot[side], x)
        check[side] = {"met": met, "conditions": got}
        if met and hit is None:
            hit = side
    bot["state"]["last_check"] = check
    return hit


def _exit_reason(bot: Dict[str, Any], price: float, clock: Dict[str, Any]) -> Optional[str]:
    pos, ex = bot["state"]["position"], bot["exits"]
    if bot["status"] == "stopped":
        return "bot stopped"
    if ex["max_minutes"] and time.time() - pos["at"] >= ex["max_minutes"] * 60:
        return f"time stop, {ex['max_minutes']:g} min"
    if _flatten_due(bot, clock):
        return "flattened before the close"
    return None


def _trail(bot: Dict[str, Any], price: float) -> Optional[float]:
    """The new stop if the trail has moved it, else None."""
    pos, trail = bot["state"]["position"], bot["exits"]["trail_pct"] / 100
    if not trail:
        return None
    if pos["side"] == "long":
        pos["water"] = max(pos["water"], price)
        new = round(pos["water"] * (1 - trail), 2)
        return new if new > pos["stop"] + 0.01 else None
    pos["water"] = min(pos["water"], price)
    new = round(pos["water"] * (1 + trail), 2)
    return new if new < pos["stop"] - 0.01 else None


def _tick_watch(bot: Dict[str, Any], clock: Dict[str, Any]) -> None:
    st = bot["state"]
    if st["position"] or (bot["status"] == "running" and clock.get("is_open")):
        x = market(bot["symbol"])
    else:
        return
    price = x["price"]
    if not price:
        return
    st["mark"] = price
    if st["position"]:
        pos = st["position"]
        long = pos["side"] == "long"
        if (long and price >= pos["tp"]) or (not long and price <= pos["tp"]):
            return _record_exit(bot, pos["tp"], "take profit")
        if (long and price <= pos["stop"]) or (not long and price >= pos["stop"]):
            return _record_exit(bot, pos["stop"], "stop loss" if pos["stop"] == pos.get("first_stop") else "trailing stop")
        new = _trail(bot, price)
        if new:
            pos["stop"] = new
            _event(bot, "trail", f"stop moved to {new:.2f}")
        why = _exit_reason(bot, price, clock)
        if why:
            _record_exit(bot, price, why)
        return
    why = _may_enter(bot, clock)
    side = _entries(bot, x)
    if why:
        st["blocked"] = why
        return
    st["blocked"] = None
    if not side:
        return
    qty = size_for(bot, price)
    if qty < 1:
        st["blocked"] = f"${min(bot['size']['dollars'], bot['pot']):,.0f} buys less than one share at {price:.2f}"
        return
    tp, sl = _levels(side, price, bot["exits"])
    _open_position(bot, side, qty, price, tp, sl, first_stop=sl)
    _event(bot, "entry", f"{'bought' if side == 'long' else 'shorted'} {qty} @ {price:.2f} "
                         f"(simulated) -- target {tp:.2f}, stop {sl:.2f}")


def _stop_leg(order: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    return next((l for l in order.get("legs") or [] if l.get("type") in ("stop", "stop_limit")), None)


def _tick_broker(bot: Dict[str, Any], clock: Dict[str, Any]) -> None:
    st = bot["state"]
    br = B.Broker(live=bot["mode"] == "live")
    sym = bot["symbol"]

    if st.get("pending"):
        o = br.order(st["pending"]["id"]) or {}
        status = o.get("status")
        if bot["status"] == "stopped" and status not in ("filled", "partially_filled"):
            br.cancel(st["pending"]["id"])
            st["pending"] = None
            _event(bot, "state", "entry order cancelled: bot stopped")
            return
        if status == "filled":
            side = st["pending"]["side"]
            entry = float(o.get("filled_avg_price") or 0)
            leg = _stop_leg(o)
            tp_leg = next((l for l in o.get("legs") or [] if l.get("type") == "limit"), None)
            _open_position(bot, side, int(float(o.get("filled_qty") or 0)), entry,
                           float(tp_leg["limit_price"]) if tp_leg else st["pending"]["tp"],
                           float(leg["stop_price"]) if leg else st["pending"]["sl"],
                           order_id=o["id"], stop_id=leg["id"] if leg else None,
                           first_stop=float(leg["stop_price"]) if leg else st["pending"]["sl"])
            st["pending"] = None
            _event(bot, "fill", f"filled {side} {st['position']['qty']} @ {entry:.2f}")
        elif status in ("canceled", "expired", "rejected", "done_for_day"):
            _event(bot, "error", f"entry order {status}")
            st["pending"] = None
        return

    if st.get("closing"):
        o = br.order(st["closing"]["id"]) or {}
        if o.get("status") == "filled":
            _record_exit(bot, float(o["filled_avg_price"]), st["closing"]["reason"])
        elif o.get("status") in ("canceled", "expired", "rejected"):
            _event(bot, "error", f"closing order {o.get('status')} -- will try again")
            st["closing"] = None
        return

    if st.get("position"):
        pos = st["position"]
        if br.position(sym) is None:
            # Flat at the broker: one of the bracket's legs filled.
            o = br.order(pos["order_id"]) or {}
            leg = next((l for l in o.get("legs") or [] if l.get("status") == "filled"), None)
            if leg:
                reason = "take profit" if leg.get("type") == "limit" else (
                    "stop loss" if float(leg.get("stop_price") or 0) == pos.get("first_stop") else "trailing stop")
                return _record_exit(bot, float(leg["filled_avg_price"]), reason)
            return _record_exit(bot, B.latest_price(sym) or pos["entry"], "closed outside QUIPU")
        price = B.latest_price(sym) or pos["entry"]
        st["mark"] = price
        new = _trail(bot, price)
        if new and pos.get("stop_id"):
            br.move_stop(pos["stop_id"], new)
            pos["stop"] = new
            _event(bot, "trail", f"stop moved to {new:.2f}")
        why = _exit_reason(bot, price, clock)
        if why:
            o = br.close(sym) or {}
            st["closing"] = {"id": o.get("id"), "reason": why}
            _event(bot, "order", f"closing: {why}")
            if not o.get("id"):
                _record_exit(bot, price, why)
        return

    if bot["status"] != "running" or not clock.get("is_open"):
        return
    x = market(sym)
    st["mark"] = x["price"]
    why = _may_enter(bot, clock)
    side = _entries(bot, x)
    if why:
        st["blocked"] = why
        return
    st["blocked"] = None
    if not side or not x["price"]:
        return
    if br.position(sym) is not None:
        st["blocked"] = f"the account already holds {sym} -- one position per symbol"
        return
    price = x["price"]
    qty = size_for(bot, price)
    if qty < 1:
        st["blocked"] = f"${min(bot['size']['dollars'], bot['pot']):,.0f} buys less than one share at {price:.2f}"
        return
    tp, sl = _levels(side, price, bot["exits"])
    tif = "day" if bot["session"]["flatten"] else "gtc"
    o = br.bracket(sym, qty, "buy" if side == "long" else "sell", tp, sl, tif,
                   f"quipu-{bot['id']}-{uuid.uuid4().hex[:8]}")
    st["pending"] = {"id": o["id"], "side": side, "tp": tp, "sl": sl}
    _event(bot, "order", f"{'buy' if side == 'long' else 'short'} {qty} at market "
                         f"({bot['mode']}) -- target {tp:.2f}, stop {sl:.2f}")


def _busy(bot: Dict[str, Any]) -> bool:
    st = bot["state"]
    return bot["status"] == "running" or bool(st.get("position") or st.get("pending") or st.get("closing"))


def _cycle() -> float:
    with _LOCK:
        bots = [b for b in _load()["bots"].values() if _busy(b)]
    if not bots:
        _ENGINE.update(state="idle", at=time.time())
        return 5.0
    try:
        clock = _clock()
    except Exception as exc:                                # noqa: BLE001
        _ENGINE.update(state="error", error=f"clock: {exc}", at=time.time())
        return 30.0
    for bot in bots:
        with _LOCK:
            try:
                (_tick_watch if bot["mode"] == "watch" else _tick_broker)(bot, clock)
                bot["state"]["error"] = None
            except Exception as exc:                        # noqa: BLE001
                msg = f"{type(exc).__name__}: {exc}"[:200]
                if bot["state"].get("error") != msg:
                    _event(bot, "error", msg)
                bot["state"]["error"] = msg
        _ENGINE.update(state="running", error=None, at=time.time())
    with _LOCK:
        _save()
    return TICK_S if clock.get("is_open") else 30.0


def _loop() -> None:
    while True:
        try:
            wait = _cycle()
        except Exception as exc:                            # noqa: BLE001
            _ENGINE.update(state="error", error=str(exc)[:200], at=time.time())
            wait = 30.0
        time.sleep(wait)


def start() -> None:
    with _LOCK:
        if _STARTED[0]:
            return
        _STARTED[0] = True
        _load()
    threading.Thread(target=_loop, name="autopilot", daemon=True).start()


# ---- what the routes call ------------------------------------------------------------

def view() -> Dict[str, Any]:
    try:
        _clock()        # so the page knows whether the market is open before any bot runs
    except Exception:                                       # noqa: BLE001
        pass
    with _LOCK:
        d = _load()
        bots = [dict(b, state=dict(b["state"])) for b in d["bots"].values()]
        trades = list(d["trades"][-100:])
    account = None
    try:
        a = B.Broker(live=False).account()
        account = {k: a.get(k) for k in ("equity", "cash", "buying_power", "status", "trading_blocked")}
    except Exception as exc:                                # noqa: BLE001
        account = {"error": str(exc)[:160]}
    live = None
    if B.live_enabled():
        try:
            a = B.Broker(live=True).account()
            live = {k: a.get(k) for k in ("equity", "cash", "buying_power", "status", "trading_blocked")}
        except Exception as exc:                            # noqa: BLE001
            live = {"error": str(exc)[:160]}
    return {
        "engine": {k: v for k, v in _ENGINE.items() if k != "market"},
        "market": {k: v for k, v in (_ENGINE.get("market") or {}).items() if not k.startswith("_")},
        "live": {"available": B.live_available(), "enabled": B.live_enabled(), "account": live},
        "paper": account,
        "bots": sorted(bots, key=lambda b: b.get("created", 0)),
        "trades": trades,
        "templates": R.TEMPLATES,
    }


def save_bot(cfg: Dict[str, Any]) -> Dict[str, Any]:
    bot = clean(cfg)
    with _LOCK:
        d = _load()
        bid = cfg.get("id") if cfg.get("id") in d["bots"] else None
        if bid:
            have = d["bots"][bid]
            if (have["state"].get("position") or have["state"].get("pending")) and \
                    (bot["symbol"] != have["symbol"] or bot["mode"] != have["mode"]):
                raise ValueError("close its position before changing its symbol or mode")
            have.update(bot, updated=time.time())
            _event(have, "state", "settings changed")
            out = have
        else:
            bid = uuid.uuid4().hex[:10]
            out = d["bots"][bid] = {**bot, "id": bid, "status": "stopped", "created": time.time(),
                                    "updated": time.time(), "pot": _f(cfg.get("pot"), 0, 1e7, 1000),
                                    "state": _fresh_state()}
            _event(out, "state", f"created, {out['mode']} mode, ${out['pot']:,.0f} in its pot")
        _save()
        return out


def act(bot_id: str, action: str) -> Dict[str, Any]:
    with _LOCK:
        d = _load()
        bot = d["bots"].get(bot_id)
        if not bot:
            raise KeyError("no such bot")
        st = bot["state"]
        if action == "start":
            if bot["mode"] != "watch":
                clash = [b for b in d["bots"].values() if b is not bot and b["symbol"] == bot["symbol"]
                         and b["mode"] != "watch" and _busy(b)]
                if clash:
                    raise ValueError(f"'{clash[0]['name']}' already trades {bot['symbol']} on the "
                                     "account -- one broker bot per symbol")
            if bot["mode"] == "live" and not B.live_enabled():
                raise ValueError("live trading is switched off")
            bot["status"] = "running"
            _event(bot, "state", "started")
        elif action == "pause":
            bot["status"] = "paused"
            _event(bot, "state", "paused -- no new trades; an open position keeps its stop and target")
        elif action == "stop":
            bot["status"] = "stopped"
            _event(bot, "state", "stopped -- any open position is being closed")
        elif action == "delete":
            if st.get("position") or st.get("pending") or st.get("closing"):
                raise ValueError("stop it and let its position close first")
            del d["bots"][bot_id]
        else:
            raise ValueError("unknown action")
        _save()
        return bot


def cash(bot_id: str, amount: float) -> Dict[str, Any]:
    with _LOCK:
        bot = _load()["bots"].get(bot_id)
        if not bot:
            raise KeyError("no such bot")
        amount = _f(amount, -1e7, 1e7, 0)
        before = bot["pot"]
        bot["pot"] = round(max(before + amount, 0.0), 2)
        moved = bot["pot"] - before
        _event(bot, "cash", f"{'added' if moved >= 0 else 'pulled'} ${abs(moved):,.2f}; pot now ${bot['pot']:,.2f}")
        _save()
        return bot


def kill() -> int:
    """Every bot stopped; the engine closes their positions next cycle."""
    with _LOCK:
        n = 0
        for bot in _load()["bots"].values():
            if bot["status"] != "stopped" or bot["state"].get("position"):
                bot["status"] = "stopped"
                _event(bot, "state", "stopped by the kill switch")
                n += 1
        _save()
    return n


def check(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Read a bot's conditions against the market now, without saving it."""
    bot = clean(cfg)
    x = market(bot["symbol"])
    out = {"price": x["price"], "at": time.time(), "sides": {}}
    for side in ("long", "short"):
        if bot[side]["enabled"]:
            met, got = R.check(bot[side], x)
            out["sides"][side] = {"met": met, "conditions": got}
    pot = _f(cfg.get("pot"), 0, 1e7, 1000)
    if x["price"]:
        qty = int(min(bot["size"]["dollars"], pot) // x["price"])
        out["size"] = {"qty": qty, "cost": round(qty * x["price"], 2)}
        out["levels"] = {s: dict(zip(("take_profit", "stop_loss"), _levels(s, x["price"], bot["exits"])))
                         for s in ("long", "short")}
    return out


def set_live(on: bool) -> Dict[str, Any]:
    if on and not B.live_available():
        raise ValueError("no live keys: add ALPACA_LIVE_API_KEY_ID and ALPACA_LIVE_API_SECRET_KEY first")
    with _LOCK:
        if not on:
            # With live off QUIPU cannot reach the live account at all, so a
            # live position left open would be one it could no longer close.
            holding = [b for b in _load()["bots"].values() if b["mode"] == "live" and (
                b["state"].get("position") or b["state"].get("pending") or b["state"].get("closing"))]
            if holding:
                raise ValueError(f"'{holding[0]['name']}' still has a live position or order -- "
                                 "stop it and let it close first")
            running = [b for b in _load()["bots"].values() if b["mode"] == "live" and _busy(b)]
            for b in running:
                b["status"] = "paused"
                _event(b, "state", "paused: live trading switched off")
            _save()
    B.set_live(on)
    return {"available": B.live_available(), "enabled": B.live_enabled()}
