"""
Session Replay Simulator
=========================
Replays the last trading session candle-by-candle through all strategies.
Shows what trades the bot would have taken, P&L, and learning insights.

Usage:
    python3 simulator.py                  # Replay last session
    python3 simulator.py --date 2026-03-20  # Replay specific date
    python3 simulator.py --history         # List cached sessions
    python3 simulator.py --speed fast      # Skip pauses
"""

import argparse
import json
import logging
import math
import sys
import time
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

from config import (
    STARTING_CAPITAL, LOT_SIZES,
    STOP_LOSS_PCT, TARGET_PCT, TRAILING_SL_PCT,
    MAX_RISK_PER_TRADE_PCT, MAX_TRADES_PER_DAY,
    BANKNIFTY_STRIKE_INTERVAL, NIFTY_STRIKE_INTERVAL,
    DATA_DIR,
)
from strategies import ALL_STRATEGIES
from strategies.base import Signal, TradeSignal
from data_scraper import scrape_session, scrape_last_session, list_cached_sessions

logger = logging.getLogger("simulator")
IST = timezone(timedelta(hours=5, minutes=30))

# ── Colors for terminal output ──
class C:
    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    CYAN = "\033[96m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RESET = "\033[0m"
    BLUE = "\033[94m"
    MAGENTA = "\033[95m"


def _bar(pct: float, width: int = 30) -> str:
    filled = int(pct / 100 * width)
    return f"[{'█' * filled}{'░' * (width - filled)}] {pct:.1f}%"


class SimulatedPosition:
    """Tracks a simulated trade during replay."""

    def __init__(self, trade_id: int, index: str, strike: int, opt_type: str,
                 premium: float, lot_size: int, qty_lots: int,
                 entry_candle: int, entry_time: str, strategy: str, reason: str):
        self.id = trade_id
        self.index = index
        self.strike = strike
        self.opt_type = opt_type
        self.entry_premium = premium
        self.current_premium = premium
        self.peak_premium = premium
        self.lot_size = lot_size
        self.qty_lots = qty_lots
        self.total_qty = lot_size * qty_lots
        self.cost = premium * self.total_qty
        self.entry_candle = entry_candle
        self.entry_time = entry_time
        self.strategy = strategy
        self.reason = reason
        self.exit_premium = 0.0
        self.exit_time = ""
        self.exit_trigger = ""
        self.pnl = 0.0
        self.is_open = True

    def update_premium(self, new_premium: float):
        self.current_premium = new_premium
        if new_premium > self.peak_premium:
            self.peak_premium = new_premium

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_premium - self.entry_premium) * self.total_qty

    @property
    def pnl_pct(self) -> float:
        if self.entry_premium == 0:
            return 0
        return (self.current_premium - self.entry_premium) / self.entry_premium * 100


