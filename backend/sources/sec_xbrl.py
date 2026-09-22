"""Financial statements as the company filed them, not as a vendor retyped them.

Everything else on the Business panels comes from Yahoo, which is a
convenience layer over this. Convenience layers normalise, and
normalising is where numbers quietly change: a vendor decides what counts
as revenue for a company that reports three kinds, picks one, and gives
you a figure with no way to ask which.

The SEC publishes the source. Every number in every XBRL-tagged filing
since roughly 2009 is available at data.sec.gov, free, no key, and each
one carries the form it came from, the date it was filed and the
accession number of the filing. That is what makes this the only data in
the app that can honestly wear the FILED label -- not because it is more
accurate, but because it is attributable. Click the number, read the
10-K it is on.

TWO THINGS THAT MAKE THIS HARDER THAN IT LOOKS

Restatements. The same fiscal period appears in several filings, and the
figures differ, because a later filing revised them. Apple's FY2023 net
income appears in the FY2023, FY2024 and FY2025 10-Ks. The most recently
filed version is the one that stands, so periods are collapsed on their
END DATE and the newest filing of each wins.

Tag choice. US GAAP has many ways to say revenue and companies pick
different ones -- `Revenues` for some, the 80-character
`RevenueFromContractWithCustomerExcludingAssessedTax` for others. Each
metric is therefore a list of candidate tags in preference order, and
the tag actually used is reported alongside the number so a figure that
looks odd can be traced to the concept it came from.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple

import requests

# The SEC throttles to 10 requests a second. One company's facts is a
# single request, cached for a day, so this is never close to it.
#
# It also asks for a contactable user agent, and rejects some perfectly
# ordinary ones: a string with parentheses in it comes back 403 from an
# edge rule, silently, as an HTML error page. Kept plain for that reason.
#
# Their fair-access notice asks for an email. Rather than put the user's
# address in a header to a third party without being asked, it is opt-in
# through the environment; requests work either way.
_CONTACT = os.environ.get("QUIPU_SEC_CONTACT", "").strip()
UA = {"User-Agent": f"quipu-research/0.1 {_CONTACT}".strip()}
TIMEOUT = 40
FACTS = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
FILING = "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}"

CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache", "xbrl")
TTL = 86400          # filings arrive quarterly; a day is generous

#: Friendly name -> the us-gaap tags that might carry it, best first.
CONCEPTS: Dict[str, List[str]] = {
    "revenue": [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "Revenues",
        "RevenuesNetOfInterestExpense",          # banks
        "OperatingLeaseLeaseIncome",             # REITs, post-ASC-842
        "RegulatedAndUnregulatedOperatingRevenue",   # utilities
        "SalesRevenueNet",
        "SalesRevenueGoodsNet",
    ],
    "cost_of_revenue": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfServices"],
    "gross_profit": ["GrossProfit"],
    "research": ["ResearchAndDevelopmentExpense"],
    "sga": [
        "SellingGeneralAndAdministrativeExpense",
        "GeneralAndAdministrativeExpense",
    ],
    "operating_income": ["OperatingIncomeLoss"],
    "pretax_income": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                      "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "tax": ["IncomeTaxExpenseBenefit"],
    "net_income": ["NetIncomeLoss", "ProfitLoss"],
    "eps_diluted": ["EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted"],
    "eps_basic": ["EarningsPerShareBasic"],
    "shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],

    "assets": ["Assets"],
    "assets_current": ["AssetsCurrent"],
    "liabilities": ["Liabilities"],
    "liabilities_current": ["LiabilitiesCurrent"],
    "equity": ["StockholdersEquity",
               "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue",
             "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "inventory": ["InventoryNet"],
    "long_term_debt": ["LongTermDebtNoncurrent", "LongTermDebt"],

    "operating_cash_flow": [
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
    ],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment",
              "PaymentsToAcquireProductiveAssets"],
    "buybacks": ["PaymentsForRepurchaseOfCommonStock"],
    "dividends_paid": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"],
}

#: Which of those are point-in-time rather than over-a-period. A balance
#: sheet is a photograph; an income statement is a film.
INSTANT = {"assets", "assets_current", "liabilities", "liabilities_current",
           "equity", "cash", "inventory", "long_term_debt"}


# --------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------

def _cache_path(cik: int) -> str:
    return os.path.join(CACHE_DIR, f"{cik:010d}.json")


def company_facts(cik: int) -> Dict[str, Any]:
    """Every tagged number the company has filed, cached on disk.

    These files run to several megabytes, and the contents only change
    when a filing lands. Re-fetching one per page load would be rude to
    a free public service and slow for no reason.
    """
    path = _cache_path(cik)
    try:
        if os.path.exists(path) and (time.time() - os.path.getmtime(path)) < TTL:
            with open(path, encoding="utf-8") as fh:
                return json.load(fh)
    except Exception:
        pass

    res = requests.get(FACTS.format(cik=cik), headers=UA, timeout=TIMEOUT)
    res.raise_for_status()
    data = res.json()
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    except Exception:
        pass
    return data


# --------------------------------------------------------------------------
# reading a concept out
# --------------------------------------------------------------------------

def _days(row: Dict) -> Optional[int]:
    if not row.get("start"):
        return None
    try:
        return (date.fromisoformat(row["end"]) - date.fromisoformat(row["start"])).days
    except Exception:
        return None


def _series(gaap: Dict, metric: str, period: str) -> Tuple[Optional[str], List[Dict]]:
    """One metric as a clean time series, newest filing of each period.

    `period` is "annual" or "quarter". Duration concepts are filtered on
    how long the period actually ran rather than on the form type,
    because a 10-K carries quarterly figures too and an annual number
    tagged in a 10-Q is not unheard of.
    """
    best: Optional[Tuple] = None

    for rank, tag in enumerate(CONCEPTS.get(metric, [])):
        node = gaap.get(tag)
        if not node:
            continue
        for unit, rows in node.get("units", {}).items():
            if unit not in ("USD", "USD/shares", "shares"):
                continue

            keep: Dict[str, Dict] = {}
            for r in rows:
                if r.get("val") is None:
                    continue
                length = _days(r)
                if metric in INSTANT:
                    if length is not None:
                        continue                      # not a balance figure
                elif period == "annual":
                    if length is None or not 330 <= length <= 400:
                        continue
                else:
                    if length is None or not 60 <= length <= 120:
                        continue

                # Collapse restatements: the same period end, filed more
                # than once, keeps whichever filing came last.
                prev = keep.get(r["end"])
                if prev is None or r.get("filed", "") > prev.get("filed", ""):
                    keep[r["end"]] = r

            if not keep:
                continue
            out = sorted(keep.values(), key=lambda r: r["end"])
            # Preference order alone is not enough. A REIT tags its rent
            # as contract revenue until the lease standard changes, then
            # stops -- so the preferred tag still exists, still has
            # data, and stops in 2018. Realty Income came back with a
            # 2018 income statement and $1.3bn of revenue against an
            # actual $5.5bn. Whichever tag runs closest to the present
            # is the one the company is using now; list order only
            # breaks ties.
            score = (out[-1]["end"], len(out), -rank)
            if best is None or score > best[0]:
                best = (score, tag, unit, out)

    if best is None:
        return None, []
    _, tag, unit, out = best
    return tag, [{
        "end": r["end"],
        "start": r.get("start"),
        "val": r["val"],
        "form": r.get("form"),
        "filed": r.get("filed"),
        "accn": r.get("accn"),
        "fy": r.get("fy"),
        "unit": unit,
    } for r in out]


def _accn_url(cik: int, accn: Optional[str]) -> Optional[str]:
    """A link to the actual filing a number came from."""
    if not accn:
        return None
    plain = accn.replace("-", "")
    return (f"https://www.sec.gov/Archives/edgar/data/{cik}/{plain}/"
            f"{accn}-index.htm")


# --------------------------------------------------------------------------
# the statements
# --------------------------------------------------------------------------

def _div(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or not b:
        return None
    return a / b


def _a_year_before(end: str, by_end: Dict[str, Dict]) -> Optional[Dict]:
    """The row closest to exactly a year before `end`, or nothing.

    Fiscal calendars drift by a few days -- a 52/53-week filer's Q1 can
    land anywhere in a fortnight -- so this looks for the nearest match
    inside a window rather than an exact date, and refuses rather than
    reaching for something six months out.
    """
    try:
        target = date.fromisoformat(end).replace(
            year=date.fromisoformat(end).year - 1)
    except ValueError:                      # 29 February
        target = date.fromisoformat(end) - timedelta(days=365)

    best, gap = None, timedelta(days=46)
    for other, row in by_end.items():
        try:
            diff = abs(date.fromisoformat(other) - target)
        except ValueError:
            continue
        if diff < gap:
            best, gap = row, diff
    return best


def _add_missing_q4(annual: List[Dict], quarters: List[Dict]) -> List[Dict]:
    """The fourth quarter, which no company files.

    A 10-Q covers the first three quarters; the fourth is only ever
    reported inside the annual figure. Left alone the series jumps from
    September to the following April, which reads as a company that
    stopped trading for six months.

    So it is backed out: the year less the three quarters inside it.
    That is arithmetic on filed numbers rather than a filed number, and
    is flagged as such.
    """
    have = {r["end"] for r in quarters}
    made = []

    for yr in annual:
        end = yr.get("end")
        if not end or end in have:
            continue
        try:
            y_end = date.fromisoformat(end)
        except ValueError:
            continue
        y_start = y_end - timedelta(days=360)

        inside = [q for q in quarters
                  if y_start <= date.fromisoformat(q["end"]) < y_end]
        if len(inside) != 3:
            continue                        # cannot subtract what is not there

        row: Dict[str, Any] = {"end": end, "cite": yr.get("cite"),
                               "derived_q4": True}
        for k in ("revenue", "net_income", "operating_income", "gross_profit",
                  "operating_cash_flow", "capex"):
            whole = yr.get(k)
            parts = [q.get(k) for q in inside]
            if whole is None or any(v is None for v in parts):
                continue
            row[k] = whole - sum(parts)
        # Balance-sheet figures at the year end ARE the quarter end, so
        # they carry across untouched rather than being differenced.
        for k in ("assets", "liabilities", "equity", "cash"):
            if yr.get(k) is not None:
                row[k] = yr[k]
        if row.get("revenue") is not None:
            made.append(row)

    return sorted(quarters + made, key=lambda r: r["end"])


def statements(symbol: str, cik: int, years: int = 5,
               quarters: int = 8) -> Dict[str, Any]:
    """Income, balance sheet and cash flow, with a citation on every line."""
    facts = company_facts(cik)
    gaap = facts.get("facts", {}).get("us-gaap", {})
    if not gaap:
        return {"available": False, "reason": "no XBRL facts filed"}

    tags: Dict[str, str] = {}

    def grab(period: str, n: int) -> Dict[str, Dict[str, Dict]]:
        """metric -> {period_end: row}, keyed for lookup.

        Deliberately keeps every period rather than a tail slice. A
        balance sheet is filed at every quarter end as well as every
        year end, so the last nine entries of `Assets` are the last nine
        QUARTERS -- and the year-end dates the income statement is lined
        up against fall off the back of that window. The table came back
        with four empty years of assets and equity under five full years
        of revenue.
        """
        table: Dict[str, Dict[str, Dict]] = {}
        for metric in CONCEPTS:
            tag, rows = _series(gaap, metric, period)
            if not rows:
                continue
            tags.setdefault(metric, tag)
            table[metric] = {r["end"]: r for r in rows}
        return table

    annual = grab("annual", years)
    quarter = grab("quarter", quarters)

    def assemble(table: Dict[str, Dict[str, Dict]], n: int,
                 anchor: str = "revenue") -> List[Dict[str, Any]]:
        """Line the metrics up on the period ends the anchor metric has.

        Balance-sheet items are filed on the same date as the income
        statement they accompany, so the income statement's period ends
        are the spine. A balance figure that does not land on one is
        from an interim date and is not part of this row.
        """
        spine = sorted((table.get(anchor) or table.get("net_income") or {}).keys())[-n:]
        out = []
        for end in spine:
            row: Dict[str, Any] = {"end": end, "cite": None}
            for metric, byend in table.items():
                hit = byend.get(end)
                if hit is None:
                    continue
                row[metric] = hit["val"]
                if row["cite"] is None or metric == anchor:
                    row["cite"] = {
                        "form": hit["form"], "filed": hit["filed"],
                        "accn": hit["accn"], "fy": hit["fy"],
                        "url": _accn_url(cik, hit["accn"]),
                    }
            # Plenty of filers never tag `Liabilities` -- they tag the
            # components and let the total fall out of the balance
            # sheet. Coca-Cola is one, and the row was empty for every
            # year. The identity that defines a balance sheet supplies
            # it, and is marked as arithmetic rather than a filed line.
            if row.get("liabilities") is None:
                a_, e_ = row.get("assets"), row.get("equity")
                if a_ is not None and e_ is not None:
                    row["liabilities"] = a_ - e_
                    row["liabilities_derived"] = True

            # Derived figures, computed here rather than taken on trust.
            rev = row.get("revenue")
            row["gross_margin"] = _div(row.get("gross_profit"), rev)
            row["operating_margin"] = _div(row.get("operating_income"), rev)
            row["net_margin"] = _div(row.get("net_income"), rev)
            row["roe"] = _div(row.get("net_income"), row.get("equity"))
            row["current_ratio"] = _div(row.get("assets_current"),
                                        row.get("liabilities_current"))
            row["debt_to_equity"] = _div(row.get("long_term_debt"), row.get("equity"))
            ocf, capex = row.get("operating_cash_flow"), row.get("capex")
            row["free_cash_flow"] = (ocf - capex) if ocf is not None and capex is not None else None
            out.append(row)
        return out

    rows_a = assemble(annual, years)
    rows_q = assemble(quarter, quarters + 6)
    rows_q = _add_missing_q4(rows_a, rows_q)[-quarters:]

    # Year-on-year growth, matched on the DATE a year earlier rather
    # than on four rows back. Quarterly figures are seasonal so the
    # comparison has to be against the same season -- and counting rows
    # assumes the series has no gaps, which it does: nobody files a
    # fourth-quarter 10-Q, so four rows back was five calendar quarters
    # and every growth figure on the page was against the wrong period.
    for series in (rows_a, rows_q):
        by_end = {r["end"]: r for r in series}
        for row in series:
            prior = _a_year_before(row["end"], by_end)
            for k in ("revenue", "net_income", "operating_income"):
                was = (prior or {}).get(k)
                now = row.get(k)
                row[f"{k}_growth"] = ((now / was - 1) if was and now is not None
                                      and was > 0 else None)
            row["prior_end"] = (prior or {}).get("end")

    # A company that has reorganised files under a NEW CIK, and the new
    # registrant starts with no history: Exxon's ticker resolves to a
    # CIK carrying two quarters and no annual periods at all. That is
    # the filings being right, not the reader being unlucky, so it is
    # said rather than shown as an empty table.
    note = None
    if not rows_a and rows_q:
        note = ("This registrant has not filed an annual report yet, so there "
                "is no yearly history under it. That usually means the company "
                "has reorganised and the earlier years sit under a predecessor "
                "filer at the SEC.")
    elif not rows_a and not rows_q:
        note = "Nothing tagged in XBRL for this filer."

    return {
        "available": bool(rows_a or rows_q),
        "note": note,
        "symbol": symbol,
        "cik": cik,
        "entity": facts.get("entityName"),
        "annual": rows_a,
        "quarterly": rows_q,
        "tags": tags,
        "source": "SEC EDGAR company facts (XBRL)",
        "source_url": f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik:010d}&type=10-K",
    }


def fetch(symbol: str, lookup_cik) -> Dict[str, Any]:
    """Entry point: resolve the ticker to a CIK, then read the filings."""
    try:
        hit = lookup_cik(symbol)
    except Exception:
        hit = None
    if not hit or not hit.get("cik"):
        return {"available": False, "reason": f"no CIK on file for {symbol}"}
    return statements(symbol, int(hit["cik"]))
