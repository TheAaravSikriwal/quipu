# PyInstaller recipe for QUIPU-Engine.exe -- the part of QUIPU a visitor to
# wearechintu.com runs on their own computer.
#
#   .venv\Scripts\python.exe -m PyInstaller packaging\engine.spec --noconfirm
#
# One file, Python and every dependency inside it, so a visitor needs
# nothing installed. What goes in: every backend module, the page, and the
# data files a few libraries read at run time (trafilatura's extractors,
# the timezone database the market clock needs on Windows, yfinance's
# compiled HTTP client). What stays out: tests, caches, and any keys --
# the engine reads a visitor's own keys from their own data folder.

from pathlib import Path
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"

# Every backend module by name: they are imported off sys.path rather than
# as one package, which PyInstaller cannot follow on its own.
skip = {"verify", "engine"}
backend_modules = []
for p in BACKEND.rglob("*.py"):
    if "cache" in p.parts or "testdata" in p.parts or "__pycache__" in p.parts:
        continue
    rel = p.relative_to(BACKEND).with_suffix("")
    name = ".".join(rel.parts)
    if name.endswith(".__init__"):
        name = name[: -len(".__init__")]
    if name.split(".")[0] in skip:
        continue
    backend_modules.append(name)

datas, binaries, hidden = [], [], list(backend_modules)
hidden += collect_submodules("uvicorn")
for pkg in ("trafilatura", "justext", "courlan", "htmldate", "tzdata", "certifi", "dateparser"):
    try:
        datas += collect_data_files(pkg)
    except Exception:
        pass
for pkg in ("curl_cffi", "yfinance"):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hidden += h

# The page, without its tests.
for f in FRONTEND.iterdir():
    if f.is_file() and not f.name.endswith(".test.js") and f.name != "lift.js":
        datas.append((str(f), "frontend"))

a = Analysis(
    [str(BACKEND / "engine.py")],
    pathex=[str(BACKEND)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "matplotlib", "IPython", "pytest", "notebook"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="QUIPU-Engine",
    console=True,          # the small window that says it is running, and stops it when closed
    upx=False,
)
