"""
Angel One SmartAPI Broker Client
---------------------------------
Handles login, market data, option chain, and order placement.
Paper trading simulates everything locally.
"""

import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pyotp

from config import (
    ANGEL_API_KEY,
    ANGEL_CLIENT_ID,
    ANGEL_PASSWORD,
    ANGEL_TOTP_SECRET,
    TRADING_MODE,
    STARTING_CAPITAL,
    DATA_DIR,
    LOT_SIZES,
    BANKNIFTY_STRIKE_INTERVAL,
    NIFTY_STRIKE_INTERVAL,
)

logger = logging.getLogger("broker")

# IST timezone offset
IST = timezone(timedelta(hours=5, minutes=30))


class PaperTrader:
    """Simulated broker for paper trading."""

    _PATH = DATA_DIR / "paper_account.json"

    def __init__(self):
        self.capital = STARTING_CAPITAL
        self.positions: list[dict] = []
        self.closed_trades: list[dict] = []
        self.order_id = 0
        self._load()

    def _load(self):
        if self._PATH.exists():
            d = json.loads(self._PATH.read_text())
            self.capital = d.get("capital", self.capital)
            self.positions = d.get("positions", [])
            self.closed_trades = d.get("closed_trades", [])
            self.order_id = d.get("order_id", 0)

    def save(self):
        self._PATH.write_text(json.dumps({
            "capital": round(self.capital, 2),
            "positions": self.positions,
            "closed_trades": self.closed_trades,
            "order_id": self.order_id,
        }, indent=2, default=str))

    def buy_option(self, symbol: str, strike: int, option_type: str,
                   premium: float, lot_size: int, qty_lots: int) -> dict:
        total_qty = lot_size * qty_lots
        cost = premium * total_qty
        if cost > self.capital:
            raise ValueError(f"Insufficient capital: need ₹{cost:.0f}, have ₹{self.capital:.0f}")

        self.capital -= cost
        self.order_id += 1
        pos = {
            "id": self.order_id,
            "symbol": symbol,
            "strike": strike,
            "option_type": option_type,
            "entry_premium": premium,
            "current_premium": premium,
            "lot_size": lot_size,
            "qty_lots": qty_lots,
            "total_qty": total_qty,
            "cost": round(cost, 2),
            "entry_time": datetime.now(IST).isoformat(),
            "status": "open",
        }
        self.positions.append(pos)
        self.save()
        logger.info("PAPER BUY %s %s%s @ ₹%.1f x %d = ₹%.0f",
                     symbol, strike, option_type, premium, total_qty, cost)
        return pos

    def sell_option(self, position_id: int, exit_premium: float) -> dict:
        pos = None
        for p in self.positions:
            if p["id"] == position_id and p["status"] == "open":
                pos = p
                break
        if pos is None:
            raise ValueError(f"Position {position_id} not found or already closed")

        revenue = exit_premium * pos["total_qty"]
        pnl = revenue - pos["cost"]
        self.capital += revenue

        pos["status"] = "closed"
        pos["exit_premium"] = exit_premium
        pos["exit_time"] = datetime.now(IST).isoformat()
        pos["pnl"] = round(pnl, 2)
        pos["pnl_pct"] = round((exit_premium - pos["entry_premium"]) / pos["entry_premium"] * 100, 1)

        self.closed_trades.append(pos)
        self.positions = [p for p in self.positions if p["status"] == "open"]
        self.save()

        logger.info("PAPER SELL %s %s%s @ ₹%.1f | PnL: ₹%.0f (%.1f%%)",
                     pos["symbol"], pos["strike"], pos["option_type"],
                     exit_premium, pnl, pos["pnl_pct"])
        return pos

    def get_open_positions(self) -> list[dict]:
        return [p for p in self.positions if p["status"] == "open"]

    def get_capital(self) -> float:
        return self.capital

    def get_portfolio_value(self) -> float:
        return self.capital + sum(p["current_premium"] * p["total_qty"] for p in self.get_open_positions())


