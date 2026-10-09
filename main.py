"""
Auto Income Bot — Options Trading Orchestrator
================================================
Runs Mon-Fri during NSE market hours (9:15 AM - 3:30 PM IST).
Sleeps outside market hours to save resources.
"""

import logging
import time
import threading
import traceback
from datetime import datetime, timezone, timedelta, date

from apscheduler.schedulers.background import BackgroundScheduler

from logger_setup import setup_logging
from config import (
    INSTRUMENTS, TRADING_MODE,
    MARKET_OPEN_HOUR, MARKET_OPEN_MINUTE,
    MARKET_CLOSE_HOUR, MARKET_CLOSE_MINUTE,
    NO_ENTRY_AFTER_HOUR, NO_ENTRY_AFTER_MINUTE,
    SQUARE_OFF_HOUR, SQUARE_OFF_MINUTE,
    LOT_SIZES,
)
from broker.client import BrokerClient
from strategies import ALL_STRATEGIES
from strategies.base import Signal
from risk_manager import RiskManager
from notifier import Notifier
from goal_tracker import GoalTracker

setup_logging()
logger = logging.getLogger("main")
trade_logger = logging.getLogger("trades")

IST = timezone(timedelta(hours=5, minutes=30))


def _now_ist() -> datetime:
    return datetime.now(IST)


def _is_market_hours() -> bool:
    now = _now_ist()
    if now.weekday() >= 5:  # Sat/Sun
        return False
    market_open = now.replace(hour=MARKET_OPEN_HOUR, minute=MARKET_OPEN_MINUTE, second=0)
    market_close = now.replace(hour=MARKET_CLOSE_HOUR, minute=MARKET_CLOSE_MINUTE, second=0)
    return market_open <= now <= market_close


def _can_enter() -> bool:
    """Check if we're allowed to enter new positions."""
    now = _now_ist()
    cutoff = now.replace(hour=NO_ENTRY_AFTER_HOUR, minute=NO_ENTRY_AFTER_MINUTE, second=0)
    return _is_market_hours() and now < cutoff


def _should_square_off() -> bool:
    now = _now_ist()
    sq = now.replace(hour=SQUARE_OFF_HOUR, minute=SQUARE_OFF_MINUTE, second=0)
    return now >= sq and now.weekday() < 5


