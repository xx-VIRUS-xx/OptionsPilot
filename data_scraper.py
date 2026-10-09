"""
Historical Data Scraper
------------------------
Fetches real intraday candle data for Nifty/BankNifty
from the last trading session using yfinance.

Data is cached locally so you don't re-download every run.
"""

import json
import logging
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

import yfinance as yf
import pandas as pd

from config import DATA_DIR

logger = logging.getLogger("scraper")
IST = timezone(timedelta(hours=5, minutes=30))

CACHE_DIR = DATA_DIR / "history"
CACHE_DIR.mkdir(exist_ok=True)

# Yahoo Finance tickers for NSE indices
YAHOO_TICKERS = {
    "NIFTY": "^NSEI",
    "BANKNIFTY": "^NSEBANK",
}


def _last_trading_day(ref_date: date | None = None) -> date:
    """Get the most recent trading day (skip weekends)."""
    d = ref_date or date.today()
    # If today is a weekday and market hasn't opened yet, use yesterday
    now = datetime.now(IST)
    if d == date.today() and now.hour < 16:
        d -= timedelta(days=1)
    while d.weekday() >= 5:  # Saturday=5, Sunday=6
        d -= timedelta(days=1)
    return d


def _cache_path(index: str, session_date: date, timeframe: str) -> Path:
    return CACHE_DIR / f"{index}_{session_date.isoformat()}_{timeframe}.json"


def scrape_session(index: str, session_date: date | None = None,
                   timeframe: str = "5m") -> list[dict]:
    """
    Fetch intraday candles for a given index and date.

    Args:
        index: "NIFTY" or "BANKNIFTY"
        session_date: Date of the session (default: last trading day)
        timeframe: "5m", "15m", or "1m"

    Returns:
        List of candle dicts with keys: timestamp, open, high, low, close, volume
    """
    session_date = session_date or _last_trading_day()
    ticker = YAHOO_TICKERS.get(index)
    if not ticker:
        logger.error("Unknown index: %s", index)
        return []

    # Check cache first
    cache = _cache_path(index, session_date, timeframe)
    if cache.exists():
        logger.info("Loading cached data: %s", cache.name)
        candles = json.loads(cache.read_text())
        return candles

    logger.info("Fetching %s %s data for %s from Yahoo Finance...",
                index, timeframe, session_date)

    try:
        # yfinance needs start and end dates; end is exclusive
        start = session_date
        end = session_date + timedelta(days=1)

        df = yf.download(
            ticker,
            start=start.isoformat(),
            end=end.isoformat(),
            interval=timeframe,
            progress=False,
        )

        if df.empty:
            # Try fetching a range and filtering (yfinance quirk for single days)
            df = yf.download(
                ticker,
                start=(session_date - timedelta(days=5)).isoformat(),
                end=end.isoformat(),
                interval=timeframe,
                progress=False,
            )
            if not df.empty:
                df.index = df.index.tz_localize("Asia/Kolkata") if df.index.tz is None else df.index.tz_convert("Asia/Kolkata")
                df = df[df.index.date == session_date]

        if df.empty:
            logger.warning("No data returned for %s on %s", index, session_date)
            return []

        # Flatten MultiIndex columns if present (yfinance returns MultiIndex)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Ensure timezone is IST
        if df.index.tz is None:
            df.index = df.index.tz_localize("Asia/Kolkata")
        else:
            df.index = df.index.tz_convert("Asia/Kolkata")

        # Convert to list of dicts
        candles = []
        for ts, row in df.iterrows():
            candles.append({
                "timestamp": ts.isoformat(),
                "open": round(float(row["Open"]), 2),
                "high": round(float(row["High"]), 2),
                "low": round(float(row["Low"]), 2),
                "close": round(float(row["Close"]), 2),
                "volume": int(row.get("Volume", 0)),
            })

        if candles:
            cache.write_text(json.dumps(candles, indent=2))
            logger.info("Cached %d candles → %s", len(candles), cache.name)

        return candles

    except Exception as e:
        logger.error("Failed to fetch data for %s: %s", index, e)
        return []


def scrape_last_session(indices: list[str] | None = None
                        ) -> dict[str, dict[str, list[dict]]]:
    """
    Scrape both 5m and 15m candles for all indices from last trading session.

    Returns:
        {
            "NIFTY": {"5m": [...candles], "15m": [...candles]},
            "BANKNIFTY": {"5m": [...candles], "15m": [...candles]},
            "date": "2026-03-20",
        }
    """
    indices = indices or list(YAHOO_TICKERS.keys())
    session_date = _last_trading_day()
    result = {"date": session_date.isoformat()}

    for index in indices:
        result[index] = {}
        for tf in ("5m", "15m"):
            result[index][tf] = scrape_session(index, session_date, tf)
            count = len(result[index][tf])
            if count > 0:
                logger.info("  %s %s: %d candles (%s → %s)",
                            index, tf, count,
                            result[index][tf][0]["timestamp"][-8:],
                            result[index][tf][-1]["timestamp"][-8:])
            else:
                logger.warning("  %s %s: NO DATA", index, tf)

    return result


def list_cached_sessions() -> list[dict]:
    """List all cached session data files."""
    sessions = {}
    for f in sorted(CACHE_DIR.glob("*.json")):
        parts = f.stem.split("_")
        if len(parts) >= 3:
            index = parts[0]
            date_str = parts[1]
            tf = parts[2]
            key = date_str
            if key not in sessions:
                sessions[key] = {"date": date_str, "indices": {}}
            if index not in sessions[key]["indices"]:
                sessions[key]["indices"][index] = []
            sessions[key]["indices"][index].append(tf)

    return sorted(sessions.values(), key=lambda x: x["date"], reverse=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    print("Scraping last session data...\n")
    data = scrape_last_session()
    print(f"\nSession date: {data['date']}")
    for idx in ["NIFTY", "BANKNIFTY"]:
        if idx in data:
            for tf in ["5m", "15m"]:
                candles = data[idx].get(tf, [])
                if candles:
                    opens = [c["open"] for c in candles]
                    print(f"  {idx} {tf}: {len(candles)} candles | "
                          f"Open={candles[0]['open']:.0f} → Close={candles[-1]['close']:.0f} | "
                          f"High={max(c['high'] for c in candles):.0f} Low={min(c['low'] for c in candles):.0f}")
