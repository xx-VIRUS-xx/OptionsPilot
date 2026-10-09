"""
Momentum Scalp Strategy
------------------------
Quick directional trades based on strong candle momentum + RSI.

Logic:
1. Detect 3+ consecutive green/red 5m candles with increasing volume
2. RSI confirming direction (>60 for calls, <40 for puts)
3. Buy ATM option, ride the momentum, quick exit

Best for: Strong trending sessions (budget day, RBI policy, global events)
"""

import logging
from datetime import datetime, timezone, timedelta

from strategies.base import BaseStrategy, TradeSignal, Signal
from config import BANKNIFTY_STRIKE_INTERVAL, NIFTY_STRIKE_INTERVAL

logger = logging.getLogger("momentum")
IST = timezone(timedelta(hours=5, minutes=30))


class MomentumScalpStrategy(BaseStrategy):
    name = "momentum_scalp"

    def __init__(self, consec_candles: int = 3, rsi_period: int = 14):
        self.consec_candles = consec_candles
        self.rsi_period = rsi_period

    def analyze(self, index: str, spot_price: float, option_chain: dict,
                candles_5m: list[dict], candles_15m: list[dict]) -> TradeSignal:

        if len(candles_5m) < self.rsi_period + 5:
            return self._hold(index, "Not enough 5m candles")

        now = datetime.now(IST)
        hour_min = now.hour * 100 + now.minute
        if hour_min < 935 or hour_min > 1445:
            return self._hold(index, "Outside momentum window")

        closes = [c["close"] for c in candles_5m]

        # RSI calculation
        rsi = self._calc_rsi(closes, self.rsi_period)
        if rsi is None:
            return self._hold(index, "RSI calculation failed")

        # Check consecutive candle direction
        recent = candles_5m[-self.consec_candles:]
        all_green = all(c["close"] > c["open"] for c in recent)
        all_red = all(c["close"] < c["open"] for c in recent)

        # Check increasing body size (momentum building)
        bodies = [abs(c["close"] - c["open"]) for c in recent]
        momentum_building = all(bodies[i] >= bodies[i - 1] * 0.8 for i in range(1, len(bodies)))

        # Total move in the consecutive candles
        total_move = abs(recent[-1]["close"] - recent[0]["open"])
        avg_candle_range = sum(c["high"] - c["low"] for c in candles_5m[-20:]) / 20
        strong_move = total_move > avg_candle_range * 1.5

        interval = BANKNIFTY_STRIKE_INTERVAL if index == "BANKNIFTY" else NIFTY_STRIKE_INTERVAL

        # BULLISH: 3+ green candles + RSI > 60 + momentum building
        if all_green and rsi > 60 and momentum_building and strong_move:
            atm_strike = round(spot_price / interval) * interval
            premium = self._find_premium(option_chain, "CE", atm_strike)
            if premium <= 0:
                return self._hold(index, "No CE premium")

            strength = min(0.3 + (rsi - 60) / 60 + (0.2 if strong_move else 0), 0.85)
            return self._buy_ce(
                index, atm_strike, strength,
                f"Bullish momentum ({self.consec_candles} green, RSI={rsi:.0f}, move={total_move:.0f})",
                premium
            )

        # BEARISH: 3+ red candles + RSI < 40 + momentum building
        if all_red and rsi < 40 and momentum_building and strong_move:
            atm_strike = round(spot_price / interval) * interval
            premium = self._find_premium(option_chain, "PE", atm_strike)
            if premium <= 0:
                return self._hold(index, "No PE premium")

            strength = min(0.3 + (40 - rsi) / 60 + (0.2 if strong_move else 0), 0.85)
            return self._buy_pe(
                index, atm_strike, strength,
                f"Bearish momentum ({self.consec_candles} red, RSI={rsi:.0f}, move={total_move:.0f})",
                premium
            )

        return self._hold(index, f"No clear momentum (RSI={rsi:.0f})")

    def _calc_rsi(self, closes: list[float], period: int) -> float | None:
        if len(closes) < period + 1:
            return None
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    def _find_premium(self, chain: dict, opt_type: str, strike: int) -> float:
        for item in chain.get(opt_type, []):
            if item["strike"] == strike:
                return item.get("premium", 0)
        return 0