class OptionsBot:
    def __init__(self):
        self.broker = BrokerClient()
        self.risk = RiskManager()
        self.notifier = Notifier()
        self.goal = GoalTracker()
        self.strategies = {name: cls() for name, cls in ALL_STRATEGIES.items()}

        # Simulated candle store (for paper mode)
        self._candle_store: dict[str, dict] = {}

    def run_cycle(self):
        """Main cycle — runs every 2 minutes during market hours."""
        if not _is_market_hours():
            return

        try:
            capital = self.broker.get_capital()

            # 1. Check SL/TP on open positions
            self._monitor_positions()

            # 2. Square off if near close
            if _should_square_off():
                self._square_off_all("End of day square off")
                return

            # 3. Look for new entries
            if _can_enter():
                for index in INSTRUMENTS:
                    self._analyze_and_trade(index, capital)

        except Exception as e:
            logger.error("Cycle error: %s\n%s", e, traceback.format_exc())
            self.notifier.error_alert(str(e))

    def _monitor_positions(self):
        """Check SL/TP/Trailing SL on all open positions."""
        for pos in self.broker.get_open_positions():
            try:
                # Get current premium
                spot = self.broker.get_spot_price(pos["symbol"])
                chain = self.broker.get_option_chain(pos["symbol"], spot, num_strikes=3)
                opt_type = pos["option_type"]
                current_premium = self._get_current_premium(chain, opt_type, pos["strike"])

                if current_premium <= 0:
                    continue

                # Update live premium
                self.broker.update_position_premium(pos["id"], current_premium)

                # Check exit conditions
                trigger, reason = self.risk.check_exit(pos["id"], pos["entry_premium"], current_premium)

                if trigger:
                    self._exit_position(pos, current_premium, trigger, reason)

            except Exception as e:
                logger.warning("Monitor failed for position %s: %s", pos["id"], e)

    def _analyze_and_trade(self, index: str, capital: float):
        """Run all strategies on an index."""
        # Pre-trade risk check
        ok, msg = self.risk.can_trade(capital)
        if not ok:
            logger.info("Trade blocked: %s", msg)
            return

        spot = self.broker.get_spot_price(index)
        if spot <= 0:
            return

        chain = self.broker.get_option_chain(index, spot)
        candles_5m = self._get_candles(index, "5m")
        candles_15m = self._get_candles(index, "15m")

        signals = []
        for name, strategy in self.strategies.items():
            try:
                signal = strategy.analyze(index, spot, chain, candles_5m, candles_15m)
                if signal.signal not in (Signal.HOLD, ):
                    signals.append(signal)
                    logger.info("%s | %s → %s %s%s (str=%.2f) %s",
                                index, name, signal.signal.value,
                                signal.strike, "CE" if "CE" in signal.signal.value else "PE",
                                signal.strength, signal.reason)
            except Exception as e:
                logger.warning("Strategy %s failed on %s: %s", name, index, e)

        if not signals:
            return

        # Pick strongest signal
        best = max(signals, key=lambda s: s.strength)

        # Consensus bonus
        same_dir = [s for s in signals if s.signal == best.signal]
        if len(same_dir) > 1:
            best.strength = min(best.strength * 1.3, 1.0)
            best.reason += f" (+{len(same_dir)} agree)"

        self._execute_signal(best, capital)

    def _execute_signal(self, signal, capital: float):
        """Execute an options buy signal."""
        index = signal.index
        opt_type = "CE" if signal.signal == Signal.BUY_CE else "PE"
        strike = signal.strike
        premium = signal.premium

        if premium <= 0:
            return

        # Check if we can afford a lot
        can_afford, qty_lots = self.risk.can_afford_lot(index, premium, capital)
        if not can_afford:
            lot_size = LOT_SIZES.get(index, 15)
            logger.info("Can't afford %s %s%s @ ₹%.1f (need ₹%.0f, have ₹%.0f)",
                        index, strike, opt_type, premium,
                        premium * lot_size, capital)
            return

        # Execute buy
        lot_size = LOT_SIZES.get(index, 15)
        total_qty = lot_size * qty_lots
        cost = premium * total_qty

        order = self.broker.buy_option(index, strike, opt_type, premium, qty_lots)

        self.risk.record_trade()
        self.notifier.trade_entry(opt_type, index, strike, premium, total_qty, cost,
                                  signal.strategy_name, self.broker.mode)
        trade_logger.info(
            "BUY | %s %s%s | premium=%.1f qty=%d cost=%.0f | strat=%s | %s",
            index, strike, opt_type, premium, total_qty, cost,
            signal.strategy_name, signal.reason
        )

    def _exit_position(self, pos: dict, exit_premium: float, trigger: str, reason: str):
        """Exit an open position."""
        result = self.broker.sell_option(pos["id"], exit_premium)
        pnl = (exit_premium - pos["entry_premium"]) * pos["total_qty"]

        self.risk.record_pnl(pnl)
        self.risk.clear_position(pos["id"])

        self.notifier.trade_exit(pos["symbol"], pos["strike"], pos["option_type"],
                                 pos["entry_premium"], exit_premium, pnl, trigger)
        trade_logger.info(
            "EXIT | %s %s%s | entry=%.1f exit=%.1f pnl=%.0f | %s | %s",
            pos["symbol"], pos["strike"], pos["option_type"],
            pos["entry_premium"], exit_premium, pnl, trigger, reason
        )

    def _square_off_all(self, reason: str):
        """Close all positions (end of day)."""
        positions = self.broker.get_open_positions()
        if not positions:
            return

        logger.info("Squaring off %d positions: %s", len(positions), reason)
        for pos in positions:
            try:
                spot = self.broker.get_spot_price(pos["symbol"])
                chain = self.broker.get_option_chain(pos["symbol"], spot, num_strikes=3)
                premium = self._get_current_premium(chain, pos["option_type"], pos["strike"])
                if premium > 0:
                    self._exit_position(pos, premium, "square_off", reason)
            except Exception as e:
                logger.error("Square-off failed for %s: %s", pos["id"], e)

    def _get_current_premium(self, chain: dict, opt_type: str, strike: int) -> float:
        for item in chain.get(opt_type, []):
            if item["strike"] == strike:
                return item.get("premium", 0)
        return 0

    def _get_candles(self, index: str, timeframe: str) -> list[dict]:
        """
        Get intraday candles. In paper mode, generates synthetic candles.
        In live mode, uses broker API.
        """
        if self.broker.mode == "paper":
            return self._generate_paper_candles(index, timeframe)
        # Live: fetch from broker
        return []

    def _generate_paper_candles(self, index: str, timeframe: str) -> list[dict]:
        """Generate realistic synthetic candles for paper trading."""
        import random
        spot = self.broker.get_spot_price(index)
        if spot <= 0:
            return []

        now = _now_ist()
        interval_min = 5 if timeframe == "5m" else 15
        num_candles = 50

        candles = []
        price = spot * (1 - random.uniform(0.001, 0.005))  # start slightly lower

        for i in range(num_candles):
            ts = now - timedelta(minutes=interval_min * (num_candles - i))
            # Random walk with slight mean reversion
            change_pct = random.gauss(0, 0.001)  # 0.1% std dev per candle
            price *= (1 + change_pct)

            high = price * (1 + random.uniform(0.0005, 0.002))
            low = price * (1 - random.uniform(0.0005, 0.002))
            open_p = price * (1 + random.uniform(-0.001, 0.001))
            close_p = price

            candles.append({
                "timestamp": ts,
                "open": round(open_p, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close_p, 2),
                "volume": random.randint(50000, 200000),
            })

        return candles

    def send_daily_summary(self):
        """End-of-day summary."""
        try:
            capital = self.broker.get_portfolio_value()
            stats = self.risk.get_daily_stats()
            progress = self.goal.get_progress(capital)
            self.goal.record(capital)

            closed = self.broker.get_closed_trades(50)
            today_str = _now_ist().strftime("%Y-%m-%d")
            today_trades = [t for t in closed if t.get("exit_time", "").startswith(today_str)]
            wins = sum(1 for t in today_trades if t.get("pnl", 0) > 0)
            losses = sum(1 for t in today_trades if t.get("pnl", 0) <= 0)

            self.notifier.daily_summary(
                capital, stats["pnl_today"], stats["trades_today"],
                progress["progress_pct"], wins, losses
            )
            print("\n" + self.goal.format_progress(capital) + "\n")
        except Exception as e:
            logger.error("Summary error: %s", e)


