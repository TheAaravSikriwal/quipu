"""What is already on the calendar between now and expiry.

The question this answers is narrow and practical: *is something known
coming before my option expires?* An earnings report two days before
expiry is the difference between a trade and a coin toss, and it is
knowable in advance, so there is no excuse for being surprised by it.

WHERE THE DATES COME FROM, AND HOW FAR EACH ONE REACHES

  Federal Reserve   federalreserve.gov, parsed from the FOMC calendar the
                    Board publishes itself. Authoritative, and it runs
                    more than a year ahead.
  BEA               bea.gov release schedule -- GDP, personal income and
                    outlays (which carries the PCE inflation figure the
                    Fed actually targets), trade. Roughly a quarter ahead.
  The week ahead    a free aggregator of the week's scheduled releases,
                    which is the only reachable source that carries the
                    BLS numbers with a forecast next to them.
  The company       earnings date and dividend dates, from Yahoo.

WHAT IS *NOT* CONFIRMED, AND WHY IT IS STILL HERE

The two biggest scheduled movers after the Fed -- the inflation report
and the jobs report -- come from the BLS, and bls.gov refuses automated
requests outright (403, any user agent). Rather than silently leave a
hole where the two most-watched releases of the month should be, they are
emitted from their usual timing and marked `confirmed: False`. The app
draws those differently and says so in words. An estimate you can see is
an estimate is useful; one you cannot is a lie.

Whenever the week-ahead feed carries the real date, it replaces the
estimate.
"""

from __future__ import annotations

import calendar as _cal
import json
import os
import re
import time
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

import requests

UA = {"User-Agent": "quipu/0.1 (personal research tool)"}
TIMEOUT = 20

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")
CACHE = os.path.join(CACHE_DIR, "events.json")

#: Calendars are published documents that change a few times a year; the
#: week-ahead feed moves daily. No point hammering either.
TTL = {"fomc": 86400 * 3, "bea": 86400, "week": 3600 * 3}

#: Full names and abbreviations both. A meeting that straddles a month
#: boundary is labelled "Jan/Feb" rather than "January/February", so a
#: table of full names alone silently loses one meeting a year in the
#: years that have one -- and it is always a January or an October
#: meeting, never a quiet one.
MONTHS = {m.lower(): i for i, m in enumerate(_cal.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(_cal.month_abbr) if m})
MONTHS["sept"] = 9


def _holidays(year: int) -> set:
    """The market holiday calendar, already built for pricing."""
    try:
        from .options import market_holidays
        return set(market_holidays(year))
    except Exception:
        return set()


# --------------------------------------------------------------------------
# a cache that survives a restart, because none of this changes by the minute
# --------------------------------------------------------------------------

def _cache_read() -> Dict[str, Any]:
    try:
        with open(CACHE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def _cache_write(store: Dict[str, Any]) -> None:
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE, "w", encoding="utf-8") as fh:
            json.dump(store, fh)
    except Exception:
        pass


def _cached(key: str, build) -> List[Dict[str, Any]]:
    """Fetch through the cache, and keep stale data if the fetch fails.

    A calendar that is three days old beats an empty panel: the dates in
    it were not going to move anyway, and the alternative is telling
    someone there is nothing coming when there is.
    """
    store = _cache_read()
    hit = store.get(key)
    if hit and (time.time() - hit.get("at", 0)) < TTL.get(key, 3600):
        return hit.get("rows", [])
    try:
        rows = build()
        if rows:
            store[key] = {"at": time.time(), "rows": rows}
            _cache_write(store)
            return rows
    except Exception:
        pass
    return (hit or {}).get("rows", [])


def _ev(day: str, title: str, kind: str, why: str, source: str,
        scope: str = "market", weight: int = 2, confirmed: bool = True,
        time_et: Optional[str] = None, url: Optional[str] = None,
        approx: bool = False, extra: Optional[Dict] = None) -> Dict[str, Any]:
    row = {"date": day, "title": title, "kind": kind, "why": why,
           "source": source, "scope": scope, "weight": weight,
           "confirmed": confirmed, "time": time_et, "url": url,
           "approx": approx}
    if extra:
        row.update(extra)
    return row


# --------------------------------------------------------------------------
# the Fed
# --------------------------------------------------------------------------

FOMC_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"

_WHY_FOMC = (
    "The Fed decides where interest rates go. It is the one date that moves "
    "every stock at once, and the surprise is usually in the wording rather "
    "than the number — the market has normally guessed the number."
)