class SessionSimulator:
    """Replays a trading session through all strategies."""

    def __init__(self, capital: float = STARTING_CAPITAL, speed: str = "normal"):
        self.starting_capital = capital
        self.capital = capital
        self.speed = speed
        self.strategies = {name: cls() for name, cls in ALL_STRATEGIES.items()}
        self.positions: list[SimulatedPosition] = []
        self.closed_trades: list[SimulatedPosition] = []
        self.trade_counter = 0
        self.trades_today = 0
        self.signals_log: list[dict] = []
        self._last_spot: dict[str, float] = {}

    def run(self, session_date: date | None = None):
        """Run full simulation of a session."""
        print(f"\n{C.BOLD}{'═' * 70}{C.RESET}")
        print(f"{C.BOLD}  📊  SESSION REPLAY SIMULATOR{C.RESET}")
        print(f"{C.BOLD}{'═' * 70}{C.RESET}")
        print(f"  Starting capital: {C.CYAN}₹{self.starting_capital:,.0f}{C.RESET}")
        print(f"  Strategies: {', '.join(self.strategies.keys())}")
        print()

        # Scrape data
        print(f"  {C.DIM}Fetching market data...{C.RESET}")
        data_5m = {}
        data_15m = {}
        for index in ["BANKNIFTY", "NIFTY"]:
            data_5m[index] = scrape_session(index, session_date, "5m")
            data_15m[index] = scrape_session(index, session_date, "15m")

        # Pick index with most data
        primary = max(data_5m.keys(), key=lambda k: len(data_5m[k]))
        if not data_5m[primary]:
            print(f"\n  {C.RED}✗ No data available for this session.{C.RESET}")
            print(f"  {C.DIM}Try: python3 simulator.py --history{C.RESET}")
            return

        session_str = data_5m[primary][0]["timestamp"][:10]
        total_candles = max(len(data_5m[i]) for i in data_5m)
        print(f"  Session: {C.BOLD}{session_str}{C.RESET}")
        for idx in ["BANKNIFTY", "NIFTY"]:
            n = len(data_5m[idx])
            if n > 0:
                o = data_5m[idx][0]["open"]
                cl = data_5m[idx][-1]["close"]
                chg = cl - o
                color = C.GREEN if chg >= 0 else C.RED
                print(f"  {idx}: {n} candles | "
                      f"Open={o:,.0f} → Close={cl:,.0f} | "
                      f"{color}{'+' if chg >= 0 else ''}{chg:,.0f} ({chg/o*100:+.2f}%){C.RESET}")

        print(f"\n{C.BOLD}{'─' * 70}{C.RESET}")
        print(f"  {C.BOLD}REPLAY{C.RESET}")
        print(f"{'─' * 70}")

        # Replay candle by candle
        for candle_idx in range(total_candles):
            for index in ["BANKNIFTY", "NIFTY"]:
                candles_5m = data_5m[index][:candle_idx + 1]
                candles_15m = self._resample_to_15m(data_5m[index][:candle_idx + 1])

                if not candles_5m:
                    continue

                current = candles_5m[-1]
                spot = current["close"]
                ts = current["timestamp"]
                self._last_spot[index] = spot

                # Parse time for market hours check
                candle_time = self._parse_time(ts)
                if candle_time is None:
                    continue

                hhmm = candle_time.hour * 100 + candle_time.minute

                # 1. Monitor open positions (check SL/TP)
                self._monitor_positions(index, spot, candle_idx, ts)

                # 2. Square off at 15:15
                if hhmm >= 1515:
                    self._square_off_all(ts, "End-of-day square off")
                    continue

                # 3. No new entries after 14:45
                if hhmm > 1445:
                    continue

                # 4. Check if we can trade
                if self.trades_today >= MAX_TRADES_PER_DAY:
                    continue

                # 5. Build option chain from current price
                chain = self._build_option_chain(index, spot)

                # 6. Run strategies (with time override)
                self._run_strategies(index, spot, chain, candles_5m, candles_15m,
                                     candle_idx, ts, candle_time)

            # Display progress
            if candle_idx % 3 == 0 or candle_idx == total_candles - 1:
                self._show_status(candle_idx, total_candles, data_5m)

            # Speed control
            if self.speed == "slow":
                time.sleep(0.5)
            elif self.speed == "normal":
                time.sleep(0.1)
            # fast = no pause

        # Final square off anything remaining
        for idx in ["BANKNIFTY", "NIFTY"]:
            if data_5m[idx]:
                last_ts = data_5m[idx][-1]["timestamp"]
                self._square_off_all(last_ts, "Session ended")

        # Show results
        self._show_results(session_str)

    def _run_strategies(self, index, spot, chain, candles_5m, candles_15m,
                        candle_idx, ts, candle_time):
        """Run all strategies and execute best signal."""
        signals = []
        for name, strategy in self.strategies.items():
            try:
                # Temporarily override datetime.now for strategies that check time
                signal = self._analyze_with_time(
                    strategy, index, spot, chain, candles_5m, candles_15m, candle_time
                )
                if signal and signal.signal not in (Signal.HOLD,):
                    signals.append(signal)
                    self.signals_log.append({
                        "candle": candle_idx,
                        "time": ts,
                        "index": index,
                        "strategy": name,
                        "signal": signal.signal.value,
                        "strike": signal.strike,
                        "strength": round(signal.strength, 2),
                        "reason": signal.reason,
                        "premium": signal.premium,
                    })
            except Exception as e:
                logger.debug("Strategy %s error: %s", name, e)

        if not signals:
            return

        # Pick strongest
        best = max(signals, key=lambda s: s.strength)

        # Consensus bonus
        same_dir = [s for s in signals if s.signal == best.signal]
        if len(same_dir) > 1:
            best = TradeSignal(
                best.signal, best.index, best.strike,
                min(best.strength * 1.3, 1.0),
                best.reason + f" (+{len(same_dir)} agree)",
                best.strategy_name, best.premium
            )

        self._execute(best, candle_idx, ts)

    def _analyze_with_time(self, strategy, index, spot, chain,
                           candles_5m, candles_15m, sim_time):
        """Run strategy.analyze() with simulated time context."""
        # Monkey-patch datetime so strategies see the historical time
        import strategies.orb as orb_mod
        import strategies.momentum_scalp as mom_mod
        import strategies.vwap_bounce as vwap_mod
        import strategies.expiry_play as exp_mod

        original_now = datetime.now

        def fake_now(tz=None):
            if tz:
                return sim_time
            return sim_time

        # Patch all strategy modules' datetime.now usage
        _originals = {}
        for mod in [orb_mod, mom_mod, vwap_mod, exp_mod]:
            _originals[mod] = mod.datetime
            # Create a wrapper class
            class FakeDatetime(datetime):
                @classmethod
                def now(cls, tz=None):
                    return sim_time
            mod.datetime = FakeDatetime

        try:
            return strategy.analyze(index, spot, chain, candles_5m, candles_15m)
        finally:
            for mod, orig in _originals.items():
                mod.datetime = orig

    def _execute(self, signal: TradeSignal, candle_idx: int, ts: str):
        """Execute a trading signal."""
        index = signal.index
        opt_type = "CE" if signal.signal == Signal.BUY_CE else "PE"
        premium = signal.premium
        strike = signal.strike

        if premium <= 0:
            return

        lot_size = LOT_SIZES.get(index, 15)
        max_spend = self.capital * (MAX_RISK_PER_TRADE_PCT / 100)
        cost_per_lot = premium * lot_size

        # If suggested strike is too expensive, find a cheaper OTM option
        if cost_per_lot > max_spend:
            interval = BANKNIFTY_STRIKE_INTERVAL if index == "BANKNIFTY" else NIFTY_STRIKE_INTERVAL
            spot = self._last_spot.get(index, strike)
            found = False
            # Search OTM strikes (cheaper premiums)
            for offset in range(1, 8):
                if opt_type == "CE":
                    otm_strike = strike + offset * interval
                else:
                    otm_strike = strike - offset * interval
                otm_premium = self._calc_premium(spot, otm_strike, opt_type, index)
                otm_cost = otm_premium * lot_size
                if otm_cost <= max_spend and otm_premium >= 3:  # at least ₹3
                    strike = otm_strike
                    premium = otm_premium
                    cost_per_lot = otm_cost
                    found = True
                    break
            if not found:
                return

        qty_lots = max(int(max_spend / cost_per_lot), 1)
        cost = premium * lot_size * qty_lots

        if cost > self.capital:
            return

        self.capital -= cost
        self.trade_counter += 1
        self.trades_today += 1

        pos = SimulatedPosition(
            self.trade_counter, index, strike, opt_type,
            premium, lot_size, qty_lots, candle_idx, ts,
            signal.strategy_name, signal.reason
        )
        self.positions.append(pos)

        time_str = self._fmt_time(ts)
        color = C.GREEN if opt_type == "CE" else C.RED
        print(f"\n  {C.BOLD}🔔 TRADE #{self.trade_counter}{C.RESET} "
              f"@ {time_str} | {color}BUY {index} {strike}{opt_type}{C.RESET} "
              f"@ ₹{premium:.1f} × {lot_size * qty_lots} = "
              f"{C.CYAN}₹{cost:,.0f}{C.RESET}")
        print(f"     {C.DIM}Strategy: {signal.strategy_name} | "
              f"Strength: {signal.strength:.0%} | {signal.reason}{C.RESET}")

    def _monitor_positions(self, index: str, spot: float, candle_idx: int, ts: str):
        """Check SL/TP on open positions for this index."""
        for pos in self.positions:
            if not pos.is_open or pos.index != index:
                continue

            # Estimate current premium based on spot movement
            new_premium = self._estimate_premium(pos, spot)
            pos.update_premium(new_premium)

            # Check exit conditions
            trigger, reason = self._check_exit(pos)
            if trigger:
                self._close_position(pos, new_premium, ts, trigger, reason)

    def _check_exit(self, pos: SimulatedPosition) -> tuple[str | None, str]:
        """Check SL/TP/Trailing SL."""
        pnl_pct = pos.pnl_pct

        if pnl_pct <= -STOP_LOSS_PCT:
            return "stop_loss", f"SL hit ({pnl_pct:.1f}%)"

        if pnl_pct >= TARGET_PCT:
            return "target", f"Target hit ({pnl_pct:.1f}%)"

        # Trailing SL after 30%+ gain
        if pos.peak_premium > pos.entry_premium * 1.3:
            trail_level = pos.peak_premium * (1 - TRAILING_SL_PCT / 100)
            if pos.current_premium <= trail_level:
                locked = (pos.current_premium - pos.entry_premium) / pos.entry_premium * 100
                return "trailing_sl", f"Trail SL (peak=₹{pos.peak_premium:.0f}, locked {locked:.1f}%)"

        return None, ""

    def _close_position(self, pos: SimulatedPosition, exit_premium: float,
                        ts: str, trigger: str, reason: str):
        """Close a position."""
        pos.exit_premium = exit_premium
        pos.exit_time = ts
        pos.exit_trigger = trigger
        pos.pnl = (exit_premium - pos.entry_premium) * pos.total_qty
        pos.is_open = False

        self.capital += exit_premium * pos.total_qty
        self.closed_trades.append(pos)
        self.positions = [p for p in self.positions if p.is_open]

        time_str = self._fmt_time(ts)
        color = C.GREEN if pos.pnl >= 0 else C.RED
        icon = "✅" if pos.pnl >= 0 else "❌"
        print(f"  {icon} EXIT #{pos.id} @ {time_str} | "
              f"{pos.index} {pos.strike}{pos.opt_type} "
              f"₹{pos.entry_premium:.1f}→₹{exit_premium:.1f} | "
              f"{color}PnL: ₹{pos.pnl:+,.0f} ({pos.pnl_pct:+.1f}%){C.RESET} "
              f"| {trigger}")

    def _square_off_all(self, ts: str, reason: str):
        """Force close all open positions."""
        open_pos = [p for p in self.positions if p.is_open]
        for pos in open_pos:
            self._close_position(pos, pos.current_premium, ts, "square_off", reason)

    def _estimate_premium(self, pos: SimulatedPosition, current_spot: float) -> float:
        """
        Estimate current premium by recalculating at new spot price.
        This naturally handles ITM/OTM transitions.
        """
        return self._calc_premium(current_spot, pos.strike, pos.opt_type, pos.index)

    def _build_option_chain(self, index: str, spot: float) -> dict:
        """Build a simulated option chain around current spot."""
        interval = BANKNIFTY_STRIKE_INTERVAL if index == "BANKNIFTY" else NIFTY_STRIKE_INTERVAL
        atm = round(spot / interval) * interval

        chain = {"CE": [], "PE": [], "atm_strike": atm, "spot": spot}

        for i in range(-10, 11):
            strike = atm + i * interval
            for opt in ["CE", "PE"]:
                premium = self._calc_premium(spot, strike, opt, index)
                chain[opt].append({
                    "strike": strike,
                    "premium": round(premium, 1),
                    "token": f"SIM_{index}_{strike}{opt}",
                })

        return chain

    def _calc_premium(self, spot: float, strike: int, opt_type: str, index: str) -> float:
        """Realistic option premium approximation for Indian weekly options."""
        interval = BANKNIFTY_STRIKE_INTERVAL if index == "BANKNIFTY" else NIFTY_STRIKE_INTERVAL
        diff = spot - strike if opt_type == "CE" else strike - spot
        intrinsic = max(diff, 0)

        # Strikes away from ATM (this drives premium decay more than % distance)
        strikes_away = abs(spot - strike) / interval

        # ATM time value: realistic for weekly options with ~2 days left
        atm_tv = spot * (0.010 if index == "BANKNIFTY" else 0.007)

        # Premium decays roughly exponentially per strike OTM
        # ATM=100%, 1OTM=55%, 2OTM=30%, 3OTM=15%, 4OTM=7%, 5OTM=3%
        if diff >= 0:  # ITM
            time_value = atm_tv * math.exp(-0.3 * strikes_away)
        else:  # OTM
            time_value = atm_tv * math.exp(-0.7 * strikes_away)

        return max(intrinsic + time_value, 1.0)

    def _resample_to_15m(self, candles_5m: list[dict]) -> list[dict]:
        """Convert 5m candles to 15m by grouping."""
        if len(candles_5m) < 3:
            return candles_5m

        result = []
        for i in range(0, len(candles_5m) - 2, 3):
            group = candles_5m[i:i + 3]
            result.append({
                "timestamp": group[0]["timestamp"],
                "open": group[0]["open"],
                "high": max(c["high"] for c in group),
                "low": min(c["low"] for c in group),
                "close": group[-1]["close"],
                "volume": sum(c.get("volume", 0) for c in group),
            })
        return result

    def _parse_time(self, ts: str) -> datetime | None:
        """Parse ISO timestamp to datetime in IST."""
        try:
            dt = datetime.fromisoformat(ts)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=IST)
            return dt
        except Exception:
            return None

    def _show_status(self, candle_idx: int, total: int, data_5m: dict):
        """Show inline progress."""
        pct = (candle_idx + 1) / total * 100
        open_count = sum(1 for p in self.positions if p.is_open)
        unrealized = sum(p.unrealized_pnl for p in self.positions if p.is_open)
        realized = sum(p.pnl for p in self.closed_trades)

        # Get current spot for display
        spots = []
        for idx in ["BANKNIFTY", "NIFTY"]:
            candles = data_5m.get(idx, [])
            if candle_idx < len(candles):
                spots.append(f"{idx}={candles[candle_idx]['close']:,.0f}")

        spots_str = " | ".join(spots)
        total_pnl = realized + unrealized
        color = C.GREEN if total_pnl >= 0 else C.RED

        sys.stdout.write(
            f"\r  {C.DIM}[{candle_idx + 1}/{total}]{C.RESET} "
            f"{spots_str} | "
            f"Open:{open_count} | "
            f"Closed:{len(self.closed_trades)} | "
            f"{color}PnL: ₹{total_pnl:+,.0f}{C.RESET}  "
        )
        sys.stdout.flush()

    def _show_results(self, session_str: str):
        """Display final simulation results."""
        print(f"\n\n{C.BOLD}{'═' * 70}{C.RESET}")
        print(f"{C.BOLD}  📋  SESSION REPORT — {session_str}{C.RESET}")
        print(f"{'═' * 70}\n")

        total_trades = len(self.closed_trades)

        if total_trades == 0:
            print(f"  {C.YELLOW}No trades were triggered this session.{C.RESET}")
            self._show_signals_summary()
            return

        wins = [t for t in self.closed_trades if t.pnl > 0]
        losses = [t for t in self.closed_trades if t.pnl <= 0]
        total_pnl = sum(t.pnl for t in self.closed_trades)
        win_rate = len(wins) / total_trades * 100

        print(f"  {C.BOLD}Capital:{C.RESET}  ₹{self.starting_capital:,.0f} → "
              f"₹{self.capital:,.0f}")

        pnl_color = C.GREEN if total_pnl >= 0 else C.RED
        print(f"  {C.BOLD}Net PnL:{C.RESET}   {pnl_color}₹{total_pnl:+,.0f} "
              f"({total_pnl / self.starting_capital * 100:+.1f}%){C.RESET}")

        print(f"  {C.BOLD}Trades:{C.RESET}    {total_trades} total "
              f"({C.GREEN}{len(wins)} wins{C.RESET}, "
              f"{C.RED}{len(losses)} losses{C.RESET})")

        wr_color = C.GREEN if win_rate >= 50 else C.RED
        print(f"  {C.BOLD}Win Rate:{C.RESET}  {wr_color}{win_rate:.0f}%{C.RESET} "
              f"{_bar(win_rate, 20)}")

        if wins:
            avg_win = sum(t.pnl for t in wins) / len(wins)
            best_win = max(t.pnl for t in wins)
            print(f"  {C.BOLD}Avg Win:{C.RESET}   {C.GREEN}₹{avg_win:+,.0f}{C.RESET} "
                  f"| Best: {C.GREEN}₹{best_win:+,.0f}{C.RESET}")

        if losses:
            avg_loss = sum(t.pnl for t in losses) / len(losses)
            worst_loss = min(t.pnl for t in losses)
            print(f"  {C.BOLD}Avg Loss:{C.RESET}  {C.RED}₹{avg_loss:+,.0f}{C.RESET} "
                  f"| Worst: {C.RED}₹{worst_loss:+,.0f}{C.RESET}")

        if wins and losses:
            rr = abs(sum(t.pnl for t in wins) / len(wins)) / abs(sum(t.pnl for t in losses) / len(losses))
            rr_color = C.GREEN if rr >= 1 else C.RED
            print(f"  {C.BOLD}Risk/Reward:{C.RESET} {rr_color}{rr:.2f}{C.RESET}")

        # Strategy breakdown
        print(f"\n  {C.BOLD}Strategy Breakdown:{C.RESET}")
        print(f"  {'─' * 55}")
        strats = {}
        for t in self.closed_trades:
            if t.strategy not in strats:
                strats[t.strategy] = {"wins": 0, "losses": 0, "pnl": 0}
            if t.pnl > 0:
                strats[t.strategy]["wins"] += 1
            else:
                strats[t.strategy]["losses"] += 1
            strats[t.strategy]["pnl"] += t.pnl

        for name, s in sorted(strats.items(), key=lambda x: -x[1]["pnl"]):
            total = s["wins"] + s["losses"]
            wr = s["wins"] / total * 100 if total > 0 else 0
            pnl_c = C.GREEN if s["pnl"] >= 0 else C.RED
            print(f"  {name:<20} {total} trades | WR: {wr:.0f}% | "
                  f"{pnl_c}PnL: ₹{s['pnl']:+,.0f}{C.RESET}")

        # Trade details
        print(f"\n  {C.BOLD}Trade Log:{C.RESET}")
        print(f"  {'─' * 65}")
        print(f"  {'#':<3} {'Time':<6} {'Index':<10} {'Type':<4} {'Strike':<7} "
              f"{'Entry':<7} {'Exit':<7} {'PnL':<10} {'Trigger':<10}")
        print(f"  {'─' * 65}")

        for t in self.closed_trades:
            entry_t = self._fmt_time(t.entry_time)
            exit_t = self._fmt_time(t.exit_time)
            pnl_c = C.GREEN if t.pnl >= 0 else C.RED
            print(f"  {t.id:<3} {entry_t}→{exit_t} {t.index:<10} {t.opt_type:<4} "
                  f"{t.strike:<7} ₹{t.entry_premium:<6.1f} ₹{t.exit_premium:<6.1f} "
                  f"{pnl_c}₹{t.pnl:>+7,.0f}{C.RESET}  {t.exit_trigger}")

        # Exit type breakdown
        print(f"\n  {C.BOLD}Exit Analysis:{C.RESET}")
        triggers = {}
        for t in self.closed_trades:
            triggers.setdefault(t.exit_trigger, {"count": 0, "pnl": 0})
            triggers[t.exit_trigger]["count"] += 1
            triggers[t.exit_trigger]["pnl"] += t.pnl

        for trig, data in triggers.items():
            pnl_c = C.GREEN if data["pnl"] >= 0 else C.RED
            icon = {"stop_loss": "🛑", "target": "🎯", "trailing_sl": "📈",
                    "square_off": "⏰"}.get(trig, "•")
            print(f"  {icon} {trig:<15} {data['count']} exits | "
                  f"{pnl_c}₹{data['pnl']:+,.0f}{C.RESET}")

        # Signals summary
        self._show_signals_summary()

        # Learning insights
        self._show_insights()

        print(f"\n{C.BOLD}{'═' * 70}{C.RESET}\n")

        # Save report
        self._save_report(session_str)

    def _show_signals_summary(self):
        """Show all signals that were generated."""
        if not self.signals_log:
            print(f"\n  {C.YELLOW}No signals were generated.{C.RESET}")
            print(f"  {C.DIM}This could mean:{C.RESET}")
            print(f"  {C.DIM}  • Market was range-bound (no clear breakouts){C.RESET}")
            print(f"  {C.DIM}  • It was not an expiry day (expiry strategy inactive){C.RESET}")
            print(f"  {C.DIM}  • Session had low volatility{C.RESET}")
            return

        print(f"\n  {C.BOLD}All Signals Generated ({len(self.signals_log)}):{C.RESET}")
        print(f"  {'─' * 60}")
        for s in self.signals_log[:20]:  # show first 20
            time_str = self._fmt_time(s["time"])
            color = C.GREEN if "ce" in s["signal"] else C.RED
            print(f"  {time_str} | {s['index']:<10} | "
                  f"{color}{s['signal']:<7}{C.RESET} {s['strike']} "
                  f"| str={s['strength']:.0%} | {s['strategy']}")

        if len(self.signals_log) > 20:
            print(f"  {C.DIM}... and {len(self.signals_log) - 20} more{C.RESET}")

    def _show_insights(self):
        """Show learning insights based on the simulation."""
        print(f"\n  {C.BOLD}💡 Learning Insights:{C.RESET}")
        print(f"  {'─' * 55}")

        if not self.closed_trades:
            return

        total_pnl = sum(t.pnl for t in self.closed_trades)
        wins = [t for t in self.closed_trades if t.pnl > 0]
        losses = [t for t in self.closed_trades if t.pnl <= 0]
        win_rate = len(wins) / len(self.closed_trades) * 100

        # Insight 1: Best strategy
        strat_pnl = {}
        for t in self.closed_trades:
            strat_pnl.setdefault(t.strategy, 0)
            strat_pnl[t.strategy] += t.pnl
        best_strat = max(strat_pnl, key=strat_pnl.get)
        worst_strat = min(strat_pnl, key=strat_pnl.get)

        if strat_pnl[best_strat] > 0:
            print(f"  ✦ Best strategy: {C.GREEN}{best_strat}{C.RESET} "
                  f"(₹{strat_pnl[best_strat]:+,.0f})")
        if strat_pnl[worst_strat] < 0:
            print(f"  ✦ Weakest strategy: {C.RED}{worst_strat}{C.RESET} "
                  f"(₹{strat_pnl[worst_strat]:+,.0f})")

        # Insight 2: SL hit too often?
        sl_trades = [t for t in self.closed_trades if t.exit_trigger == "stop_loss"]
        if len(sl_trades) > len(self.closed_trades) * 0.5:
            print(f"  ⚠ {C.YELLOW}SL was hit on {len(sl_trades)}/{len(self.closed_trades)} trades. "
                  f"Consider widening SL or being more selective.{C.RESET}")

        # Insight 3: Target hit often?
        target_trades = [t for t in self.closed_trades if t.exit_trigger == "target"]
        if target_trades:
            avg_time = sum(
                (self._parse_time(t.exit_time) - self._parse_time(t.entry_time)).total_seconds() / 60
                for t in target_trades if self._parse_time(t.exit_time) and self._parse_time(t.entry_time)
            ) / len(target_trades)
            print(f"  ✦ Target trades took avg {avg_time:.0f} min to hit.")

        # Insight 4: Trailing SL effectiveness
        trail_trades = [t for t in self.closed_trades if t.exit_trigger == "trailing_sl"]
        if trail_trades:
            avg_locked = sum(
                (t.exit_premium - t.entry_premium) / t.entry_premium * 100
                for t in trail_trades
            ) / len(trail_trades)
            print(f"  ✦ Trailing SL locked avg {C.GREEN}{avg_locked:.0f}%{C.RESET} profit "
                  f"on {len(trail_trades)} trades.")

        # Insight 5: Time-based analysis
        morning = [t for t in self.closed_trades
                   if self._get_hour(t.entry_time) < 11]
        afternoon = [t for t in self.closed_trades
                     if self._get_hour(t.entry_time) >= 11]
        if morning and afternoon:
            m_pnl = sum(t.pnl for t in morning)
            a_pnl = sum(t.pnl for t in afternoon)
            better = "Morning" if m_pnl > a_pnl else "Afternoon"
            print(f"  ✦ {better} trades performed better "
                  f"(Morning: ₹{m_pnl:+,.0f}, Afternoon: ₹{a_pnl:+,.0f})")

        # Insight 6: Overall verdict
        if total_pnl > 0:
            pct = total_pnl / self.starting_capital * 100
            print(f"\n  {C.GREEN}✓ Profitable session! "
                  f"+{pct:.1f}% return on ₹{self.starting_capital:,.0f}{C.RESET}")
            if pct > 4:
                print(f"  {C.GREEN}  On track for the ₹1Cr goal!{C.RESET}")
        else:
            print(f"\n  {C.RED}✗ Loss-making session. "
                  f"Review the trade log above for improvements.{C.RESET}")
            if win_rate < 40:
                print(f"  {C.YELLOW}  Low win rate ({win_rate:.0f}%) — "
                      f"strategies may not suit this market condition.{C.RESET}")

    @staticmethod
    def _fmt_time(ts: str) -> str:
        """Extract HH:MM from ISO timestamp."""
        try:
            t_idx = ts.index("T")
            return ts[t_idx + 1:t_idx + 6]
        except (ValueError, IndexError):
            return ts[-8:-3]

    def _get_hour(self, ts: str) -> int:
        dt = self._parse_time(ts)
        return dt.hour if dt else 12

    def _save_report(self, session_str: str):
        """Save simulation report to JSON."""
        report_dir = DATA_DIR / "sim_reports"
        report_dir.mkdir(exist_ok=True)

        report = {
            "session_date": session_str,
            "starting_capital": self.starting_capital,
            "ending_capital": round(self.capital, 2),
            "net_pnl": round(sum(t.pnl for t in self.closed_trades), 2),
            "total_trades": len(self.closed_trades),
            "wins": sum(1 for t in self.closed_trades if t.pnl > 0),
            "losses": sum(1 for t in self.closed_trades if t.pnl <= 0),
            "trades": [
                {
                    "id": t.id, "index": t.index, "strike": t.strike,
                    "opt_type": t.opt_type, "entry_premium": t.entry_premium,
                    "exit_premium": t.exit_premium, "pnl": round(t.pnl, 2),
                    "strategy": t.strategy, "trigger": t.exit_trigger,
                    "entry_time": t.entry_time, "exit_time": t.exit_time,
                    "reason": t.reason,
                }
                for t in self.closed_trades
            ],
            "signals": self.signals_log,
        }

        path = report_dir / f"sim_{session_str}.json"
        path.write_text(json.dumps(report, indent=2))
        print(f"  {C.DIM}Report saved → {path}{C.RESET}")


