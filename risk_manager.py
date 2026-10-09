"""
Risk Manager — Options Edition
--------------------------------
Enforces position sizing, SL/TP, daily loss limits, trailing stops.
Designed for options buying with ₹5K capital.
"""

import json
import logging
from datetime import datetime, timezone, timedelta

from config import (
    MAX_RISK_PER_TRADE_PCT,
    MAX_TRADES_PER_DAY,
    MAX_LOSS_PER_DAY_PCT,
    STOP_LOSS_PCT,
    TARGET_PCT,
    TRAILING_SL_PCT,
    LOT_SIZES,
    DATA_DIR,
)

logger = logging.getLogger("risk")
IST = timezone(timedelta(hours=5, minutes=30))


class RiskManager:
    _PATH = DATA_DIR / "risk_state.json"

    def __init__(self):
        self.trades_today = 0
        self.pnl_today = 0.0
        self.peak_premium: dict[int, float] = {}  # position_id → highest premium seen
        self._today_str = ""
        self._load()

    def _load(self):
        if self._PATH.exists():
            d = json.loads(self._PATH.read_text())
            self.trades_today = d.get("trades_today", 0)
            self.pnl_today = d.get("pnl_today", 0.0)
            self.peak_premium = {int(k): v for k, v in d.get("peak_premium", {}).items()}
            self._today_str = d.get("today", "")

    def _save(self):
        self._PATH.write_text(json.dumps({
            "trades_today": self.trades_today,
            "pnl_today": round(self.pnl_today, 2),
            "peak_premium": self.peak_premium,
            "today": self._today_str,
        }, indent=2))

    def _reset_if_new_day(self, capital: float):
        today = datetime.now(IST).strftime("%Y-%m-%d")
        if today != self._today_str:
            self.trades_today = 0
            self.pnl_today = 0.0
            self.peak_premium.clear()
            self._today_str = today
            self._save()

    # ── Pre-trade checks ──

    def can_trade(self, capital: float) -> tuple[bool, str]:
        self._reset_if_new_day(capital)

        if self.trades_today >= MAX_TRADES_PER_DAY:
            return False, f"Max trades reached ({MAX_TRADES_PER_DAY}/day)"

        max_loss = capital * (MAX_LOSS_PER_DAY_PCT / 100)
        if self.pnl_today < -max_loss:
            return False, f"Daily loss limit hit (PnL=₹{self.pnl_today:.0f}, limit=-₹{max_loss:.0f})"

        return True, "OK"

    def calculate_position_size(self, capital: float, signal_strength: float) -> float:
        """Return INR amount to risk on this trade."""
        max_alloc = capital * (MAX_RISK_PER_TRADE_PCT / 100)
        return max_alloc * max(signal_strength, 0.3)

    def can_afford_lot(self, index: str, premium: float, capital: float) -> tuple[bool, int]:
        """Check if we can afford at least 1 lot. Returns (can_afford, qty_lots)."""
        lot_size = LOT_SIZES.get(index, 15)
        cost_per_lot = premium * lot_size
        max_spend = capital * (MAX_RISK_PER_TRADE_PCT / 100)

        if cost_per_lot > max_spend:
            return False, 0

        qty_lots = max(int(max_spend / cost_per_lot), 1)
        return True, qty_lots

    def record_trade(self):
        self.trades_today += 1
        self._save()

    def record_pnl(self, pnl: float):
        self.pnl_today += pnl
        self._save()

    # ── SL / TP / Trailing SL ──

    def check_exit(self, position_id: int, entry_premium: float,
                   current_premium: float) -> tuple[str | None, str]:
        """
        Check if position should be exited.
        Returns: (trigger_type, reason) or (None, "")
        trigger_type: "stop_loss", "target", "trailing_sl"
        """
        # Track peak premium for trailing SL
        prev_peak = self.peak_premium.get(position_id, entry_premium)
        if current_premium > prev_peak:
            self.peak_premium[position_id] = current_premium
            self._save()
        peak = self.peak_premium.get(position_id, entry_premium)

        pnl_pct = (current_premium - entry_premium) / entry_premium * 100

        # Stop loss
        if pnl_pct <= -STOP_LOSS_PCT:
            return "stop_loss", f"SL hit ({pnl_pct:.1f}% loss)"

        # Target
        if pnl_pct >= TARGET_PCT:
            return "target", f"Target hit ({pnl_pct:.1f}% gain)"

        # Trailing SL: only after 30%+ gain, trail from peak
        if peak > entry_premium * 1.3:
            trail_level = peak * (1 - TRAILING_SL_PCT / 100)
            if current_premium <= trail_level:
                locked_pct = (current_premium - entry_premium) / entry_premium * 100
                return "trailing_sl", f"Trailing SL (peak=₹{peak:.0f}, locked {locked_pct:.1f}%)"

        return None, ""

    def clear_position(self, position_id: int):
        self.peak_premium.pop(position_id, None)
        self._save()

    def get_daily_stats(self) -> dict:
        return {
            "trades_today": self.trades_today,
            "pnl_today": round(self.pnl_today, 2),
        }