def _fomc() -> List[Dict[str, Any]]:
    """Meeting dates, straight off the Board's own calendar page."""
    html = requests.get(FOMC_URL, headers=UA, timeout=TIMEOUT).text
    rows: List[Dict[str, Any]] = []

    # The page is one panel per year; the year only appears in the heading,
    # so the rows have to be read inside their panel to be dated at all.
    parts = re.split(r'<a id="\d+">(\d{4})\s+FOMC Meetings</a>', html)
    for i in range(1, len(parts) - 1, 2):
        year = int(parts[i])
        block = parts[i + 1]
        pairs = re.findall(
            r'fomc-meeting__month[^>]*>(.*?)</div>.*?fomc-meeting__date[^>]*>(.*?)</div>',
            block, re.S)
        for month_raw, day_raw in pairs:
            month_txt = re.sub(r"<[^>]+>", "", month_raw).strip()
            day_txt = re.sub(r"<[^>]+>", "", day_raw).strip()

            # A notation vote is a poll conducted by circulating a document,
            # not a meeting with a rate decision at the end of it. Counting
            # one gives a year nine meetings and puts a decision date in the
            # calendar that never carried a decision.
            if "notation" in day_txt.lower():
                continue

            months = [m.strip().lower() for m in month_txt.split("/") if m.strip()]
            days = [int(d) for d in re.findall(r"\d+", day_txt)]
            if not months or not days:
                continue
            # A two-day meeting decides on the second day, and when it
            # straddles a month boundary that second day is in the second
            # month -- January 27-28 versus January/February 31-1.
            month = MONTHS.get(months[-1] if len(months) > 1 else months[0])
            if not month:
                continue
            try:
                when = date(year, month, days[-1])
            except ValueError:
                continue
            # A starred meeting comes with the quarterly projections and a
            # press conference, which is materially more to react to than
            # the statement on its own.
            projections = "*" in day_txt
            rows.append(_ev(
                when.isoformat(), "Fed interest rate decision", "rate",
                _WHY_FOMC + (" This one also brings the quarterly forecasts and "
                             "a press conference, so there is more to react to "
                             "than usual." if projections else ""),
                "Federal Reserve", weight=3, time_et="2:00pm ET",
                url=FOMC_URL, extra={"projections": projections}))
    return rows


# --------------------------------------------------------------------------
# the Bureau of Economic Analysis
# --------------------------------------------------------------------------

BEA_URL = "https://www.bea.gov/news/schedule"

#: BEA titles their releases for economists. These are the same things in
#: the words people actually use, with what they do to a share price.
_BEA_MAP = [
    (r"personal income and outlays", "Inflation reading (PCE)", "inflation", 3,
     "The inflation measure the Fed actually targets. Hotter than expected "
     "usually means rate cuts get pushed back, and shares fall."),
    (r"international trade in goods", "Trade figures", "growth", 1,
     "Imports against exports. A slow mover unless tariffs are the story."),
]

#: Each quarter's GDP is published three times, and only the first one
#: moves anything -- by the second pass the market has had the number for
#: a month. Naming them all "GDP" put three identical-looking rows in the
#: calendar for what is really one event and two footnotes.
_GDP_ROUNDS = [
    (r"advance estimate", "Economic growth (GDP, first estimate)", 2,
     "The first read on how fast the economy grew last quarter. This is "
     "the one that moves markets — the later revisions of the same "
     "quarter almost never do."),
    (r"second estimate", "Economic growth (GDP, second estimate)", 1,
     "A revision to a number the market already has. Rarely moves much."),
    (r"third estimate", "Economic growth (GDP, final estimate)", 1,
     "The final revision to a quarter that ended months ago. Historical "
     "interest mostly."),
]


def _bea_row(title: str):
    """What a BEA release is called in plain words, or None to skip it.

    BEA publishes a great deal that is not a market event -- GDP broken
    down by county, state personal income for the year before last. Those
    carry "GDP" in the title and nothing else, and matching on the word
    alone put "there is a GDP release before your expiry" in front of the
    reader when there was not one that mattered.
    """
    low = title.lower()
    for pat, nice, kind, weight, why in _BEA_MAP:
        if re.search(pat, low):
            return nice, kind, weight, why
    # Plain substring tests rather than a regex: an earlier version of
    # this line carried word-boundary escapes that did not survive being
    # written to disk, and silently matched nothing at all.
    if "gdp" in low or "gross domestic product" in low:
        for pat, nice, weight, why in _GDP_ROUNDS:
            if re.search(pat, low):
                return nice, "growth", weight, why
        return None                  # regional or annual detail, not an event
    return None