def main():
    bot = OptionsBot()

    logger.info("=" * 60)
    logger.info("  AUTO INCOME BOT — OPTIONS TRADING")
    logger.info("  Mode: %s", TRADING_MODE.upper())
    logger.info("  Capital: ₹%s", f"{bot.broker.get_capital():,.0f}")
    logger.info("  Instruments: %s", ", ".join(INSTRUMENTS))
    logger.info("  Strategies: %s", ", ".join(ALL_STRATEGIES.keys()))
    logger.info("=" * 60)

    bot.notifier.bot_started(TRADING_MODE, list(ALL_STRATEGIES.keys()))

    scheduler = BackgroundScheduler()

    # Main cycle: every 2 minutes during market hours
    scheduler.add_job(bot.run_cycle, "interval", minutes=2, id="options_cycle",
                      max_instances=1, misfire_grace_time=30)

    # Daily summary at 3:25 PM IST (15:25)
    scheduler.add_job(bot.send_daily_summary, "cron", hour=15, minute=25,
                      timezone=IST, id="daily_summary")

    # Square off at 3:15 PM IST
    scheduler.add_job(lambda: bot._square_off_all("Auto square-off"),
                      "cron", hour=SQUARE_OFF_HOUR, minute=SQUARE_OFF_MINUTE,
                      timezone=IST, id="square_off")

    # Start dashboard
    from dashboard import run_dashboard
    dash_thread = threading.Thread(
        target=run_dashboard,
        args=(bot.broker, bot.risk, bot.goal),
        daemon=True,
    )
    dash_thread.start()
    logger.info("Dashboard: http://127.0.0.1:8080")

    scheduler.start()

    # Run first cycle
    if _is_market_hours():
        bot.run_cycle()
    else:
        logger.info("Market closed. Waiting for 9:15 AM IST Mon-Fri...")
        bot.notifier.market_closed()

    # Show goal progress
    capital = bot.broker.get_portfolio_value()
    print("\n" + bot.goal.format_progress(capital) + "\n")

    try:
        while True:
            time.sleep(60)
            # Log heartbeat every 30 min
            if _now_ist().minute % 30 == 0 and _now_ist().second < 60:
                if _is_market_hours():
                    capital = bot.broker.get_portfolio_value()
                    open_pos = len(bot.broker.get_open_positions())
                    logger.info("♥ Capital=₹%.0f | Positions=%d | PnL=₹%.0f",
                                capital, open_pos, bot.risk.pnl_today)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        scheduler.shutdown()
        logger.info("Bot stopped.")


if __name__ == "__main__":
    main()