class BrokerClient:
    """Unified broker client for Angel One (live) and paper trading."""

    def __init__(self):
        self.mode = TRADING_MODE
        self._smart_api = None
        self._paper = PaperTrader() if self.mode == "paper" else None
        self._token_map: dict = {}  # symbol -> token mapping

        if self.mode == "live":
            self._login()

        logger.info("Broker initialized in %s mode", self.mode.upper())

    def _login(self):
        """Login to Angel One SmartAPI."""
        try:
            from SmartApi import SmartConnect
            self._smart_api = SmartConnect(api_key=ANGEL_API_KEY)
            totp = pyotp.TOTP(ANGEL_TOTP_SECRET).now()
            data = self._smart_api.generateSession(ANGEL_CLIENT_ID, ANGEL_PASSWORD, totp)
            if data["status"]:
                self._auth_token = data["data"]["jwtToken"]
                self._refresh_token = data["data"]["refreshToken"]
                self._feed_token = self._smart_api.getfeedToken()
                logger.info("Angel One login successful for %s", ANGEL_CLIENT_ID)
            else:
                raise ConnectionError(f"Login failed: {data.get('message', 'unknown error')}")
        except ImportError:
            raise ImportError("Install smartapi-python: pip install smartapi-python")

    def _get_ltp(self, exchange: str, symbol_token: str) -> float:
        """Get last traded price."""
        if self.mode == "live" and self._smart_api:
            data = self._smart_api.ltpData(exchange, symbol_token, symbol_token)
            return float(data["data"]["ltp"])
        return 0.0

    # ── Spot price (for determining strikes) ──

    def get_spot_price(self, index: str) -> float:
        """Get current spot price of NIFTY/BANKNIFTY."""
        if self.mode == "paper":
            # In paper mode, fetch from NSE or use a free API
            return self._fetch_spot_free(index)

        if self.mode == "live" and self._smart_api:
            tokens = {"NIFTY": "99926000", "BANKNIFTY": "99926009"}
            token = tokens.get(index, "99926000")
            data = self._smart_api.ltpData("NSE", token, token)
            return float(data["data"]["ltp"])

        return 0.0

    def _fetch_spot_free(self, index: str) -> float:
        """Fetch spot price from free NSE data."""
        import requests
        try:
            url = "https://www.nseindia.com/api/allIndices"
            headers = {
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/json",
            }
            session = requests.Session()
            # NSE requires a cookie first
            session.get("https://www.nseindia.com", headers=headers, timeout=5)
            resp = session.get(url, headers=headers, timeout=5)
            if resp.status_code == 200:
                for item in resp.json().get("data", []):
                    idx_name = "NIFTY 50" if index == "NIFTY" else "NIFTY BANK"
                    if item.get("index") == idx_name:
                        return float(item["last"])
        except Exception as e:
            logger.warning("NSE fetch failed: %s", e)

        # Fallback: approximate values (will be overridden by live data)
        fallbacks = {"NIFTY": 23500, "BANKNIFTY": 50000}
        return fallbacks.get(index, 23500)

    # ── Option chain ──

    def get_option_chain(self, index: str, spot_price: float, num_strikes: int = 5) -> dict:
        """
        Get nearby strikes and their premiums.
        Returns: {"CE": [{strike, premium, token}, ...], "PE": [...]}
        """
        interval = BANKNIFTY_STRIKE_INTERVAL if index == "BANKNIFTY" else NIFTY_STRIKE_INTERVAL
        atm_strike = round(spot_price / interval) * interval

        strikes = []
        for i in range(-num_strikes, num_strikes + 1):
            strikes.append(atm_strike + i * interval)

        chain = {"CE": [], "PE": [], "atm_strike": atm_strike, "spot": spot_price}

        if self.mode == "paper":
            # Simulate option premiums using a simple model
            for strike in strikes:
                for opt_type in ["CE", "PE"]:
                    premium = self._simulate_premium(spot_price, strike, opt_type, index)
                    chain[opt_type].append({
                        "strike": strike,
                        "premium": round(premium, 1),
                        "token": f"PAPER_{index}_{strike}{opt_type}",
                    })
        elif self.mode == "live" and self._smart_api:
            # Use SmartAPI to get real option chain
            try:
                data = self._smart_api.optionGreek({
                    "name": index,
                    "expirydate": self._get_nearest_expiry(index),
                })
                if data.get("data"):
                    for item in data["data"]:
                        s = int(item.get("strikePrice", 0))
                        if s in strikes:
                            for opt_type in ["CE", "PE"]:
                                key = "call" if opt_type == "CE" else "put"
                                if item.get(key):
                                    chain[opt_type].append({
                                        "strike": s,
                                        "premium": float(item[key].get("ltp", 0)),
                                        "token": item[key].get("symbolToken", ""),
                                        "iv": float(item[key].get("impliedVolatility", 0)),
                                        "delta": float(item[key].get("delta", 0)),
                                        "oi": int(item[key].get("openInterest", 0)),
                                    })
            except Exception as e:
                logger.warning("Option chain fetch failed: %s", e)

        return chain

    def _simulate_premium(self, spot: float, strike: int, opt_type: str, index: str) -> float:
        """Simple Black-Scholes-like approximation for paper trading."""
        import math
        diff = spot - strike
        if opt_type == "PE":
            diff = -diff

        # Intrinsic value
        intrinsic = max(diff, 0)

        # Time value (rough approximation assuming ~2 days to expiry)
        atm_premium = spot * 0.012 if index == "BANKNIFTY" else spot * 0.008
        distance_pct = abs(spot - strike) / spot
        time_value = atm_premium * math.exp(-5 * distance_pct)

        return max(intrinsic + time_value, 1.0)  # minimum ₹1

    def _get_nearest_expiry(self, index: str) -> str:
        """Get nearest weekly expiry date string."""
        from datetime import date
        today = date.today()
        # BankNifty weekly: Wednesday, Nifty weekly: Thursday
        expiry_day = 2 if index == "BANKNIFTY" else 3  # 0=Mon
        days_ahead = expiry_day - today.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        expiry = today + timedelta(days=days_ahead)
        return expiry.strftime("%d%b%Y").upper()

    # ── Order placement ──

    def buy_option(self, index: str, strike: int, option_type: str,
                   premium: float, qty_lots: int = 1) -> dict:
        lot_size = LOT_SIZES.get(index, 15)

        if self.mode == "paper":
            return self._paper.buy_option(index, strike, option_type, premium, lot_size, qty_lots)

        if self.mode == "live" and self._smart_api:
            symbol = f"{index}{self._get_nearest_expiry(index)}{strike}{option_type}"
            order = self._smart_api.placeOrder({
                "variety": "NORMAL",
                "tradingsymbol": symbol,
                "symboltoken": "",  # needs token lookup
                "transactiontype": "BUY",
                "exchange": "NFO",
                "ordertype": "MARKET",
                "producttype": "INTRADAY",
                "duration": "DAY",
                "quantity": str(lot_size * qty_lots),
            })
            return order

        return {}

    def sell_option(self, position_id: int, exit_premium: float) -> dict:
        if self.mode == "paper":
            return self._paper.sell_option(position_id, exit_premium)
        # Live: would use SmartAPI order placement
        return {}

    # ── Account info ──

    def get_capital(self) -> float:
        if self.mode == "paper":
            return self._paper.get_capital()
        if self._smart_api:
            try:
                rms = self._smart_api.rmsLimit()
                return float(rms["data"].get("availablecash", 0))
            except Exception:
                return 0.0
        return 0.0

    def get_portfolio_value(self) -> float:
        if self.mode == "paper":
            return self._paper.get_portfolio_value()
        return self.get_capital()

    def get_open_positions(self) -> list[dict]:
        if self.mode == "paper":
            return self._paper.get_open_positions()
        return []

    def get_closed_trades(self, limit: int = 50) -> list[dict]:
        if self.mode == "paper":
            return self._paper.closed_trades[-limit:]
        return []

    def update_position_premium(self, position_id: int, current_premium: float):
        """Update live premium for a paper position."""
        if self._paper:
            for p in self._paper.positions:
                if p["id"] == position_id:
                    p["current_premium"] = current_premium
            self._paper.save()