def _bea() -> List[Dict[str, Any]]:
    """GDP and the PCE inflation print, from the BEA's own schedule."""
    html = requests.get(BEA_URL, headers=UA, timeout=TIMEOUT).text
    body = re.search(r"<tbody.*?</tbody>", html, re.S)
    if not body:
        return []

    today = date.today()
    rows: List[Dict[str, Any]] = []
    for tr in re.findall(r"<tr.*?</tr>", body.group(0), re.S):
        cells = [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh].*?</t[dh]>", tr, re.S)]
        if len(cells) < 3:
            continue
        when_txt, sort, title = cells[0], cells[1], cells[2]
        if sort.lower() != "news":
            continue                                  # data drops, not news
        m = re.match(r"([A-Za-z]+)\s+(\d{1,2})\s*(.*)", when_txt)
        if not m:
            continue
        month = MONTHS.get(m.group(1).lower())
        if not month:
            continue
        # The page carries no year. It is forward-looking, so the year is
        # whichever one puts the date ahead of today rather than behind it.
        year = today.year
        try:
            when = date(year, month, int(m.group(2)))
        except ValueError:
            continue
        if (when - today).days < -14:
            when = when.replace(year=year + 1)

        hit = _bea_row(title)
        if not hit:
            continue
        nice, kind, weight, why = hit
        rows.append(_ev(when.isoformat(), nice, kind, why,
                        "Bureau of Economic Analysis", weight=weight,
                        time_et=(m.group(3) or "8:30am ET").lower()
                                .replace(" am", "am").replace(" pm", "pm"),
                        url=BEA_URL, extra={"detail": title}))
    return rows


# --------------------------------------------------------------------------
# the week ahead -- the only reachable source carrying the BLS numbers
# --------------------------------------------------------------------------

WEEK_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

#: Not fetchable -- it 403s any automated request -- but it is the page
#: that settles the question, so a reader who wants the confirmed date
#: should be given the door even though the app cannot walk through it.
BLS_URL = "https://www.bls.gov/schedule/news_release/"

_WEEK_MAP = [
    (r"\bcpi\b", "Inflation report (CPI)", "inflation", 3,
     "The headline inflation number. Higher than forecast and rate cuts "
     "look further away, which usually knocks shares down."),
    (r"non-farm|nonfarm|employment change", "Jobs report", "jobs", 3,
     "How many jobs the economy added last month. Strong hiring is good for "
     "the economy but points to rates staying high for longer."),
    (r"unemployment rate", "Unemployment rate", "jobs", 2,
     "Out the same moment as the jobs report, and read together with it."),
    (r"\bppi\b", "Wholesale prices (PPI)", "inflation", 2,
     "Inflation one step back in the chain, before it reaches shop shelves."),
    (r"federal funds rate|fomc statement", "Fed interest rate decision", "rate", 3,
     _WHY_FOMC),
    (r"retail sales", "Retail sales", "growth", 2,
     "What people actually spent. The cleanest read on whether the consumer "
     "is still holding up."),
    (r"\bgdp\b", "Economic growth (GDP)", "growth", 2,
     "How fast the economy grew last quarter."),
    # Deliberately last, so a real release on the same day wins the pattern
    # match. Several officials usually speak on one day and the merge
    # collapses them into a single line, which is the right amount of
    # attention: a speech moves things occasionally, a scheduled number
    # always can.
    (r"fomc member|fed chair|powell speaks", "Fed officials speaking", "fedspeak", 1,
     "Unscripted remarks from the people who set rates. Usually nothing, "
     "occasionally a hint about the next decision that moves the market."),
]


