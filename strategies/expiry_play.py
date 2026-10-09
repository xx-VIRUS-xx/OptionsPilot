"""
Expiry Day Strategy
--------------------
Exploits the unique dynamics of weekly expiry (Thursday for Nifty, Wed for BankNifty).

Logic:
- On expiry day, ATM premiums decay rapidly (theta crush)
- But big directional moves can 5-10x OTM options in minutes
- Buy slightly OTM options cheaply (₹10-50 range) if a breakout begins
- High risk / high reward — only with a small portion of capital

Key rules:
1. Only active on expiry days
2. Buy cheap OTM options (₹10-50)
3. Use tight SL (50%) but let winners run (200-500% target)
4. Maximum 1-2 trades on expiry
"""

import logging
from datetime import datetime, timezone, timedelta, date

from strategies.base import BaseStrategy, TradeSignal, Signal
from config import BANKNIFTY_STRIKE_INTERVAL, NIFTY_STRIKE_INTERVAL

logger = logging.getLogger("expiry")
IST = timezone(timedelta(hours=5, minutes=30))


class ExpiryDayStrategy(BaseStrategy):
    name = "expiry_play"

    def __init__(self, max_premium: float = 50, min_premium: float = 5):
        self.max_premium = max_premium
        self.min_premium = min_premium

    def _is_expiry_day(self, index: str) -> bool:
        today = date.today()
        weekday = today.weekday()  # 0=Mon
        # BankNifty: Wednesday (2), Nifty: Thursday (3)
        if index == "BANKNIFTY":
            return weekday == 2
        elif index == "NIFTY":
            return weekday == 3
        return False

    def analyze(self, index: str, spot_price: float, option_chain: dict,
                candles_5m: list[dict], candles_15m: list[dict]) -> TradeSignal:

        if not self._is_expiry_day(index):
            return self._hold(index, "Not expiry day")

        now = datetime.now(IST)
        hour_min = now.hour * 100 + now.minute

        # Active window: 10:00 - 14:00 (not too early, not too late)
        if hour_min < 1000 or hour_min > 1400:
            return self._hold(index, "Outside expiry play window (10:00-14:00)")

        if len(candles_5m) < 15:
            return self._hold(index, "Not enough data")

        interval = BANKNIFTY_STRIKE_INTERVAL if index == "BANKNIFTY" else NIFTY_STRIKE_INTERVAL

        # Look for a strong directional move forming
        recent_5 = candles_5m[-5:]
        total_move = recent_5[-1]["close"] - recent_5[0]["open"]
        avg_range = sum(c["high"] - c["low"] for c in candles_5m[-20:]) / 20

        is_strong_up = total_move > avg_range * 2
        is_strong_down = total_move < -avg_range * 2

        if not (is_strong_up or is_strong_down):
            return self._hold(index, f"No strong expiry move (move={total_move:.0f})")

        # Find cheap OTM option
        if is_strong_up:
            # Buy OTM CE (1-2 strikes above ATM)
            atm = round(spot_price / interval) * interval
            target_strike = atm + interval  # 1 strike OTM

            premium = self._find_cheap_option(option_chain, "CE", target_strike)
            if premium is None:
                return self._hold(index, "No cheap CE found")

            return self._buy_ce(
                index, target_strike, 0.6,
                f"Expiry breakout UP (move={total_move:.0f}, cheap OTM @ ₹{premium:.0f})",
                premium
            )

        if is_strong_down:
            atm = round(spot_price / interval) * interval
            target_strike = atm - interval

            premium = self._find_cheap_option(option_chain, "PE", target_strike)
            if premium is None:
                return self._hold(index, "No cheap PE found")

            return self._buy_pe(
                index, target_strike, 0.6,
                f"Expiry breakdown DOWN (move={total_move:.0f}, cheap OTM @ ₹{premium:.0f})",
                premium
            )

        return self._hold(index, "No expiry signal")

    def _find_cheap_option(self, chain: dict, opt_type: str, preferred_strike: int) -> float | None:
        """Find an option in the ₹5-50 range near the preferred strike."""
        candidates = []
        for item in chain.get(opt_type, []):
            p = item.get("premium", 0)
            if self.min_premium <= p <= self.max_premium:
                candidates.append(item)

        if not candidates:
            return None

        # Prefer the one closest to preferred strike
        candidates.sort(key=lambda x: abs(x["strike"] - preferred_strike))
        best = candidates[0]
        return best["premium"]
