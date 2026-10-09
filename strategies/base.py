"""
Base strategy for options trading.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum


class Signal(Enum):
    BUY_CE = "buy_ce"   # Buy Call
    BUY_PE = "buy_pe"   # Buy Put
    EXIT = "exit"        # Exit position
    HOLD = "hold"        # Do nothing


@dataclass
class TradeSignal:
    signal: Signal
    index: str            # NIFTY / BANKNIFTY
    strike: int           # strike price
    strength: float       # 0.0 to 1.0
    reason: str
    strategy_name: str
    premium: float = 0.0  # suggested entry premium


class BaseStrategy(ABC):
    name: str = "base"

    @abstractmethod
    def analyze(self, index: str, spot_price: float, option_chain: dict,
                candles_5m: list[dict], candles_15m: list[dict]) -> TradeSignal:
        ...

    def _hold(self, index: str, reason: str = "") -> TradeSignal:
        return TradeSignal(Signal.HOLD, index, 0, 0.0, reason, self.name)

    def _buy_ce(self, index: str, strike: int, strength: float, reason: str,
                premium: float = 0) -> TradeSignal:
        return TradeSignal(Signal.BUY_CE, index, strike, min(strength, 1.0),
                           reason, self.name, premium)

    def _buy_pe(self, index: str, strike: int, strength: float, reason: str,
                premium: float = 0) -> TradeSignal:
        return TradeSignal(Signal.BUY_PE, index, strike, min(strength, 1.0),
                           reason, self.name, premium)
