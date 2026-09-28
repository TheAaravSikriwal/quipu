"""Watch-mode bots against a scripted market: no network, no orders.

  .venv/Scripts/python.exe backend/autopilot/selftest.py

Drives the engine's real cycle with a fake clock and fake prices, and
checks each exit and each limit does what the page says it does.
"""

from __future__ import annotations

import sys
import tempfile
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from autopilot import engine as E  # noqa: E402
from autopilot import rules as R  # noqa: E402

ET = R.ET
FAILS = []


def ok(name, cond, detail=""):
    print(("  [PASS] " if cond else "  [FAIL] ") + name + (f"  ({detail})" if detail and not cond else ""))
    if not cond:
        FAILS.append(name)


def bars_for(closes, vols=None, start=None):
    start = start or datetime.now(ET).replace(hour=9, minute=30, second=0, microsecond=0)
    out = []
    for i, c in enumerate(closes):
        t = (start + timedelta(minutes=i)).astimezone(ET)
        v = (vols or [1000] * len(closes))[i]
        out.append({"t": t.isoformat(), "o": c, "h": c + 0.05, "l": c - 0.05, "c": c, "v": v})
    return out


class Market:
    """What E.market returns, scripted."""
    def __init__(self):
        self.closes = [100.0] * 60
        self.vols = [1000] * 60
        self.price = 100.0
        self.now = datetime.now(ET).replace(hour=11, minute=0, second=0, microsecond=0)

    def __call__(self, symbol):
        b = bars_for(self.closes, self.vols)
        return R.context(b, [], self.price, now=self.now)


