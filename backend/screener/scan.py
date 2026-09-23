"""Measuring the whole universe.

Everything here is computed from daily OHLCV, because that is the only thing
available in bulk. Option chains are one HTTP request per symbol per expiry;
at eleven thousand symbols that is a non-starter, so the chain is pulled
later and only for the handful of names a ranking actually surfaces.

That split is deliberate and it is the same one the rest of QUIPU uses:
measure widely on what is cheap, then go deep on what survived.

What gets measured, and why it earns its place:

  liquidity    dollar volume and price. Every experienced options trader
               says the same thing first -- if you cannot get out, nothing
               else about the trade matters.
  movement     realised volatility, ATR, the average absolute day. How much
               this thing actually moves, which is what an option is priced
               on.
  compression  short-window vol against long-window vol. Volatility is
               mean-reverting and cycles between quiet and loud; a stock
               that has gone unusually quiet is where long options are
               cheap, and the reverse is where selling is paid.
  vol rank     where today's realised vol sits inside its own trailing year,
               0-100. This is the honest stand-in for IV rank until the
               chain is fetched, and it is the number that says whether
               "40% vol" is high or low FOR THIS STOCK.
  trend        12-1 momentum and the R-squared of a fit through log price.
               Return alone rewards one lucky gap; R-squared asks whether
               the move was orderly enough to still be in force.
  thrust       recent return, relative volume, distance above the 20-day
               average. The short-horizon counterpart.
"""

from __future__ import annotations

import math
import time
import warnings
from typing import Any, Dict, Iterable, List

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

import yfinance as yf  # noqa: E402

TRADING_DAYS = 252
CHUNK = 250          # symbols per download call


def _annualised(returns: pd.DataFrame, window: int) -> pd.Series:
    return returns.tail(window).std() * math.sqrt(TRADING_DAYS) * 100


def _pct_change_over(close: pd.DataFrame, days: int) -> pd.Series:
    if len(close) <= days:
        return pd.Series(np.nan, index=close.columns)
    return (close.iloc[-1] / close.iloc[-1 - days] - 1) * 100


