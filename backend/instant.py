"""Instant: what lands first about one company, the moment it lands.

The Wire panel reads aggregators -- Yahoo, Google News, Seeking Alpha --
every ninety seconds, and an aggregator only writes a story up after a
wire has run it. By the time a headline arrives there the price has
usually already moved on it. This reads the places things are published
FIRST, and says how many seconds after publication each one got here:

  Alpaca news stream   Benzinga's newswire, pushed down one socket as it
                       is published. One connection for every ticker.
  SEC filings          the company's submissions file, every 15 s. An
                       8-K is on it within a second of the SEC accepting it.
  Press wires          PR Newswire and Business Wire, every 20 s: where a
                       company's own announcements go out.
  Google News          the last hour only, every 45 s. An aggregator, but
                       the widest net for local and trade press.
  Finnhub              every 30 s, when FINNHUB_API_KEY is set.

No free feed reliably beats the tape -- the price often moves as the
headline lands -- so the page also raises its own alarms when the price
or volume starts moving before any story has explained it (the
frontend's tripwires).

Everything here runs only while somebody has the company open: a desk
nobody has asked about for ten minutes is closed, and with no desks open
the stream disconnects.
"""

from __future__ import annotations

import calendar
import hashlib
import json
import os
import re
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote
from zoneinfo import ZoneInfo

import feedparser
import requests

import wire
from sources import alpaca, news_rss, sec_edgar

ET = ZoneInfo("America/New_York")

IDLE_S = 600          # a desk nobody has polled for this long is closed
MAX_DESKS = 12        # visitors can open desks too; the oldest go first
KEEP = 150            # events kept per desk
EARLIER_S = 3 * 86400  # on opening, the last three days, marked as earlier
FRESH_S = 1800        # a later poll's item older than this is not "new"

EVERY = {"edgar": 15, "wires": 20, "google": 45, "finnhub": 30, "alpaca": 15}

WIRES = [
    ("PR Newswire", "https://www.prnewswire.com/rss/news-releases-list.rss"),
    ("Business Wire", "https://feed.businesswire.com/rss/home/?rss=G1QFDERJXkJeGVtRWA=="),
]
STREAM_URL = "wss://stream.data.alpaca.markets/v1beta1/news"
BROWSER = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
}

_LOCK = threading.Lock()
_DESKS: Dict[str, "Desk"] = {}
_SEQ = [0]
_STARTED = [False]
_POOL = ThreadPoolExecutor(max_workers=8, thread_name_prefix="instant")


def _next_seq() -> int:
    with _LOCK:
        _SEQ[0] += 1
        return _SEQ[0]


# ---- names ---------------------------------------------------------------

_SUFFIX = re.compile(
    r"\b(class [a-z]\b|common stock|ordinary shares|american depositary shares|"
    r"corporation|corp|incorporated|inc|holdings?|company|co|ltd|limited|plc|"
    r"n\.v|s\.a|ag|se|lp|llc)\b\.?", re.I)


def short_name(name: str, symbol: str) -> str:
    """'Bloom Energy Corporation Class A Common Stock' -> 'Bloom Energy'.
    What a press release or a headline actually calls the company."""
    s = _SUFFIX.sub(" ", name or "")
    s = re.sub(r"\s+", " ", s).strip(" ,.&-")
    if len(s) < 4 or s.upper() == symbol.upper():
        return ""
    return s


def _key(title: str, url: Optional[str]) -> str:
    """The same story from two feeds is one story. Keyed on the first
    words of the headline, which survive a feed's own punctuation."""
    words = re.findall(r"[a-z0-9]+", (title or "").lower())
    base = " ".join(words[:12]) if len(words) >= 4 else (url or title or "")
    return hashlib.sha1(base.encode("utf-8")).hexdigest()[:16]


# ---- one company's desk ----------------------------------------------------

