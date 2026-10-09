"""
Goal Tracker — ₹5,000 → ₹1 Crore
"""

import json
import math
import logging
from datetime import datetime, timezone, timedelta, date

from config import GOAL_AMOUNT, STARTING_CAPITAL, DATA_DIR

logger = logging.getLogger("goal")
IST = timezone(timedelta(hours=5, minutes=30))

# Trading days per year in India (NSE)
TRADING_DAYS_PER_YEAR = 250


class GoalTracker:
    _PATH = DATA_DIR / "goal_state.json"

    def __init__(self):
        self.snapshots: list[dict] = []
        self._load()

    def _load(self):
        if self._PATH.exists():
            d = json.loads(self._PATH.read_text())
            self.snapshots = d.get("snapshots", [])

    def _save(self):
        self._PATH.write_text(json.dumps({"snapshots": self.snapshots}, indent=2))

    def record(self, capital: float):
        today = datetime.now(IST).strftime("%Y-%m-%d")
        # One snapshot per day
        if self.snapshots and self.snapshots[-1].get("date") == today:
            self.snapshots[-1]["capital"] = round(capital, 2)
        else:
            self.snapshots.append({"date": today, "capital": round(capital, 2)})
        if len(self.snapshots) > 400:
            self.snapshots = self.snapshots[-400:]
        self._save()

    def get_progress(self, capital: float) -> dict:
        progress_pct = (capital / GOAL_AMOUNT) * 100

        # Trading days left in 2026
        today = date.today()
        end_2026 = date(2026, 12, 31)
        cal_days_left = max((end_2026 - today).days, 1)
        trading_days_left = int(cal_days_left * TRADING_DAYS_PER_YEAR / 365)

        # Required daily return (compound)
        if capital > 0 and capital < GOAL_AMOUNT:
            req_daily = (math.exp(math.log(GOAL_AMOUNT / capital) / trading_days_left) - 1) * 100
        else:
            req_daily = 0

        # Actual average daily return
        daily_returns = []
        for i in range(1, min(len(self.snapshots), 31)):
            prev = self.snapshots[-(i + 1)]["capital"]
            curr = self.snapshots[-i]["capital"]
            if prev > 0:
                daily_returns.append((curr - prev) / prev * 100)
        avg_daily = sum(daily_returns) / len(daily_returns) if daily_returns else 0

        # Win/loss days
        win_days = sum(1 for r in daily_returns if r > 0)
        loss_days = sum(1 for r in daily_returns if r < 0)

        # Projected days to goal
        if avg_daily > 0 and capital < GOAL_AMOUNT:
            proj_days = math.log(GOAL_AMOUNT / capital) / math.log(1 + avg_daily / 100)
        else:
            proj_days = float("inf")

        # Growth since start
        growth_x = capital / STARTING_CAPITAL if STARTING_CAPITAL > 0 else 0

        return {
            "capital": round(capital, 2),
            "goal": GOAL_AMOUNT,
            "progress_pct": round(progress_pct, 3),
            "remaining": round(GOAL_AMOUNT - capital, 2),
            "trading_days_left": trading_days_left,
            "required_daily_pct": round(req_daily, 2),
            "avg_daily_pct": round(avg_daily, 2),
            "projected_days": round(proj_days) if proj_days != float("inf") else "N/A",
            "on_track": avg_daily >= req_daily if req_daily > 0 else False,
            "growth_x": round(growth_x, 1),
            "win_days": win_days,
            "loss_days": loss_days,
        }

    def format_progress(self, capital: float) -> str:
        p = self.get_progress(capital)
        bar_len = 20
        filled = int(bar_len * min(p["progress_pct"] / 100, 1.0))
        bar = "█" * filled + "░" * (bar_len - filled)

        # Milestones for small account
        milestones = [
            (10_000, "₹10K"), (25_000, "₹25K"), (50_000, "₹50K"),
            (1_00_000, "₹1L"), (5_00_000, "₹5L"), (10_00_000, "₹10L"),
            (25_00_000, "₹25L"), (50_00_000, "₹50L"), (1_00_00_000, "₹1Cr"),
        ]
        next_ms = ""
        for target, label in milestones:
            if capital < target:
                pct = capital / target * 100
                next_ms = f"🏁 Next milestone: {label} ({pct:.0f}% there)"
                break

        status = "✅ ON TRACK" if p["on_track"] else "⚠️  BEHIND"

        return (
            f"🎯 GOAL: ₹1,00,00,000 (₹1 Cr)\n"
            f"[{bar}] {p['progress_pct']:.3f}%\n\n"
            f"💰 Capital: ₹{capital:,.0f} ({p['growth_x']}x from ₹{STARTING_CAPITAL:,.0f})\n"
            f"📊 Remaining: ₹{p['remaining']:,.0f}\n"
            f"📅 Trading days left: {p['trading_days_left']}\n"
            f"{next_ms}\n\n"
            f"📈 Need: {p['required_daily_pct']:.2f}%/day\n"
            f"📉 Actual: {p['avg_daily_pct']:.2f}%/day\n"
            f"📆 Win days: {p['win_days']} | Loss days: {p['loss_days']}\n"
            f"⏱️  Projected: {p['projected_days']} trading days\n\n"
            f"{status}"
        )