def _trend_r2(close: pd.DataFrame, window: int = 126) -> pd.Series:
    """How orderly the move was.

    A stock that doubled on one gap and then sat still has the same return as
    one that climbed steadily, and they are not the same trade. Fitting a
    straight line through log price and reporting R-squared separates them:
    1.0 is a ruler, 0.0 is noise that happens to have ended higher.
    """
    seg = np.log(close.tail(window))
    n = len(seg)
    if n < 20:
        return pd.Series(np.nan, index=close.columns)
    x = np.arange(n, dtype=float)
    x -= x.mean()
    xx = float((x * x).sum())
    y = seg.to_numpy(dtype=float)
    ymean = np.nanmean(y, axis=0)
    yc = y - ymean
    beta = np.nansum(x[:, None] * yc, axis=0) / xx
    resid = yc - beta[None, :] * x[:, None]
    ss_res = np.nansum(resid ** 2, axis=0)
    ss_tot = np.nansum(yc ** 2, axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        r2 = 1.0 - ss_res / ss_tot
    return pd.Series(np.where(ss_tot > 0, r2, np.nan), index=close.columns)


def _vol_rank(returns: pd.DataFrame, window: int = 20, look: int = TRADING_DAYS) -> pd.Series:
    """Today's 20-day vol as a percentile of its own trailing year.

    The level of volatility means nothing across stocks -- a utility at 25%
    is wild, a biotech at 25% is asleep. The percentile is comparable, and
    it is what tells you whether options on THIS name are dear or cheap by
    its own standards.
    """
    rolling = returns.rolling(window).std() * math.sqrt(TRADING_DAYS) * 100
    tail = rolling.tail(look)
    if len(tail) < 40:
        return pd.Series(np.nan, index=returns.columns)
    current = tail.iloc[-1]
    counts = tail.notna().sum()
    rank = (tail < current).sum() / counts.replace(0, np.nan) * 100
    # A name listed four months ago has a mostly-empty window, and ranking
    # today against thirty observations produced a confident "0th percentile
    # of its own year" for stocks that do not have a year. Require most of
    # one before the number is allowed to mean anything.
    enough = counts >= int(look * 0.6)
    return rank.where(current.notna() & enough)


def _rvol(volume: pd.DataFrame) -> pd.Series:
    """Volume against a normal day, measured on the last COMPLETE session.

    While the market is open the newest bar holds a part-day's volume, and
    dividing that by a full-day median says every stock in the country is
    unusually quiet. It made "moving now" rank its leaders at 0.4x normal
    volume, which is the opposite of what the column claims to show.
    """
    if volume.empty:
        return pd.Series(dtype=float)
    idx = volume.index
    last = idx[-1]
    today = pd.Timestamp.now(tz=getattr(last, "tzinfo", None)).normalize()
    partial = getattr(last, "normalize", lambda: last)() == today
    series = volume.iloc[:-1] if (partial and len(volume) > 21) else volume
    if len(series) < 21:
        return pd.Series(np.nan, index=volume.columns)
    base = series.rolling(20).median().iloc[-1]
    return series.iloc[-1] / base.replace(0, np.nan)


def _atr_pct(high: pd.DataFrame, low: pd.DataFrame, close: pd.DataFrame,
             window: int = 14) -> pd.Series:
    prev = close.shift(1)
    tr = pd.concat([(high - low).abs(), (high - prev).abs(), (low - prev).abs()])
    tr = tr.groupby(level=0).max()
    atr = tr.tail(window).mean()
    return atr / close.iloc[-1] * 100


def measure(frame: pd.DataFrame) -> pd.DataFrame:
    """Every metric, for one downloaded chunk."""
    close = frame["Close"].dropna(axis=1, how="all")
    if close.empty:
        return pd.DataFrame()

    # Drop trailing rows that carry no close for anything.
    #
    # Yahoo emits a placeholder bar for the current session before it
    # has a price in it. Left in place, close.iloc[-1] is NaN -- so the
    # price, the distance from every moving average and most of the row
    # go NaN with it, the symbol silently fails the price gate and
    # disappears from the rankings. It also shifts every positional
    # lookup by one, so the twelve-month momentum quietly measures a
    # different year than it claims to.
    while len(close) and bool(close.iloc[-1].isna().all()):
        close = close.iloc[:-1]
    if close.empty:
        return pd.DataFrame()
    frame = frame.loc[close.index]
    high, low = frame["High"][close.columns], frame["Low"][close.columns]
    volume = frame["Volume"][close.columns]

    rets = np.log(close / close.shift(1))
    dollar = (close * volume).rolling(20).median().iloc[-1]
    sma20 = close.rolling(20).mean().iloc[-1]
    sma50 = close.rolling(50).mean().iloc[-1]
    sma200 = close.rolling(200).mean().iloc[-1]
    last = close.iloc[-1]

    vol20 = _annualised(rets, 20)
    vol60 = _annualised(rets, 60)
    vol252 = _annualised(rets, TRADING_DAYS)

    # Peak-to-trough over the year, as a positive percentage.
    year = close.tail(TRADING_DAYS)
    drawdown = ((year / year.cummax() - 1).min() * 100).abs()

    out = pd.DataFrame({
        "price": last,
        "dollar_vol": dollar,
        "bars": close.notna().sum(),
        "rvol": _rvol(volume),
        "vol20": vol20,
        "vol60": vol60,
        "vol252": vol252,
        # Below 1 means it has gone quiet against its own year.
        "vol_ratio": vol20 / vol252,
        "vol_rank": _vol_rank(rets),
        "atr_pct": _atr_pct(high, low, close),
        "avg_move": rets.tail(20).abs().mean() * 100,
        "gap": (frame["Open"][close.columns] / close.shift(1) - 1).tail(20).abs().mean() * 100,
        "ret_1m": _pct_change_over(close, 21),
        "ret_3m": _pct_change_over(close, 63),
        "ret_6m": _pct_change_over(close, 126),
        "ret_12m": _pct_change_over(close, TRADING_DAYS),
        "trend_r2": _trend_r2(close),
        "from_20": (last / sma20 - 1) * 100,
        "from_50": (last / sma50 - 1) * 100,
        "from_200": (last / sma200 - 1) * 100,
        "drawdown": drawdown,
    })

    # Classic 12-1 momentum: the year's return excluding the most recent
    # month, because the last month reliably reverses and would otherwise
    # cancel the signal it is meant to measure.
    if len(close) > TRADING_DAYS + 1:
        out["mom_12_1"] = (close.iloc[-22] / close.iloc[-1 - TRADING_DAYS] - 1) * 100
    else:
        out["mom_12_1"] = np.nan

    return out


def scan(symbols: Iterable[str], period: str = "2y", chunk: int = CHUNK,
         progress: bool = False) -> pd.DataFrame:
    """Measure every symbol given, in chunks so memory stays flat."""
    syms = list(dict.fromkeys(symbols))
    frames: List[pd.DataFrame] = []
    started = time.time()

    for i in range(0, len(syms), chunk):
        batch = syms[i:i + chunk]
        try:
            raw = yf.download(batch, period=period, interval="1d",
                              auto_adjust=True, threads=True, progress=False)
        except Exception:
            continue
        if raw is None or raw.empty:
            continue
        # One symbol comes back without the ticker column level.
        if not isinstance(raw.columns, pd.MultiIndex):
            raw.columns = pd.MultiIndex.from_product([raw.columns, batch[:1]])
        try:
            frames.append(measure(raw))
        except Exception:
            continue
        if progress:
            done = min(i + chunk, len(syms))
            el = time.time() - started
            print(f"  {done}/{len(syms)}  {el:.0f}s  "
                  f"eta {el / done * (len(syms) - done):.0f}s", flush=True)

    if not frames:
        return pd.DataFrame()
    out = pd.concat(frames)
    out.index.name = "symbol"
    return out[~out.index.duplicated()]


if __name__ == "__main__":
    import sys
    from . import universe

    n = int(sys.argv[1]) if len(sys.argv) > 1 else 500
    syms = universe.symbols()[:n]
    t = time.time()
    df = scan(syms, progress=True)
    el = time.time() - t
    print(f"\n{len(df)} of {len(syms)} measured in {el:.0f}s "
          f"({el / max(len(syms), 1) * 1000:.0f} ms/symbol)")
    liquid = df[(df.dollar_vol > 5e6) & (df.price > 5)]
    print(f"liquid (>$5m/day, >$5): {len(liquid)}")
    cols = ["price", "dollar_vol", "vol20", "vol_rank", "vol_ratio",
            "ret_12m", "trend_r2", "from_200"]
    print(liquid.sort_values("dollar_vol", ascending=False)[cols].head(12).round(2))