def main():
    parser = argparse.ArgumentParser(
        description="📊 Session Replay Simulator — Learn from real market data",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--date", "-d", type=str, default=None,
        help="Session date to replay (YYYY-MM-DD). Default: last trading day."
    )
    parser.add_argument(
        "--capital", "-c", type=float, default=STARTING_CAPITAL,
        help=f"Starting capital (default: ₹{STARTING_CAPITAL:,.0f})"
    )
    parser.add_argument(
        "--speed", "-s", choices=["slow", "normal", "fast"], default="fast",
        help="Replay speed: slow (0.5s), normal (0.1s), fast (instant)"
    )
    parser.add_argument(
        "--history", action="store_true",
        help="List all cached sessions"
    )
    parser.add_argument(
        "--fetch-only", action="store_true",
        help="Only fetch and cache data, don't simulate"
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )

    if args.history:
        sessions = list_cached_sessions()
        if not sessions:
            print("No cached sessions. Run simulator once to fetch data.")
            return
        print(f"\n{'═' * 40}")
        print(f"  Cached Sessions")
        print(f"{'═' * 40}")
        for s in sessions:
            indices = ", ".join(
                f"{idx} ({', '.join(tfs)})"
                for idx, tfs in s["indices"].items()
            )
            print(f"  {s['date']}  →  {indices}")
        print(f"\nReplay with: python3 simulator.py --date YYYY-MM-DD\n")
        return

    session_date = None
    if args.date:
        try:
            session_date = date.fromisoformat(args.date)
        except ValueError:
            print(f"Invalid date format: {args.date}. Use YYYY-MM-DD.")
            return

    if args.fetch_only:
        print("Fetching data...")
        scrape_last_session()
        print("Done.")
        return

    sim = SessionSimulator(capital=args.capital, speed=args.speed)
    sim.run(session_date)


if __name__ == "__main__":
    main()
