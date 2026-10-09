"""
Telegram Notifier
"""

import logging
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger("notifier")


class Notifier:
    def __init__(self):
        self.enabled = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)

    def send(self, message: str, silent: bool = False):
        logger.info("[NOTIFY] %s", message)
        if self.enabled:
            try:
                url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
                requests.post(url, json={
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": message,
                    "parse_mode": "Markdown",
                    "disable_notification": silent,
                }, timeout=10)
            except Exception as e:
                logger.warning("Telegram error: %s", e)

    def trade_entry(self, opt_type: str, index: str, strike: int, premium: float,
                    qty: int, cost: float, strategy: str, mode: str):
        tag = "📝 PAPER" if mode == "paper" else "💰 LIVE"
        emoji = "🟢" if "CE" in opt_type else "🔴"
        self.send(
            f"{emoji} *BUY {index} {strike}{opt_type}*\n"
            f"Premium: `₹{premium:.1f}` × {qty} = `₹{cost:.0f}`\n"
            f"Strategy: {strategy}\n"
            f"Mode: {tag}"
        )

    def trade_exit(self, index: str, strike: int, opt_type: str,
                   entry: float, exit_p: float, pnl: float, trigger: str):
        emoji = "✅" if pnl > 0 else "❌"
        self.send(
            f"{emoji} *EXIT {index} {strike}{opt_type}* ({trigger})\n"
            f"Entry: `₹{entry:.1f}` → Exit: `₹{exit_p:.1f}`\n"
            f"PnL: `₹{pnl:+,.0f}` ({(exit_p-entry)/entry*100:+.1f}%)"
        )

    def daily_summary(self, capital: float, pnl: float, trades: int,
                      goal_pct: float, wins: int, losses: int):
        wr = wins / (wins + losses) * 100 if (wins + losses) > 0 else 0
        self.send(
            f"📊 *Daily Summary*\n"
            f"Capital: `₹{capital:,.0f}`\n"
            f"Today PnL: `₹{pnl:+,.0f}`\n"
            f"Trades: {trades} (W:{wins} L:{losses} WR:{wr:.0f}%)\n"
            f"Goal: `{goal_pct:.2f}%` → ₹1 Cr"
        )

    def bot_started(self, mode: str, strategies: list[str]):
        self.send(
            f"🚀 *Options Bot Started*\n"
            f"Mode: {mode.upper()}\n"
            f"Capital: ₹5,000\n"
            f"Strategies: {', '.join(strategies)}"
        )

    def error_alert(self, error: str):
        self.send(f"⚠️ *ERROR*\n`{error}`")

    def market_closed(self):
        self.send("🔒 Market closed. Bot sleeping until 9:15 AM IST.", silent=True)
