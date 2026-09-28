"""Price, fundamentals and history. yfinance -- free, no key.

The quote and fundamentals read Yahoo's quote summary through yahoo.py,
which shares one answer per symbol and backs off after a refusal. When
that summary is empty the quote comes from fallback.py instead, and says
so in `source`.
"""

from __future__ import annotations

from typing import Any, Dict, List

import yfinance as yf

from . import fallback, yahoo


def _num(value: Any) -> Any:
    """yfinance hands back numpy scalars; JSON does not want them."""
    if value is None:
        return None
    try:
        if hasattr(value, "item"):
            value = value.item()
        if isinstance(value, float) and value != value:  # NaN
            return None
        return value
    except Exception:
        return None


def fetch_quote(symbol: str) -> Dict[str, Any]:
    """Current price and the headline numbers for a ticker."""
    info = yahoo.info(symbol)

    price = _num(info.get("currentPrice") or info.get("regularMarketPrice"))
    if not price:
        backup = fallback.quote(symbol)
        if backup:
            return backup
    prev = _num(info.get("previousClose") or info.get("regularMarketPreviousClose"))
    change = round(price - prev, 4) if price and prev else None
    change_pct = round((change / prev) * 100, 3) if change and prev else None

    return {
        "symbol": symbol.upper(),
        "name": info.get("longName") or info.get("shortName") or symbol.upper(),
        "exchange": info.get("fullExchangeName") or info.get("exchange"),
        "currency": info.get("currency", "USD"),
        "price": price,
        "previous_close": prev,
        "change": change,
        "change_pct": change_pct,
        "day_low": _num(info.get("dayLow")),
        "day_high": _num(info.get("dayHigh")),
        "year_low": _num(info.get("fiftyTwoWeekLow")),
        "year_high": _num(info.get("fiftyTwoWeekHigh")),
        "volume": _num(info.get("volume") or info.get("regularMarketVolume")),
        "avg_volume": _num(info.get("averageVolume")),
        "market_cap": _num(info.get("marketCap")),
        "beta": _num(info.get("beta")),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "employees": _num(info.get("fullTimeEmployees")),
        "website": info.get("website"),
        "summary": info.get("longBusinessSummary"),
        "source": "Yahoo Finance",
    }


def fetch_fundamentals(symbol: str) -> Dict[str, Any]:
    """Valuation, margins, growth, dividend, analyst view."""
    info = yahoo.info(symbol)

    target = _num(info.get("targetMeanPrice"))
    price = _num(info.get("currentPrice") or info.get("regularMarketPrice"))
    if not info:
        # Yahoo refused. Nasdaq's summary has the consensus target and
        # the price to measure it from; the ratios have nowhere else free.
        extra = fallback.nasdaq_extras(symbol)
        target = extra.get("target")
        price = price or (fetch_quote(symbol) or {}).get("price")
    upside = round(((target / price) - 1) * 100, 2) if target and price else None

    return {
        "valuation": {
            "pe_trailing": _num(info.get("trailingPE")),
            "pe_forward": _num(info.get("forwardPE")),
            "peg": _num(info.get("pegRatio")),
            "price_to_book": _num(info.get("priceToBook")),
            "price_to_sales": _num(info.get("priceToSalesTrailing12Months")),
            "ev_to_ebitda": _num(info.get("enterpriseToEbitda")),
        },
        "health": {
            "profit_margin": _num(info.get("profitMargins")),
            "operating_margin": _num(info.get("operatingMargins")),
            "gross_margin": _num(info.get("grossMargins")),
            "roe": _num(info.get("returnOnEquity")),
            "debt_to_equity": _num(info.get("debtToEquity")),
            "current_ratio": _num(info.get("currentRatio")),
            "free_cashflow": _num(info.get("freeCashflow")),
        },
        "growth": {
            "revenue_growth": _num(info.get("revenueGrowth")),
            "earnings_growth": _num(info.get("earningsGrowth")),
            "eps_trailing": _num(info.get("trailingEps")),
            "eps_forward": _num(info.get("forwardEps")),
        },
        "dividend": {
            "yield": _num(info.get("dividendYield")),
            "rate": _num(info.get("dividendRate")),
            "payout_ratio": _num(info.get("payoutRatio")),
            "ex_date": _num(info.get("exDividendDate")),
        },
        "analysts": {
            "recommendation": info.get("recommendationKey"),
            "mean_score": _num(info.get("recommendationMean")),
            "count": _num(info.get("numberOfAnalystOpinions")),
            "target_mean": target,
            "target_high": _num(info.get("targetHighPrice")),
            "target_low": _num(info.get("targetLowPrice")),
            "upside_pct": upside,
        },
        "short_interest": {
            "shares_short": _num(info.get("sharesShort")),
            "short_ratio": _num(info.get("shortRatio")),
            "short_pct_float": _num(info.get("shortPercentOfFloat")),
            "float_shares": _num(info.get("floatShares")),
        },
    }