class Desk:
    def __init__(self, symbol: str, company: str) -> None:
        self.symbol = symbol
        self.name = short_name(company, symbol)
        self.cik: Optional[str] = None
        self.opened = time.time()
        self.seen = time.time()
        self.events: deque = deque(maxlen=KEEP)
        self.by_key: Dict[str, Dict[str, Any]] = {}
        self.due: Dict[str, float] = {k: 0.0 for k in EVERY}
        self.ran: set = set()          # jobs that have had their first run
        self.running: set = set()
        self.status: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()
        # A release names the company by ticker in brackets, "(NYSE: BE)",
        # or by name. The exchange is matched loosely, the ticker exactly.
        ticker = (r"\((?i:nyse|nasdaq|nyse american|nyse arca|nyse mkt|cboe|otcqx|otcqb|otc"
                  r"|tsx|tsxv|nasdaqgs|nasdaqgm|nasdaqcm)[a-z ]*:\s*" + re.escape(symbol) + r"\)")
        name = (r"|\b" + re.escape(self.name) + r"\b") if self.name else ""
        self.pattern = re.compile(ticker + name)

    def set_status(self, feed: str, ok: bool, note: str = "") -> None:
        self.status[feed] = {"ok": ok, "note": note, "at": time.time()}

    def add(self, kind: str, source: str, title: str, url: Optional[str],
            published: Optional[float], fresh: bool, summary: str = "",
            extra: Optional[Dict[str, Any]] = None) -> None:
        now = time.time()
        if not title:
            return
        if published and now - published > EARLIER_S:
            return
        # A later poll can still turn up something hours old -- a feed
        # indexing late. That is not news arriving, and saying "arrived
        # 5 h after publishing" as if it were would be misleading.
        if fresh and published and now - published > FRESH_S:
            fresh = False
        lag = max(now - published, 0.0) if (fresh and published) else None
        key = _key(title, url)
        with self.lock:
            have = self.by_key.get(key)
            if have:
                if source != have["source"] and all(a["source"] != source for a in have["also"]):
                    have["also"].append({"source": source, "lag": lag, "url": url})
                    have["seq"] = _next_seq()
                return
            ev = {
                "id": key, "seq": _next_seq(), "kind": kind, "source": source,
                "title": title.strip(), "url": url, "summary": (summary or "").strip()[:400],
                "published": published, "received": now, "lag": lag, "fresh": fresh,
                "also": [], **(extra or {}),
            }
            self.by_key[key] = ev
            self.events.append(ev)


# ---- the feeds -------------------------------------------------------------

def _epoch_iso(text: Optional[str]) -> Optional[float]:
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def _job_edgar(desk: Desk, first: bool) -> None:
    if desk.cik is None:
        hit = sec_edgar.lookup_cik(desk.symbol)
        desk.cik = hit["cik"] if hit else ""
    if not desk.cik:
        desk.set_status("SEC filings", False, "no SEC registrant for this symbol")
        desk.due["edgar"] = time.time() + 3600
        return
    r = requests.get(f"https://data.sec.gov/submissions/CIK{desk.cik}.json",
                     headers=sec_edgar.HEADERS, timeout=12)
    r.raise_for_status()
    rec = (r.json().get("filings") or {}).get("recent") or {}
    forms = rec.get("form") or []
    for i in range(min(len(forms), 25)):
        col = lambda k: (rec.get(k) or [None] * (i + 1))[i]
        form, accn = forms[i], col("accessionNumber")
        # Labelled Z, but it is the SEC's own clock -- Eastern. Checked
        # against the live feed's offset-stamped time for the same filing.
        accepted = col("acceptanceDateTime")
        published = None
        if accepted:
            try:
                published = datetime.strptime(accepted[:19], "%Y-%m-%dT%H:%M:%S") \
                    .replace(tzinfo=ET).timestamp()
            except ValueError:
                pass
        items = sec_edgar._items(col("items") or "") if form.startswith("8-K") else []
        top = items[0] if items else None
        what = (top["means"] if top else
                sec_edgar.FORM_MEANING.get(form) or col("primaryDocDescription") or "Filing")
        doc, plain = col("primaryDocument"), (accn or "").replace("-", "")
        url = (f"https://www.sec.gov/Archives/edgar/data/{int(desk.cik)}/{plain}/{doc}"
               if doc and plain else None)
        desk.add("filing", "SEC EDGAR", f"{form}: {what}", url, published, fresh=not first,
                 summary="; ".join(x["means"] for x in items[1:3] if x["weight"]),
                 extra={"form": form,
                        "important": bool(top and top["weight"] >= 2) or form.startswith("SC 13D")})
    desk.set_status("SEC filings", True, "every 15 s")


_WIRE_CACHE: Dict[str, Any] = {"at": 0.0, "items": []}
_WIRE_LOCK = threading.Lock()


