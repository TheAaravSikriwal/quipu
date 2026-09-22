"""Holding the scan.

Measuring ten thousand stocks takes about three minutes, so it cannot happen
inside a request. It happens once, in a thread, and everything afterwards
reads the result out of memory in microseconds.

The first caller does not wait for it either. It gets `status: scanning`
and a progress count, and the interface can say what it is doing instead of
hanging on a spinner for three minutes with nothing to show.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

import pandas as pd

from . import scan, universe

CACHE = Path(__file__).resolve().parent.parent / "cache" / "scan.pkl"
STAMP = CACHE.with_suffix(".stamp")
MAX_AGE_S = 6 * 3600          # intraday moves matter; a day-old scan does not

_lock = threading.Lock()
_state: Dict[str, Any] = {
    "df": None,
    "scanned_at": 0.0,
    "status": "empty",        # empty | scanning | ready | error
    "done": 0,
    "total": 0,
    "error": None,
}


def _load_disk() -> None:
    if _state["df"] is not None or not CACHE.exists():
        return
    try:
        df = pd.read_pickle(CACHE)
        at = float(STAMP.read_text()) if STAMP.exists() else CACHE.stat().st_mtime
        _state.update(df=df, scanned_at=at, status="ready", total=len(df), done=len(df))
    except Exception:
        pass                  # a bad cache just means we rescan


def _run() -> None:
    try:
        syms = universe.symbols()
        _state.update(status="scanning", done=0, total=len(syms), error=None)

        frames = []
        for i in range(0, len(syms), scan.CHUNK):
            batch = syms[i:i + scan.CHUNK]
            part = scan.scan(batch)
            if not part.empty:
                frames.append(part)
            _state["done"] = min(i + scan.CHUNK, len(syms))

        if not frames:
            raise RuntimeError("no symbols measured")
        df = pd.concat(frames)
        df = df[~df.index.duplicated()]

        CACHE.parent.mkdir(parents=True, exist_ok=True)
        df.to_pickle(CACHE)
        now = time.time()
        STAMP.write_text(str(now))
        _state.update(df=df, scanned_at=now, status="ready", done=len(syms))
    except Exception as exc:
        _state.update(status="error", error=str(exc))


def ensure(force: bool = False) -> None:
    """Start a scan if there is no usable one and none already running."""
    with _lock:
        _load_disk()
        if _state["status"] == "scanning":
            return
        fresh = (_state["df"] is not None
                 and time.time() - _state["scanned_at"] < MAX_AGE_S)
        if fresh and not force:
            return
        _state["status"] = "scanning"
        threading.Thread(target=_run, daemon=True, name="quipu-screen").start()


def frame() -> Optional[pd.DataFrame]:
    _load_disk()
    return _state["df"]


def meta() -> Dict[str, Any]:
    df = frame()
    age = time.time() - _state["scanned_at"] if _state["scanned_at"] else None
    return {
        "status": _state["status"],
        "measured": int(len(df)) if df is not None else 0,
        "done": _state["done"],
        "total": _state["total"],
        "scanned_at": _state["scanned_at"] or None,
        "age_s": int(age) if age is not None else None,
        "stale": bool(age is not None and age > MAX_AGE_S),
        "error": _state["error"],
    }