def _week() -> List[Dict[str, Any]]:
    """This week's scheduled US releases, with the forecast attached."""
    data = requests.get(WEEK_URL, headers=UA, timeout=TIMEOUT).json()
    rows: List[Dict[str, Any]] = []
    for e in data:
        if e.get("country") != "USD" or e.get("impact") not in ("High", "Medium"):
            continue
        raw = (e.get("date") or "")[:19]
        try:
            when = datetime.fromisoformat(raw)
        except Exception:
            continue
        low = (e.get("title") or "").lower()
        for pat, nice, kind, weight, why in _WEEK_MAP:
            if re.search(pat, low):
                rows.append(_ev(
                    when.date().isoformat(), nice, kind, why,
                    "Scheduled release", weight=weight,
                    time_et=when.strftime("%-I:%M%p ET").lower()
                            if os.name != "nt" else
                            when.strftime("%I:%M%p ET").lstrip("0").lower(),
                    extra={"forecast": e.get("forecast") or None,
                           "previous": e.get("previous") or None}))
                break
    return rows


# --------------------------------------------------------------------------
# the two the BLS will not let us read
# --------------------------------------------------------------------------

def _expected_bls(horizon: int) -> List[Dict[str, Any]]:
    """The inflation and jobs reports, from their usual timing.

    Marked unconfirmed everywhere they surface. The jobs report is nearly
    always the first Friday; CPI lands mid-month and wanders by a couple
    of days, so it is shown as "around" a date rather than on one.
    """
    today = date.today()
    out: List[Dict[str, Any]] = []
    for step in range(0, horizon // 28 + 2):
        y, m = divmod((today.month - 1) + step, 12)
        y, m = today.year + y, m + 1

        first = date(y, m, 1)
        jobs = first + timedelta(days=(4 - first.weekday()) % 7)   # first Friday
        # 1 January 2027 is a first Friday. Nobody publishes payrolls on a
        # federal holiday, so it goes to the Friday after.
        if jobs in _holidays(y):
            jobs += timedelta(days=7)
        if 0 <= (jobs - today).days <= horizon:
            out.append(_ev(
                jobs.isoformat(), "Jobs report", "jobs",
                "How many jobs the economy added last month. Strong hiring is "
                "good for the economy but points to rates staying high for "
                "longer. Usually the first Friday of the month — this date "
                "is the usual timing, not a confirmed one.",
                "Bureau of Labor Statistics", weight=3, confirmed=False,
                time_et="8:30am ET", url=BLS_URL))

        cpi = date(y, m, 12)
        # The 12th is the middle of the window, not a rule, and it lands on
        # a weekend four months in ten. Nudge to the nearest weekday, which
        # stays inside the 10th-to-15th window either way.
        if cpi.weekday() == 5:
            cpi -= timedelta(days=1)
        elif cpi.weekday() == 6:
            cpi += timedelta(days=1)
        while cpi in _holidays(y):
            cpi += timedelta(days=1)
        if 0 <= (cpi - today).days <= horizon:
            out.append(_ev(
                cpi.isoformat(), "Inflation report (CPI)", "inflation",
                "The headline inflation number. Higher than forecast and rate "
                "cuts look further away, which usually knocks shares down. "
                "Lands mid-month, normally between the 10th and the 15th — "
                "the exact day is not confirmed here.",
                "Bureau of Labor Statistics", weight=3, confirmed=False,
                approx=True, time_et="8:30am ET", url=BLS_URL))
    return out


# --------------------------------------------------------------------------
# the company itself
# --------------------------------------------------------------------------

def company(symbol: str, earnings: Optional[Dict] = None,
            fundamentals: Optional[Dict] = None,
            dividends: Optional[Dict] = None) -> List[Dict[str, Any]]:
    """Earnings and dividend dates for one ticker.

    Takes what the ticker page already fetched rather than going back out
    for it: going back to Yahoo for one panel would double the traffic
    for data that is already in hand.
    """
    out: List[Dict[str, Any]] = []
    today = date.today()
    yahoo = f"https://finance.yahoo.com/quote/{symbol}"

    nxt = (earnings or {}).get("next_date")
    if nxt:
        rate = (earnings or {}).get("beat_rate")
        out.append(_ev(
            str(nxt)[:10], "Earnings", "earnings",
            "The company reports its results. For one stock this is the "
            "biggest scheduled move there is: options get more expensive "
            "going into it, and lose that extra value the moment it passes, "
            "whichever way the shares go."
            + (f" It has beaten expectations {rate}% of the time recently."
               if rate is not None else "")
            + " Companies sometimes move the date; it is worth checking "
              "against the investor relations page before trading around it.",
            "Yahoo Finance", scope="company", weight=3,
            url=f"{yahoo}/analysis"))

    div = dividends or {}
    amount = div.get("amount")
    cadence = div.get("cadence")
    ex = div.get("next_ex")

    if ex and ex >= today.isoformat():
        estimated = bool(div.get("next_ex_estimated"))
        out.append(_ev(
            ex,
            "Goes ex-dividend" + (f" ({amount:,.2f} a share)" if amount else ""),
            "dividend",
            "To receive this payment you have to own the shares before this "
            "morning. On the day the shares open lower by roughly the "
            "dividend, because a new buyer no longer gets it \u2014 that is not a "
            "fall to trade, and it is already inside the option prices. "
            "Where it does matter: if you are short a call that is in the "
            "money, the other side can exercise early to collect the "
            "dividend and leave you short the stock."
            + (f" Paid {cadence}; the last four went out about "
               f"{div.get('gap_days')} days apart."
               if estimated and cadence else "")
            + (" The company has not announced this one \u2014 the date is "
               "projected from that pattern."
               if estimated else " This date is announced."),
            "Projected from payment history" if estimated else "Yahoo Finance",
            scope="company", weight=1, confirmed=not estimated,
            approx=estimated, url=f"{yahoo}/history/?filter=div"))

    pay = div.get("pay_date")
    if pay and pay >= today.isoformat():
        out.append(_ev(
            pay, "Dividend paid" + (f" ({amount:,.2f} a share)" if amount else ""),
            "dividend_pay",
            "The cash actually lands, for anyone who held the shares before "
            "the ex-dividend date. Nothing happens to the share price here "
            "\u2014 that already happened when it went ex.",
            "Yahoo Finance", scope="company", weight=1,
            url=f"{yahoo}/history/?filter=div"))

    return out


# --------------------------------------------------------------------------
# everything, merged
# --------------------------------------------------------------------------

def _key(row: Dict) -> tuple:
    """Identity of a release, which is its name and not its subject.

    Keying on the subject collapsed CPI into PCE -- two different numbers
    out on different days that happen to both be inflation -- and left a
    month looking emptier than it was.
    """
    return (row["date"], row["title"])


def upcoming(symbol: Optional[str] = None, horizon: int = 120,
             earnings: Optional[Dict] = None,
             fundamentals: Optional[Dict] = None,
             dividends: Optional[Dict] = None) -> Dict[str, Any]:
    """Every known date between today and `horizon` days out."""
    today = date.today()
    limit = today + timedelta(days=horizon)

    rows: List[Dict[str, Any]] = []
    rows += _cached("fomc", _fomc)
    rows += _cached("bea", _bea)
    week = _cached("week", _week)
    rows += week
    rows += _expected_bls(horizon)
    if symbol:
        rows += company(symbol, earnings, fundamentals, dividends)

    # A confirmed date always beats an estimate of the same thing, and the
    # week-ahead feed confirms exactly the two the BLS will not serve.
    best: Dict[tuple, Dict] = {}
    for r in rows:
        try:
            when = date.fromisoformat(r["date"])
        except Exception:
            continue
        if not (today <= when <= limit):
            continue
        k = _key(r)
        cur = best.get(k)
        if cur is None or (r["confirmed"] and not cur["confirmed"]):
            best[k] = r

    # The estimate and the confirmed print are the same release a day or two
    # apart, so they do not collide on date alone.
    confirmed = {(r["title"], r["date"][:7]) for r in best.values() if r["confirmed"]}
    merged = [r for r in best.values()
              if r["confirmed"] or (r["title"], r["date"][:7]) not in confirmed]

    for r in merged:
        r["days"] = (date.fromisoformat(r["date"]) - today).days

    merged.sort(key=lambda r: (r["date"], -r["weight"]))
    return {
        "as_of": today.isoformat(),
        "horizon": horizon,
        "events": merged,
        "sources": [
            {"name": "Federal Reserve", "what": "FOMC meeting dates", "url": FOMC_URL},
            {"name": "Bureau of Economic Analysis", "what": "GDP and PCE inflation",
             "url": BEA_URL},
            {"name": "Bureau of Labor Statistics",
             "what": "inflation and jobs \u2014 dates projected, see below", "url": BLS_URL},
            {"name": "Yahoo Finance", "what": "earnings and dividend dates",
             "url": "https://finance.yahoo.com"},
        ],
        "bls_note": ("The inflation and jobs reports come from the BLS, which "
                     "blocks automated requests. Those two are shown at their "
                     "usual timing and marked unconfirmed until the week-ahead "
                     "feed carries the real date."),
    }