def _wire_items() -> List[Dict[str, Any]]:
    """Both wires, shared by every desk and fetched at most every 20 s."""
    with _WIRE_LOCK:
        if time.time() - _WIRE_CACHE["at"] < EVERY["wires"] - 2:
            return _WIRE_CACHE["items"]
        items: List[Dict[str, Any]] = []
        errors = []
        for source, url in WIRES:
            try:
                r = requests.get(url, headers=BROWSER, timeout=10)
                r.raise_for_status()
                for e in feedparser.parse(r.content).entries:
                    when = e.get("published_parsed") or e.get("updated_parsed")
                    items.append({
                        "source": source, "title": news_rss._strip_html(e.get("title", "")),
                        "summary": news_rss._strip_html(e.get("summary", ""))[:600],
                        "url": e.get("link"),
                        "published": calendar.timegm(when) if when else None,
                    })
            except Exception as exc:                        # noqa: BLE001
                errors.append(f"{source}: {type(exc).__name__}")
        _WIRE_CACHE.update(at=time.time(), items=items, errors=errors)
        return items


def _job_wires(desk: Desk, first: bool) -> None:
    for it in _wire_items():
        if desk.pattern.search(f"{it['title']} {it['summary']}"):
            desk.add("release", it["source"], it["title"], it["url"], it["published"],
                     fresh=not first, summary=it["summary"])
    errs = _WIRE_CACHE.get("errors") or []
    desk.set_status("Press wires", len(errs) < len(WIRES), "; ".join(errs) or "every 20 s")


def _job_google(desk: Desk, first: bool) -> None:
    term = f'"{desk.name}"' if desk.name else f'"{desk.symbol}" stock'
    window = "1d" if first else "1h"
    url = ("https://news.google.com/rss/search?q=" + quote(f"{term} when:{window}")
           + "&hl=en-US&gl=US&ceid=US:en")
    for a in news_rss._from_feed(url, "google_news", 30):
        pub = _epoch_iso(a.get("published"))
        desk.add("web", a.get("publisher") or "Google News", a["title"], a["url"], pub,
                 fresh=not first, extra={"via": "Google News"})
    desk.set_status("Google News", True, "last hour, every 45 s")


def _job_finnhub(desk: Desk, first: bool) -> None:
    if not os.getenv("FINNHUB_API_KEY"):
        desk.set_status("Finnhub", False, "no key (FINNHUB_API_KEY)")
        desk.due["finnhub"] = time.time() + 3600
        return
    for a in news_rss.finnhub_news(desk.symbol, 25):
        desk.add("news", f"{a.get('publisher') or 'Finnhub'} via Finnhub", a["title"], a["url"],
                 _epoch_iso(a.get("published")), fresh=not first, summary=a.get("summary") or "")
    desk.set_status("Finnhub", True, "every 30 s")


def _story(desk: Desk, n: Dict[str, Any], fresh: bool) -> None:
    desk.add("news", f"{(n.get('source') or 'Alpaca').title()} via Alpaca", n.get("headline") or "",
             n.get("url") or None, _epoch_iso(n.get("created_at")), fresh=fresh,
             summary=news_rss._strip_html(n.get("summary") or ""))


def _job_alpaca(desk: Desk, first: bool) -> None:
    """The last few days on opening, and a poll only while the stream is
    down -- with the stream up, this would be asking for what it pushes."""
    if not alpaca.enabled():
        desk.set_status("Alpaca news", False, alpaca.status()["why"] or "off")
        desk.due["alpaca"] = time.time() + 300
        return
    if not first and _STREAM["state"] == "live":
        return
    r = requests.get(f"{alpaca.DATA}/v1beta1/news", headers=alpaca._credentials(),
                     params={"symbols": desk.symbol, "limit": 25 if first else 10}, timeout=12)
    r.raise_for_status()
    for n in r.json().get("news") or []:
        _story(desk, n, fresh=not first)
    if _STREAM["state"] != "live":
        desk.set_status("Alpaca news", True, "polling every 15 s (stream down)")


JOBS: Dict[str, Callable[[Desk, bool], None]] = {
    "edgar": _job_edgar, "wires": _job_wires, "google": _job_google,
    "finnhub": _job_finnhub, "alpaca": _job_alpaca,
}
FEED_OF = {"edgar": "SEC filings", "wires": "Press wires", "google": "Google News",
           "finnhub": "Finnhub", "alpaca": "Alpaca news"}


def _run(desk: Desk, job: str) -> None:
    first = job not in desk.ran
    try:
        JOBS[job](desk, first)
    except Exception as exc:                                # noqa: BLE001
        desk.set_status(FEED_OF[job], False, f"{type(exc).__name__}: {exc}"[:140])
    finally:
        desk.ran.add(job)
        desk.running.discard(job)