def main() -> int:
    tmp = Path(tempfile.mkdtemp()) / "autopilot.json"
    E.STORE = tmp
    E._DATA.clear()
    m = Market()
    E.market = m
    clock = {"is_open": True, "next_close": m.now.replace(hour=16, minute=0).isoformat(), "_at": time.time() + 1e9}
    E._ENGINE["market"] = clock
    real_now = datetime.now

    # Every "now" the engine reads is the scripted one.
    class FakeDT(datetime):
        @classmethod
        def now(cls, tz=None):
            return m.now if tz else real_now()
    E.datetime = FakeDT

    def cycle():
        E._cycle()

    momentum = {"enabled": True, "match": "all",
                "conditions": [{"type": "momentum", "dir": "up", "pct": 0.5, "minutes": 5, "vol_x": 2}]}

    print("validation")
    for bad, why in (({"symbol": "BE", "long": {"enabled": True, "conditions": []}}, "no conditions"),
                     ({"symbol": "../x", "long": momentum}, "bad symbol"),
                     ({"symbol": "BE", "mode": "live", "long": momentum}, "live while off")):
        try:
            E.clean(bad)
            ok(f"refuses {why}", False)
        except ValueError:
            ok(f"refuses {why}", True)
    c = E.clean({"symbol": "be", "long": momentum, "exits": {"take_profit_pct": 999, "stop_loss_pct": -3}})
    ok("bounds settings", c["exits"]["take_profit_pct"] == 50 and c["exits"]["stop_loss_pct"] == 0.05)
    ok("drops unknown fields", "evil" not in E._clean_side({"enabled": True, "conditions": [
        {"type": "rsi", "evil": "x", "value": 30}]})["conditions"][0])

    print("entry and take profit")
    bot = E.save_bot({"symbol": "BE", "mode": "watch", "pot": 1000, "long": momentum,
                      "size": {"dollars": 500},
                      "exits": {"take_profit_pct": 1.0, "stop_loss_pct": 0.5},
                      "limits": {"max_trades_day": 3, "max_loss_day": 8, "cooldown_min": 5},
                      "session": {"from": "09:35", "to": "15:50", "flatten": True, "flatten_min": 5}})
    bid = bot["id"]
    E.act(bid, "start")
    cycle()
    ok("no entry on a flat tape", E._DATA["bots"][bid]["state"]["position"] is None)
    m.closes = m.closes[:-5] + [100.1, 100.2, 100.4, 100.6, 100.8]
    m.vols = m.vols[:-5] + [3000] * 5
    m.price = 100.8
    cycle()
    pos = E._DATA["bots"][bid]["state"]["position"]
    ok("enters on the burst", pos is not None and pos["side"] == "long", str(pos))
    ok("sizes from the smaller of size and pot", pos and pos["qty"] == 4, str(pos and pos["qty"]))
    ok("target and stop from the entry", pos and pos["tp"] == 101.81 and pos["stop"] == 100.3, str(pos))
    m.price = 101.9
    cycle()
    b = E._DATA["bots"][bid]
    t = E._DATA["trades"][-1] if E._DATA["trades"] else {}
    ok("exits at the target", b["state"]["position"] is None and t.get("reason") == "take profit", str(t))
    ok("profit into the pot", abs(b["pot"] - (1000 + 4 * (101.81 - 100.8))) < 0.02, str(b["pot"]))

    print("cooldown")
    m.closes = m.closes[:-5] + [101.9, 102.0, 102.3, 102.5, 102.8]
    m.price = 102.8
    cycle()
    ok("no re-entry inside the cooldown", E._DATA["bots"][bid]["state"]["position"] is None
       and "cooling" in (E._DATA["bots"][bid]["state"].get("blocked") or ""),
       E._DATA["bots"][bid]["state"].get("blocked"))
    E._DATA["bots"][bid]["state"]["last_exit"] = 0

    print("stop loss, and the daily loss limit")
    cycle()
    pos = E._DATA["bots"][bid]["state"]["position"]
    ok("enters again after the cooldown", pos is not None)
    # Start the day's tally from zero with a $2 limit, so this one stop-out
    # (4 shares, 0.5% under 102.80 = -$2.04) is what crosses it.
    E._DATA["bots"][bid]["state"]["today"]["pnl"] = 0
    E._DATA["bots"][bid]["limits"]["max_loss_day"] = 2
    m.price = 100.0
    cycle()
    t = E._DATA["trades"][-1]
    ok("exits at the stop", t["reason"] == "stop loss", t["reason"])
    b = E._DATA["bots"][bid]
    ok("pauses past the daily loss limit", b["status"] == "paused", f"{b['status']} pnl {b['state']['today']}")

    print("trailing stop")
    trail = E.save_bot({"symbol": "TR", "mode": "watch", "pot": 1000, "long": momentum, "size": {"dollars": 1000},
                        "exits": {"take_profit_pct": 20, "stop_loss_pct": 1, "trail_pct": 1}})
    tid = trail["id"]
    E.act(bid, "stop")
    E.act(tid, "start")
    m.price = 100.8
    m.closes = m.closes[:-5] + [100.1, 100.2, 100.4, 100.6, 100.8]
    cycle()
    p = E._DATA["bots"][tid]["state"]["position"]
    ok("trail bot enters", p is not None)
    m.price = 105.0
    cycle()
    p = E._DATA["bots"][tid]["state"]["position"]
    ok("stop follows the price up", p and abs(p["stop"] - 103.95) < 0.01, str(p and p["stop"]))
    m.price = 103.9
    cycle()
    t = E._DATA["trades"][-1]
    ok("exits on the trailed stop, in profit", t["reason"] == "trailing stop" and t["pnl"] > 0, str(t))

    print("time stop, flatten, short side")
    E.act(tid, "stop")
    short = E.save_bot({"symbol": "SH", "mode": "watch", "pot": 1000, "size": {"dollars": 1000},
                        "long": {"enabled": False, "conditions": []},
                        "short": {"enabled": True, "match": "all", "conditions": [
                            {"type": "momentum", "dir": "down", "pct": 0.5, "minutes": 5}]},
                        "exits": {"take_profit_pct": 5, "stop_loss_pct": 5, "max_minutes": 10}})
    sid = short["id"]
    E.act(sid, "start")
    m.closes = [100.0] * 55 + [99.8, 99.6, 99.4, 99.2, 99.0]
    m.price = 99.0
    cycle()
    p = E._DATA["bots"][sid]["state"]["position"]
    ok("shorts on the drop", p is not None and p["side"] == "short", str(p))
    ok("short target below, stop above", p and p["tp"] < 99 < p["stop"], str(p))
    E._DATA["bots"][sid]["state"]["position"]["at"] -= 11 * 60
    m.price = 98.5
    cycle()
    t = E._DATA["trades"][-1]
    ok("time stop closes it", t["reason"].startswith("time stop"), t["reason"])
    ok("short profit counted the right way", t["pnl"] > 0, str(t["pnl"]))
    E._DATA["bots"][sid]["state"]["last_exit"] = 0
    E._DATA["bots"][sid]["exits"]["max_minutes"] = 0
    m.price = 98.0
    m.closes = [100.0] * 55 + [99.5, 99.2, 98.9, 98.5, 98.0]
    cycle()
    ok("short bot enters again", E._DATA["bots"][sid]["state"]["position"] is not None)
    m.now = m.now.replace(hour=15, minute=56)
    cycle()
    t = E._DATA["trades"][-1]
    ok("flattened before the close", t["reason"] == "flattened before the close", t["reason"])
    cycle()
    ok("no entries in the flatten window", E._DATA["bots"][sid]["state"]["position"] is None)

    print("pot, kill switch, delete")
    E.cash(sid, -5000)
    ok("pulling more than the pot empties it, no further", E._DATA["bots"][sid]["pot"] == 0)
    E.cash(sid, 250)
    ok("adding cash", E._DATA["bots"][sid]["pot"] == 250)
    m.now = m.now.replace(hour=11)
    E._DATA["bots"][sid]["state"]["last_exit"] = 0
    m.price = 97.0
    m.closes = [100.0] * 55 + [99.0, 98.6, 98.0, 97.5, 97.0]
    cycle()
    ok("enters with the smaller pot", (E._DATA["bots"][sid]["state"]["position"] or {}).get("qty") == 2,
       str(E._DATA["bots"][sid]["state"]["position"]))
    n = E.kill()
    cycle()
    ok("kill switch stops and closes", n >= 1 and E._DATA["bots"][sid]["state"]["position"] is None
       and E._DATA["bots"][sid]["status"] == "stopped")
    E.act(sid, "delete")
    ok("delete once flat", sid not in E._DATA["bots"])
    ok("saved to disk", tmp.exists() and '"trades"' in tmp.read_text(encoding="utf-8"))

    print(f"\n{'all passed' if not FAILS else str(len(FAILS)) + ' FAILED'}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