def fetch_intraday(symbol: str) -> Dict[str, Any]:
    """Today minute by minute, for the live chart. Falls back to 5 days."""
    ticker = yf.Ticker(symbol)

    for period, interval in (("1d", "5m"), ("5d", "15m")):
        try:
            frame = ticker.history(period=period, interval=interval)
        except Exception:
            continue
        if frame is None or frame.empty:
            continue

        points = []
        for index, row in frame.iterrows():
            close = _num(row["Close"])
            if close is None:
                continue
            points.append(
                {
                    "t": index.strftime("%H:%M") if period == "1d" else index.strftime("%m-%d %H:%M"),
                    "close": round(float(close), 4),
                    "volume": int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,
                }
            )

        if len(points) > 2:
            closes = [p["close"] for p in points]
            return {
                "points": points,
                "interval": interval,
                "span": period,
                "open": closes[0],
                "last": closes[-1],
                "min": min(closes),
                "max": max(closes),
                "change_pct": round(((closes[-1] / closes[0]) - 1) * 100, 2) if closes[0] else None,
            }

    return {"points": [], "interval": None, "span": None}


def _frame_points(frame, label_fmt: str) -> List[Dict[str, Any]]:
    """OHLCV rows, NaN bars dropped. Candles need all four prices, so a bar
    missing any of them is discarded rather than half-drawn."""
    out: List[Dict[str, Any]] = []
    if frame is None or frame.empty:
        return out
    for index, row in frame.iterrows():
        o, h, l, c = (_num(row.get(k)) for k in ("Open", "High", "Low", "Close"))
        if None in (o, h, l, c):
            continue
        v = row.get("Volume")
        out.append({
            "t": index.strftime(label_fmt),
            "o": round(float(o), 4), "h": round(float(h), 4),
            "l": round(float(l), 4), "c": round(float(c), 4),
            "v": int(v) if v == v else 0,
        })
    return out


def _summarise(points: List[Dict[str, Any]]) -> Dict[str, Any]:
    if len(points) < 2:
        return {"points": points, "change_pct": None, "min": None, "max": None}
    closes = [p["c"] for p in points]
    lows = [p["l"] for p in points]
    highs = [p["h"] for p in points]
    return {
        "points": points,
        "first": closes[0],
        "last": closes[-1],
        "min": min(lows),
        "max": max(highs),
        "change_pct": round(((closes[-1] / closes[0]) - 1) * 100, 2) if closes[0] else None,
    }


def fetch_series(symbol: str) -> Dict[str, Any]:
    """Every range the chart offers, from three requests rather than six.

    Intraday needs its own granularity, but 1M/6M/1Y/5Y are all slices of one
    daily history -- so we pull that once and cut it up. Switching range in
    the UI is then instant and costs no network at all.
    """
    ticker = yf.Ticker(symbol)
    out: Dict[str, Any] = {}

    try:
        out["1D"] = _summarise(_frame_points(
            ticker.history(period="1d", interval="5m"), "%H:%M"))
    except Exception:
        out["1D"] = _summarise([])

    try:
        out["5D"] = _summarise(_frame_points(
            ticker.history(period="5d", interval="30m"), "%m-%d %H:%M"))
    except Exception:
        out["5D"] = _summarise([])

    daily: List[Dict[str, Any]] = []
    try:
        daily = _frame_points(ticker.history(period="5y", interval="1d"), "%Y-%m-%d")
    except Exception:
        pass

    # Trading days, not calendar days, because that is what the series holds.
    for label, bars in (("1M", 22), ("6M", 126), ("1Y", 252), ("5Y", len(daily))):
        out[label] = _summarise(daily[-bars:] if bars and len(daily) > bars else daily)

    out["ranges"] = ["1D", "5D", "1M", "6M", "1Y", "5Y"]
    out["default"] = "6M"
    return out


def fetch_series_live(symbol: str) -> Dict[str, Any]:
    """Just today's bars, for the fifteen-second refresh.

    The chart's other ranges cannot change intraday -- a daily bar from March
    is settled -- so re-pulling five years every tick would buy nothing and
    cost a rate limit. Only the 1D frame is live.
    """
    try:
        frame = yf.Ticker(symbol).history(period="1d", interval="5m")
    except Exception:
        return _summarise([])
    return _summarise(_frame_points(frame, "%H:%M"))


def fetch_history(symbol: str, period: str = "6mo") -> Dict[str, Any]:
    """Daily OHLCV, trimmed to what a sparkline needs."""
    frame = yf.Ticker(symbol).history(period=period, interval="1d")
    if frame is None or frame.empty:
        return {"points": [], "period": period}

    points: List[Dict[str, Any]] = []
    for index, row in frame.iterrows():
        # Skip blank bars. yfinance returns a NaN close for a session it has
        # not settled yet; letting one through makes change_pct NaN and draws
        # the chart as a fall, because NaN loses every comparison.
        close = _num(row["Close"])
        if close is None:
            continue
        points.append(
            {
                "date": index.strftime("%Y-%m-%d"),
                "close": round(float(close), 4),
                "volume": int(row["Volume"]) if row["Volume"] == row["Volume"] else 0,
            }
        )

    if not points:
        return {"points": [], "period": period}

    closes = [p["close"] for p in points]
    return {
        "points": points,
        "period": period,
        "first": closes[0] if closes else None,
        "last": closes[-1] if closes else None,
        "min": min(closes) if closes else None,
        "max": max(closes) if closes else None,
        "change_pct": round(((closes[-1] / closes[0]) - 1) * 100, 2)
        if len(closes) > 1 and closes[0]
        else None,
    }