def _active() -> List[Desk]:
    now = time.time()
    with _LOCK:
        for sym in [s for s, d in _DESKS.items() if now - d.seen > IDLE_S]:
            del _DESKS[sym]
        return list(_DESKS.values())


def _poll_loop() -> None:
    while True:
        now = time.time()
        for desk in _active():
            for job, every in EVERY.items():
                if job in desk.running or now < desk.due[job]:
                    continue
                desk.due[job] = now + every
                desk.running.add(job)
                _POOL.submit(_run, desk, job)
        time.sleep(1.0)


# ---- the stream -------------------------------------------------------------

_STREAM: Dict[str, Any] = {"state": "idle", "note": "no search open", "since": 0.0}


def _stream_loop() -> None:
    """One socket, subscribed to every story, routed to whichever desks
    the story names. Closed when nobody is looking."""
    from websockets.sync.client import connect

    backoff = 2.0
    while True:
        if not alpaca.enabled():
            _STREAM.update(state="off", note=alpaca.status()["why"] or "off")
            time.sleep(30)
            continue
        if not _active():
            _STREAM.update(state="idle", note="no search open")
            time.sleep(3)
            continue
        try:
            head = alpaca._credentials() or {}
            with connect(STREAM_URL, open_timeout=10, close_timeout=2) as ws:
                ws.recv(timeout=10)
                ws.send(json.dumps({"action": "auth", "key": head.get("APCA-API-KEY-ID"),
                                    "secret": head.get("APCA-API-SECRET-KEY")}))
                reply = json.loads(ws.recv(timeout=10))
                if not any(m.get("msg") == "authenticated" for m in reply):
                    raise RuntimeError(str(reply)[:120])
                ws.send(json.dumps({"action": "subscribe", "news": ["*"]}))
                ws.recv(timeout=10)
                _STREAM.update(state="live", note="", since=time.time())
                wire.mark("alpaca", True, code=101)
                backoff = 2.0
                while _active():
                    try:
                        raw = ws.recv(timeout=5)
                    except TimeoutError:
                        continue
                    for m in json.loads(raw):
                        if m.get("T") == "error":
                            raise RuntimeError(m.get("msg") or "stream error")
                        if m.get("T") != "n":
                            continue
                        named = set(m.get("symbols") or [])
                        for desk in _active():
                            if desk.symbol in named:
                                _story(desk, m, fresh=True)
        except Exception as exc:                            # noqa: BLE001
            # Alpaca's free plan allows one news socket per account; if
            # another program holds it, the REST poll carries on instead.
            _STREAM.update(state="down", note=f"{type(exc).__name__}: {exc}"[:140])
            time.sleep(backoff)
            backoff = min(backoff * 2, 60.0)


def _start() -> None:
    with _LOCK:
        if _STARTED[0]:
            return
        _STARTED[0] = True
    threading.Thread(target=_poll_loop, name="instant-poll", daemon=True).start()
    threading.Thread(target=_stream_loop, name="instant-stream", daemon=True).start()


# ---- what the page reads ---------------------------------------------------

def read(symbol: str, company: str, after: int) -> Dict[str, Any]:
    _start()
    company = (company or "")[:120]
    with _LOCK:
        desk = _DESKS.get(symbol)
        if desk is None:
            if len(_DESKS) >= MAX_DESKS:
                oldest = min(_DESKS.values(), key=lambda d: d.seen)
                del _DESKS[oldest.symbol]
            desk = _DESKS[symbol] = Desk(symbol, company)
        elif company and not desk.name:
            fresh = Desk(symbol, company)
            desk.name, desk.pattern = fresh.name, fresh.pattern
        desk.seen = time.time()
        seq = _SEQ[0]

    with desk.lock:
        events = sorted((dict(e, also=list(e["also"])) for e in desk.events if e["seq"] > after),
                        key=lambda e: e["seq"])

    stream = dict(_STREAM)
    if stream["state"] == "live":
        desk.set_status("Alpaca news", True, "live stream")
    elif stream["state"] in ("down", "off") and "Alpaca news" not in desk.status:
        desk.set_status("Alpaca news", False, stream["note"])
    feeds = [{"name": name, **desk.status[name]}
             for name in ("Alpaca news", "SEC filings", "Press wires", "Google News", "Finnhub")
             if name in desk.status]
    return {
        "symbol": symbol,
        "seq": max([seq] + [e["seq"] for e in events]),
        "events": events,
        "feeds": feeds,
        "stream": stream,
        "ready": sorted(desk.ran),
        "watching_since": desk.opened,
        "name": desk.name,
    }
