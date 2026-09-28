"""The depth layer -- what the company is, how it earns, what it owns, its past.

The quote tiles tell you what a stock costs today. These tell you what you are
actually buying: the business description, the revenue and margin trend over
years, the earnings it beat or missed, who owns it, and how today's volume
compares with a normal day.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import yfinance as yf

from . import fallback, yahoo


def _num(value: Any) -> Optional[float]:
    try:
        if hasattr(value, "item"):
            value = value.item()
        num = float(value)
        if num != num or math.isinf(num):
            return None
        return num
    except (TypeError, ValueError):
        return None


def _row(frame, *names: str) -> Dict[str, Optional[float]]:
    """Pull a named line item out of a yfinance statement, by period."""
    if frame is None or getattr(frame, "empty", True):
        return {}
    for name in names:
        if name in frame.index:
            series = frame.loc[name]
            out: Dict[str, Optional[float]] = {}
            for period, value in series.items():
                label = period.strftime("%Y") if hasattr(period, "strftime") else str(period)
                out[label] = _num(value)
            return out
    return {}


def fetch_profile(symbol: str) -> Dict[str, Any]:
    """Who the company is, in its own words."""
    info = yahoo.info(symbol)
    if not info:
        # Yahoo refused: Nasdaq still says what line of business it is in.
        extra = fallback.nasdaq_extras(symbol)
        info = {"sector": extra.get("sector"), "industry": extra.get("industry")}

    officers = []
    for person in (info.get("companyOfficers") or [])[:6]:
        officers.append(
            {
                "name": person.get("name"),
                "title": person.get("title"),
                "pay": _num(person.get("totalPay")),
                "born": person.get("yearBorn"),
            }
        )

    return {
        "summary": info.get("longBusinessSummary"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "employees": _num(info.get("fullTimeEmployees")),
        "country": info.get("country"),
        "city": info.get("city"),
        "state": info.get("state"),
        "website": info.get("website"),
        "ir_website": info.get("irWebsite"),
        "officers": officers,
        "governance_risk": _num(info.get("overallRisk")),
    }


def fetch_financials(symbol: str) -> Dict[str, Any]:
    """Revenue, profit and margin by year -- the economics, not the share price."""
    ticker = yf.Ticker(symbol)

    try:
        income = ticker.income_stmt
    except Exception:
        income = None
    try:
        balance = ticker.balance_sheet
    except Exception:
        balance = None
    try:
        cash = ticker.cashflow
    except Exception:
        cash = None

    revenue = _row(income, "Total Revenue", "TotalRevenue")
    gross = _row(income, "Gross Profit", "GrossProfit")
    operating = _row(income, "Operating Income", "OperatingIncome")
    net = _row(income, "Net Income", "NetIncome", "Net Income Common Stockholders")
    rnd = _row(income, "Research And Development", "ResearchAndDevelopment")

    years = sorted(revenue.keys(), reverse=True)[:5]

    rows: List[Dict[str, Any]] = []
    for i, year in enumerate(years):
        rev = revenue.get(year)
        prior = revenue.get(years[i + 1]) if i + 1 < len(years) else None
        rows.append(
            {
                "year": year,
                "revenue": rev,
                "revenue_growth": round(((rev / prior) - 1) * 100, 1)
                if rev and prior else None,
                "gross_profit": gross.get(year),
                "gross_margin": round((gross[year] / rev) * 100, 1)
                if gross.get(year) and rev else None,
                "operating_income": operating.get(year),
                "operating_margin": round((operating[year] / rev) * 100, 1)
                if operating.get(year) and rev else None,
                "net_income": net.get(year),
                "net_margin": round((net[year] / rev) * 100, 1)
                if net.get(year) and rev else None,
                "rnd": rnd.get(year),
            }
        )

    return {
        "available": bool(rows),
        "annual": rows,
        "balance": {
            "cash": _row(balance, "Cash And Cash Equivalents", "CashAndCashEquivalents"),
            "total_debt": _row(balance, "Total Debt", "TotalDebt"),
            "total_assets": _row(balance, "Total Assets", "TotalAssets"),
            "equity": _row(balance, "Stockholders Equity", "StockholdersEquity"),
        },
        "cashflow": {
            "operating": _row(cash, "Operating Cash Flow", "OperatingCashFlow"),
            "free": _row(cash, "Free Cash Flow", "FreeCashFlow"),
            "capex": _row(cash, "Capital Expenditure", "CapitalExpenditure"),
        },
    }


def fetch_earnings(symbol: str) -> Dict[str, Any]:
    """Past beats and misses, and when the next report lands."""
    ticker = yf.Ticker(symbol)

    history: List[Dict[str, Any]] = []
    next_date = None
    try:
        frame = ticker.earnings_dates
        if frame is not None and not frame.empty:
            for when, row in frame.iterrows():
                reported = _num(row.get("Reported EPS"))
                estimate = _num(row.get("EPS Estimate"))
                surprise = _num(row.get("Surprise(%)"))
                entry = {
                    "date": when.strftime("%Y-%m-%d") if hasattr(when, "strftime") else str(when),
                    "eps_estimate": estimate,
                    "eps_reported": reported,
                    "surprise_pct": round(surprise, 1) if surprise is not None else None,
                }
                if reported is None and next_date is None:
                    next_date = entry["date"]  # not yet reported
                if reported is not None:
                    history.append(entry)
    except Exception:
        pass

    beats = sum(1 for h in history if (h["surprise_pct"] or 0) > 0)
    return {
        "next_date": next_date,
        "history": history[:8],
        "beats": beats,
        "total": len(history),
        "beat_rate": round((beats / len(history)) * 100) if history else None,
    }


def fetch_dividends(symbol: str) -> Dict[str, Any]:
    """The payment history, and when the next one is likely to go ex.

    Yahoo exposes a single `exDividendDate`, and it is the date of the
    LAST payment, not the next one -- so a panel built on it shows an
    Apple dividend in August and nothing at all about the November one
    that actually matters to anyone holding options into it.

    The history is the better source. Four quarterly payments in a row
    establish a cadence, and the next ex-date projected off the median
    gap is right to within a few days for a company that has paid on
    schedule for years. It is an estimate and is labelled as one.

    The PAY date is different: Yahoo's `Dividend Date` is genuinely
    forward-looking, so when it is in the future it is reported as fact.
    """
    ticker = yf.Ticker(symbol)
    out: Dict[str, Any] = {
        "history": [], "cadence": None, "gap_days": None,
        "next_ex": None, "next_ex_estimated": True,
        "pay_date": None, "amount": None,
        # Set here too: a company that has never paid returns early, and
        # a caller reaching for the schedule should find an empty list
        # rather than a missing key.
        "schedule": [],
    }

    try:
        series = ticker.dividends
    except Exception:
        series = None
    if series is None or len(series) == 0:
        return out

    rows = [{"date": k.date().isoformat(), "amount": round(float(v), 4)}
            for k, v in series.tail(12).items()]
    out["history"] = rows
    out["amount"] = rows[-1]["amount"]

    if len(rows) >= 3:
        dates = [date.fromisoformat(r["date"]) for r in rows]
        gaps = sorted((dates[i + 1] - dates[i]).days for i in range(len(dates) - 1))
        gap = gaps[len(gaps) // 2]
        out["gap_days"] = gap
        out["cadence"] = ("monthly" if gap < 45 else "quarterly" if gap < 135
                          else "twice a year" if gap < 250 else "once a year")

        nxt = dates[-1] + timedelta(days=gap)
        # Ex-dividend dates fall on trading days. A projection that lands
        # on a Saturday is obviously wrong to a reader and undermines the
        # ones that are right.
        while nxt.weekday() > 4:
            nxt += timedelta(days=1)
        today = date.today()
        # If the projection has already gone by, the company is late or
        # the cadence changed; step forward rather than show a past date.
        while nxt < today:
            nxt += timedelta(days=gap or 91)
            while nxt.weekday() > 4:
                nxt += timedelta(days=1)
        out["next_ex"] = nxt.isoformat()

    try:
        cal = ticker.calendar or {}
        ex = cal.get("Ex-Dividend Date")
        pay = cal.get("Dividend Date")
        today = date.today()
        # Yahoo's ex-date is usually the last one. On the rare occasion it
        # is ahead of us it is the announced date, which beats a guess.
        if ex and getattr(ex, "year", None) and ex >= today:
            out["next_ex"] = ex.isoformat()
            out["next_ex_estimated"] = False
        if pay and getattr(pay, "year", None) and pay >= today:
            out["pay_date"] = pay.isoformat()
    except Exception:
        pass

    out["schedule"] = _forward_schedule(out)
    return out


def _forward_schedule(div: Dict[str, Any], horizon_days: int = 800) -> List[Dict]:
    """The dividends still to come, projected out on the same cadence.

    Option pricing needs to know which payments fall before each expiry,
    and the answer for a two-year LEAP is not "the next one". Once a
    company has established a rhythm the later dates are a worse guess
    than the first -- but a dividend assumed on roughly the right day is
    far closer to the truth than pretending there is none, which is what
    a zero yield would say.
    """
    ex, gap, amount = div.get("next_ex"), div.get("gap_days"), div.get("amount")
    if not ex or not gap or not amount:
        return []

    out, when = [], date.fromisoformat(ex)
    stop = date.today() + timedelta(days=horizon_days)
    while when <= stop and len(out) < 12:
        out.append({"date": when.isoformat(), "amount": amount,
                    # Only the first can be an announced date; the rest
                    # are this function's arithmetic and say so.
                    "estimated": bool(out) or bool(div.get("next_ex_estimated"))})
        when = when + timedelta(days=gap)
        while when.weekday() > 4:
            when += timedelta(days=1)
    return out


def fetch_ownership(symbol: str) -> Dict[str, Any]:
    """Who holds the shares -- institutions, insiders, and the biggest names."""
    ticker = yf.Ticker(symbol)
    result: Dict[str, Any] = {"institutions": [], "insider_pct": None, "institution_pct": None}

    try:
        major = ticker.major_holders
        if major is not None and not major.empty:
            # Newer yfinance returns rows keyed insidersPercentHeld,
            # institutionsPercentHeld, institutionsFloatPercentHeld AND
            # institutionsCount -- match only the percentage rows, or the
            # holder count gets read as a percentage.
            for key, value in major.iloc[:, 0].items():
                label = str(key).lower()
                if "percentheld" not in label and "percent" not in label:
                    continue
                if "insider" in label:
                    result["insider_pct"] = round((_num(value) or 0) * 100, 2)
                elif "institution" in label and "float" not in label:
                    result["institution_pct"] = round((_num(value) or 0) * 100, 2)
            count = major.iloc[:, 0].get("institutionsCount")
            result["institution_count"] = int(_num(count)) if _num(count) else None
    except Exception:
        pass

    try:
        holders = ticker.institutional_holders
        if holders is not None and not holders.empty:
            for _, row in holders.head(8).iterrows():
                result["institutions"].append(
                    {
                        "name": row.get("Holder"),
                        "shares": _num(row.get("Shares")),
                        "value": _num(row.get("Value")),
                        "pct_out": round((_num(row.get("pctHeld")) or 0) * 100, 2),
                    }
                )
    except Exception:
        pass

    return result


def fetch_volume_profile(symbol: str) -> Dict[str, Any]:
    """Is today busy? Volume only means something next to a normal day."""
    ticker = yf.Ticker(symbol)
    try:
        frame = ticker.history(period="3mo", interval="1d")
    except Exception:
        return {"available": False}

    if frame is None or frame.empty:
        return {"available": False}

    volumes = [int(v) for v in frame["Volume"].tolist() if v == v]
    if not volumes:
        return {"available": False}

    today = volumes[-1]
    avg30 = sum(volumes[-30:]) / len(volumes[-30:])
    avg90 = sum(volumes) / len(volumes)

    # Drop NaN closes before doing any arithmetic. yfinance intermittently
    # returns a blank bar -- a partially formed session, or a hole in its
    # history -- and a single NaN turns every mean and standard deviation
    # downstream into NaN, which then serialises as null and silently empties
    # the volatility panel.
    closes = [float(c) for c in frame["Close"].tolist() if c == c]
    if len(closes) < 6:
        return {"available": False, "reason": "not enough clean price history"}

    up_days = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i - 1])

    # Daily percentage moves give a realised-volatility read to sit next to IV.
    moves = [
        abs((closes[i] / closes[i - 1]) - 1) * 100
        for i in range(1, len(closes))
        if closes[i - 1]
    ]
    avg_move = sum(moves) / len(moves) if moves else None

    # Realised volatility proper: standard deviation of daily log returns,
    # annualised by sqrt(252). This is the number that belongs next to implied
    # volatility -- the two are then measuring the same thing, one looking back
    # and one looking forward.
    def realised(window: int) -> Optional[float]:
        rets = []
        series = closes[-(window + 1):]
        for i in range(1, len(series)):
            if series[i - 1] and series[i]:
                rets.append(math.log(series[i] / series[i - 1]))
        if len(rets) < 5:
            return None
        mean = sum(rets) / len(rets)
        var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        out = math.sqrt(var) * math.sqrt(252) * 100
        return round(out, 1) if math.isfinite(out) else None

    return {
        "available": True,
        "today": today,
        "avg_30d": int(avg30),
        "avg_90d": int(avg90),
        "relative": round(today / avg30, 2) if avg30 else None,
        "up_days": up_days,
        "total_days": len(closes) - 1,
        "up_day_pct": round((up_days / (len(closes) - 1)) * 100) if len(closes) > 1 else None,
        "avg_daily_move_pct": round(avg_move, 2) if avg_move else None,
        "realised_vol_20d": realised(20),
        "realised_vol_60d": realised(60),
        "realised_vol_annual": realised(len(closes) - 1),
        "biggest_up_day_pct": round(
            max(((closes[i] / closes[i - 1]) - 1) * 100 for i in range(1, len(closes))), 2
        ) if len(closes) > 1 else None,
        "biggest_down_day_pct": round(
            min(((closes[i] / closes[i - 1]) - 1) * 100 for i in range(1, len(closes))), 2
        ) if len(closes) > 1 else None,
        "max_volume_90d": max(volumes),
    }


def fetch_price_history_long(symbol: str) -> Dict[str, Any]:
    """Multi-horizon returns -- the shape of the story over years, not days."""
    ticker = yf.Ticker(symbol)
    out: Dict[str, Any] = {"returns": {}, "points": []}

    try:
        frame = ticker.history(period="5y", interval="1wk")
    except Exception:
        return out

    if frame is None or frame.empty:
        return out

    # Filter dates and closes together. Dropping NaN closes on their own while
    # keeping every date silently shifts the whole x-axis by however many bars
    # were blank.
    pairs = [
        (d.strftime("%Y-%m-%d"), float(c))
        for d, c in zip(frame.index, frame["Close"].tolist())
        if c == c
    ]
    if not pairs:
        return out
    dates = [d for d, _ in pairs]
    closes = [c for _, c in pairs]

    last = closes[-1]
    # Weekly bars, so these offsets are weeks back from today.
    for label, weeks in (("1m", 4), ("3m", 13), ("6m", 26), ("1y", 52), ("3y", 156), ("5y", 260)):
        if len(closes) > weeks:
            prior = closes[-weeks - 1]
            out["returns"][label] = round(((last / prior) - 1) * 100, 1) if prior else None

    step = max(1, len(closes) // 120)
    out["points"] = [
        {"date": dates[i], "close": round(closes[i], 2)} for i in range(0, len(closes), step)
    ]
    out["all_time_high"] = round(max(closes), 2)
    out["all_time_low"] = round(min(closes), 2)
    out["off_high_pct"] = round(((last / max(closes)) - 1) * 100, 1)
    return out
