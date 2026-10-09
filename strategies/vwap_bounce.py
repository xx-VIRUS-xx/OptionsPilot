"""
VWAP Bounce Strategy
--------------------
Uses Volume Weighted Average Price as dynamic support/resistance.

Logic:
1. Calculate VWAP from intraday candles
2. Price bouncing UP from VWAP → BUY CE (using VWAP as support)
3. Price bouncing DOWN from VWAP → BUY PE (using VWAP as resistance)
4. Confirm with candle pattern (rejection wick / engulfing)

Why it works:
- VWAP is where institutions are positioned
- Bounces from VWAP have high probability
- Premium moves are quick on VWAP tests
"""

import logging
from datetime import datetime, timezone, timedelta

from strategies.base import BaseStrategy, TradeSignal, Signal
from config import BANKNIFTY_STRIKE_INTERVAL, NIFTY_STRIKE_INTERVAL

logger = logging.getLogger("vwap")
IST = timezone(timedelta(hours=5, minutes=30))


class VWAPBounceStrategy(BaseStrategy):
    name = "vwap_bounce"

    def analyze(self, index: str, spot_price: float, option_chain: dict,
                candles_5m: list[dict], candles_15m: list[dict]) -> TradeSignal:

        if len(candles_5m) < 10:
            return self._hold(index, "Not enough candles for VWAP")

        now = datetime.now(IST)
        hour_min = now.hour * 100 + now.minute
        if hour_min < 945 or hour_min > 1445:
            return self._hold(index, "Outside VWAP window (9:45-14:45)")

        # Calculate VWAP
        vwap = self._calc_vwap(candles_5m)
        if vwap <= 0:
            return self._hold(index, "VWAP calculation failed")

        interval = BANKNIFTY_STRIKE_INTERVAL if index == "BANKNIFTY" else NIFTY_STRIKE_INTERVAL

        # Distance from VWAP (must be near VWAP for a bounce, within 0.15%)
        distance_pct = abs(spot_price - vwap) / vwap * 100
        if distance_pct > 0.15:
            return self._hold(index, f"Too far from VWAP ({distance_pct:.2f}%)")

        last = candles_5m[-1]
        prev = candles_5m[-2]

        # VWAP Bounce UP (support)
        # Price dipped to VWAP and bounced with a green candle
        if (prev["low"] <= vwap <= prev["high"] and      # prev candle touched VWAP
                last["close"] > last["open"] and           # current candle is green
                last["close"] > vwap and                   # closed above VWAP
                prev["close"] <= vwap):                    # came from below/at VWAP

            # Rejection wick bonus (long lower wick = strong rejection)
            body = abs(last["close"] - last["open"])
            lower_wick = min(last["open"], last["close"]) - last["low"]
            has_rejection = lower_wick > body * 1.5

            strength = 0.5 + (0.2 if has_rejection else 0)
            atm = round(spot_price / interval) * interval
            premium = self._find_premium(option_chain, "CE", atm)
            if premium <= 0:
                return self._hold(index, "No CE premium")

            return self._buy_ce(
                index, atm, strength,
                f"VWAP bounce UP (VWAP={vwap:.0f}, rejection={'yes' if has_rejection else 'no'})",
                premium
            )

        # VWAP Bounce DOWN (resistance)
        if (prev["high"] >= vwap >= prev["low"] and
                last["close"] < last["open"] and
                last["close"] < vwap and
                prev["close"] >= vwap):

            body = abs(last["close"] - last["open"])
            upper_wick = last["high"] - max(last["open"], last["close"])
            has_rejection = upper_wick > body * 1.5

            strength = 0.5 + (0.2 if has_rejection else 0)
            atm = round(spot_price / interval) * interval
            premium = self._find_premium(option_chain, "PE", atm)
            if premium <= 0:
                return self._hold(index, "No PE premium")

            return self._buy_pe(
                index, atm, strength,
                f"VWAP bounce DOWN (VWAP={vwap:.0f}, rejection={'yes' if has_rejection else 'no'})",
                premium
            )

        return self._hold(index, f"Near VWAP but no clear bounce (VWAP={vwap:.0f})")

    def _calc_vwap(self, candles: list[dict]) -> float:
        """VWAP = Σ(Typical Price × Volume) / Σ(Volume)"""
        cum_tv = 0.0
        cum_vol = 0.0
        for c in candles:
            typical = (c["high"] + c["low"] + c["close"]) / 3
            vol = c.get("volume", 1)
            cum_tv += typical * vol
            cum_vol += vol
        return cum_tv / cum_vol if cum_vol > 0 else 0

    def _find_premium(self, chain: dict, opt_type: str, strike: int) -> float:
        for item in chain.get(opt_type, []):
            if item["strike"] == strike:
                return item.get("premium", 0)
        return 0
