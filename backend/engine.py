"""QUIPU Engine -- what a visitor runs to use QUIPU from wearechintu.com.

The site is the front door; this is the part that has to live on the
visitor's own computer, because it is what fetches: prices from Yahoo,
filings from the SEC, the news feeds, and (if they add keys) Alpaca. None
of those can be reached from a web page on another site, and all of them
limit how much any one connection may ask for -- so each visitor asks from
their own.

Double-clicked, it:
  1. starts QUIPU on this computer only (127.0.0.1, never the network)
  2. opens wearechintu.com/quipu, which finds it and shows the app
  3. stays open in a small window that says what it is doing; closing
     the window stops it

Already running? It says so and opens the page instead of fighting over
the port.

  QUIPU-Engine.exe [--port 8848] [--no-browser] [--open URL]
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
sys.path.insert(0, str(HERE if getattr(sys, "frozen", False) else Path(__file__).resolve().parent))

import paths  # noqa: E402

SITE = "https://wearechintu.com/quipu"


def _running(port: int) -> dict | None:
    """Is a QUIPU engine already answering on this port?"""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as r:
            body = json.loads(r.read().decode("utf-8"))
            return body if body.get("app") == "quipu" else None
    except Exception:                                        # noqa: BLE001
        return None


def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) != 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="QUIPU-Engine", description="Run QUIPU on this computer.")
    ap.add_argument("--port", type=int, default=int(os.environ.get("QUIPU_PORT", "8848")))
    ap.add_argument("--no-browser", action="store_true", help="do not open the page")
    ap.add_argument("--open", default=os.environ.get("QUIPU_OPEN", SITE),
                    help="the page to open once running (default: wearechintu.com/quipu)")
    a = ap.parse_args()

    if os.name == "nt":
        os.system(f"title QUIPU Engine {paths.VERSION}")
    print(f"QUIPU Engine {paths.VERSION}")
    print(f"  data kept in   {paths.CACHE}")

    already = _running(a.port)
    if already:
        print(f"  already running on this computer (version {already.get('version')}).")
        if not a.no_browser:
            webbrowser.open(a.open)
        return 0
    if not _port_free(a.port):
        print(f"  port {a.port} is taken by something else. Close it, or run with --port <another>.")
        print("  (The page looks on 8848; another port also needs ?port=<n> on the page address.)")
        input("\nPress Enter to close.")
        return 1

    import uvicorn
    from app import app

    def _open_when_up():
        for _ in range(120):
            if _running(a.port):
                print(f"  running         http://127.0.0.1:{a.port}")
                print("\nLeave this window open while you use QUIPU. Close it to stop.")
                if not a.no_browser:
                    webbrowser.open(a.open)
                return
            time.sleep(0.25)
        print("  it did not come up -- see the messages above.")

    threading.Thread(target=_open_when_up, daemon=True).start()
    # 127.0.0.1 only: the engine is for this computer, never the network.
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
