"""Where QUIPU keeps things -- one answer for every module.

Two ways QUIPU runs, and they need different answers:

  From a checkout (how it is developed): everything stays where it always
  has -- caches in backend/cache, the page in frontend/, keys in .env
  files beside the code.

  As the standalone engine a visitor installs from wearechintu.com: the
  program is unpacked somewhere read-only and temporary, so caches cannot
  live beside it. They go to a folder of the visitor's own (on Windows,
  %LOCALAPPDATA%\\QUIPU), which survives restarts and updates. The page
  ships inside the program.

QUIPU_DATA overrides the data folder either way.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

FROZEN = bool(getattr(sys, "frozen", False))

#: One version for the engine, the page and the site's "update available".
VERSION = "1.0.0"

#: The code's own folder: the unpacked bundle when frozen, backend/ otherwise.
HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))

#: The repository root in a checkout. Meaningless in the engine.
ROOT = Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    if os.environ.get("QUIPU_DATA"):
        return Path(os.environ["QUIPU_DATA"])
    if FROZEN:
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return Path(base) / "QUIPU"
    return Path(__file__).resolve().parent / "cache"


#: Every cache, the settings file, and (in the engine) the visitor's .env.
CACHE = _data_dir()
CACHE.mkdir(parents=True, exist_ok=True)

#: The page itself.
FRONTEND = (HERE / "frontend") if FROZEN else ROOT / "frontend"

#: .env files, first found wins. The algotrader fallback is the developer's
#: own machine only -- a visitor's engine never looks outside its own folder.
ENV_FILES = [CACHE / ".env"] if FROZEN else [ROOT / ".env", ROOT.parent / "algotrader" / ".env"]


def cache(*parts: str) -> Path:
    """A path under the cache folder, with its parent made."""
    p = CACHE.joinpath(*parts)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
