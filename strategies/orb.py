"""
Opening Range Breakout (ORB) Strategy
--------------------------------------
The #1 intraday options strategy in India.

Logic:
1. Wait for the first 15 minutes (9:15 - 9:30) to form the opening range.
2. If price breaks ABOVE the high → BUY CE (call option)
3. If price breaks BELOW the low → BUY PE (put option)
4. Use ATM or 1-strike OTM for maximum bang per buck.

Why it works:
- First 15 min captures institutional order flow direction
- Breakout with volume = strong directional move
- Options premiums move 50-200% on good breakouts
"""

import logging
from datetime import datetime, timezone, timedelta

from strategies.base import BaseStrategy, TradeSignal, Signal
from config import BANKNIFTY_STRIKE_INTERVAL, NIFTY_STRIKE_INTERVAL

logger = logging.getLogger("orb")
IST = timezone(timedelta(hours=5, minutes=30))


class ORBStrategy(BaseStrategy):
    name = "orb"

    def __init__(self):
        self._range_high: dict[str, float] = {}
        self._range_low: dict[str, float] = {}
        self._range_set: dict[str, bool] = {}
        self._triggered_today: dict[str, bool] = {}
        self._last_reset_date: str = ""

    def _reset_if_new_day(self):
        today = datetime.now(IST).strftime("%Y-%m-%d")
        if today != self._last_reset_date:
            self._range_high.clear()
            self._range_low.clear()
            self._range_set.clear()
            self._triggered_today.clear()
            self._last_reset_date = today

    def analyze(self, index: str, spot_price: float, option_chain: dict,
                candles_5m: list[dict], candles_15m: list[dict]) -> TradeSignal:
        self._reset_if_new_day()
        now = datetime.now(IST)

        # Only trade between 9:30 and 11:30 (ORB works best in morning)
        hour_min = now.hour * 100 + now.minute
        if hour_min < 930 or hour_min > 1130:
            return self._hold(index, "Outside ORB window (9:30-11:30)")

        # Only trigger once per day per index
        if self._triggered_today.get(index):
            return self._hold(index, "ORB already triggered today")

        # Build opening range from 9:15-9:30 candles
        if not self._range_set.get(index):
            opening_candles = [c for c in candles_5m
                               if 915 <= self._candle_time(c) < 930]
            if len(opening_candles) < 3:
                return self._hold(index, "Waiting for opening range (need 9:15-9:30 data)")

            self._range_high[index] = max(c["high"] for c in opening_candles)
            self._range_low[index] = min(c["low"] for c in opening_candles)
            self._range_set[index] = True
            range_size = self._range_high[index] - self._range_low[index]
            logger.info("ORB range set for %s: %.0f - %.0f (size=%.0f)",
                        index, self._range_low[index], self._range_high[index], range_size)

        high = self._range_high[index]
        low = self._range_low[index]
        range_size = high - low

        # Need minimum range size (avoid choppy days)
        min_range = 50 if index == "BANKNIFTY" else 20
        if range_size < min_range:
            return self._hold(index, f"Range too narrow ({range_size:.0f} < {min_range})")

        interval = BANKNIFTY_STRIKE_INTERVAL if index == "BANKNIFTY" else NIFTY_STRIKE_INTERVAL

        # Breakout above high → BUY CE
        if spot_price > high:
            # Pick ATM or 1 strike OTM call
            atm_strike = round(spot_price / interval) * interval
            target_strike = atm_strike  # ATM for stronger premium move

            # Find premium from chain
            premium = self._find_premium(option_chain, "CE", target_strike)
            if premium <= 0:
                return self._hold(index, "No CE premium data")

            # Strength based on how decisively it broke out
            breakout_pct = (spot_price - high) / range_size
            strength = min(0.4 + breakout_pct, 0.9)

            self._triggered_today[index] = True
            return self._buy_ce(
                index, target_strike, strength,
                f"ORB breakout UP (range {low:.0f}-{high:.0f}, break by {spot_price - high:.0f})",
                premium
            )

        # Breakdown below low → BUY PE
        if spot_price < low:
            atm_strike = round(spot_price / interval) * interval
            target_strike = atm_strike

            premium = self._find_premium(option_chain, "PE", target_strike)
            if premium <= 0:
                return self._hold(index, "No PE premium data")

            breakout_pct = (low - spot_price) / range_size
            strength = min(0.4 + breakout_pct, 0.9)

            self._triggered_today[index] = True
            return self._buy_pe(
                index, target_strike, strength,
                f"ORB breakdown DOWN (range {low:.0f}-{high:.0f}, break by {low - spot_price:.0f})",
                premium
            )

        return self._hold(index, f"Inside range ({low:.0f} < {spot_price:.0f} < {high:.0f})")

    def _candle_time(self, candle: dict) -> int:
        """Extract HHMM from candle timestamp."""
        ts = candle.get("timestamp", "")
        if isinstance(ts, datetime):
            return ts.hour * 100 + ts.minute
        try:
            dt = datetime.fromisoformat(str(ts))
            return dt.hour * 100 + dt.minute
        except Exception:
            return 0

    def _find_premium(self, chain: dict, opt_type: str, strike: int) -> float:
        for item in chain.get(opt_type, []):
            if item["strike"] == strike:
                return item.get("premium", 0)
        return 0
