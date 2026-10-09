"""
Auto Income Bot - Options Trading Configuration
"""

import os
from pathlib import Path
from dotenv import load_dotenv

_env_path = Path(__file__).parent / ".env"
load_dotenv(_env_path)


def _float(key: str, default: float) -> float:
    return float(os.getenv(key, str(default)))


def _int(key: str, default: int) -> int:
    return int(os.getenv(key, str(default)))


# ── Broker (Angel One SmartAPI — free) ──
BROKER = os.getenv("BROKER", "angel")
ANGEL_API_KEY = os.getenv("ANGEL_API_KEY", "")
ANGEL_CLIENT_ID = os.getenv("ANGEL_CLIENT_ID", "")
ANGEL_PASSWORD = os.getenv("ANGEL_PASSWORD", "")
ANGEL_TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET", "")

# ── Trading Mode ──
TRADING_MODE = os.getenv("TRADING_MODE", "paper")

# ── Telegram ──
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Instruments ──
INSTRUMENTS = os.getenv("INSTRUMENTS", "BANKNIFTY,NIFTY").split(",")
PREFERRED_EXPIRY = os.getenv("PREFERRED_EXPIRY", "weekly")

# ── Capital & Risk (tuned for ₹5K options buying) ──
STARTING_CAPITAL = _float("STARTING_CAPITAL", 5000)
MAX_RISK_PER_TRADE_PCT = _float("MAX_RISK_PER_TRADE_PCT", 20)
MAX_TRADES_PER_DAY = _int("MAX_TRADES_PER_DAY", 5)
MAX_LOSS_PER_DAY_PCT = _float("MAX_LOSS_PER_DAY_PCT", 30)
STOP_LOSS_PCT = _float("STOP_LOSS_PCT", 30)
TARGET_PCT = _float("TARGET_PCT", 50)
TRAILING_SL_PCT = _float("TRAILING_SL_PCT", 20)

# ── Market Hours IST ──
MARKET_OPEN_HOUR = 9
MARKET_OPEN_MINUTE = 15
MARKET_CLOSE_HOUR = 15
MARKET_CLOSE_MINUTE = 30
NO_ENTRY_AFTER_HOUR = _int("NO_ENTRY_AFTER_HOUR", 14)
NO_ENTRY_AFTER_MINUTE = _int("NO_ENTRY_AFTER_MINUTE", 45)
SQUARE_OFF_HOUR = _int("SQUARE_OFF_HOUR", 15)
SQUARE_OFF_MINUTE = _int("SQUARE_OFF_MINUTE", 15)

# ── Goal ──
GOAL_AMOUNT = _float("GOAL_AMOUNT", 10_000_000)

# ── Dashboard ──
DASHBOARD_PORT = _int("DASHBOARD_PORT", 8080)
DASHBOARD_HOST = os.getenv("DASHBOARD_HOST", "127.0.0.1")

# ── Data/Logs ──
DATA_DIR = Path(__file__).parent / "data"
DATA_DIR.mkdir(exist_ok=True)
LOG_DIR = Path(__file__).parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

# ── Option chain strike interval ──
BANKNIFTY_STRIKE_INTERVAL = 100
NIFTY_STRIKE_INTERVAL = 50

# Lot sizes (SEBI defined)
LOT_SIZES = {
    "BANKNIFTY": 15,  # 15 per lot (post Nov 2024)
    "NIFTY": 25,      # 25 per lot (post Nov 2024)
}
