from strategies.base import BaseStrategy, Signal, TradeSignal
from strategies.orb import ORBStrategy
from strategies.momentum_scalp import MomentumScalpStrategy
from strategies.vwap_bounce import VWAPBounceStrategy
from strategies.expiry_play import ExpiryDayStrategy

ALL_STRATEGIES = {
    "orb": ORBStrategy,
    "momentum_scalp": MomentumScalpStrategy,
    "vwap_bounce": VWAPBounceStrategy,
    "expiry_play": ExpiryDayStrategy,
}
