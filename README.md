# OptionsPilot

A paper-trading bot and session-replay simulator for intraday Nifty and BankNifty options buying on NSE. Four rule-based strategies feed a shared risk manager; trades are simulated locally, with a Telegram alert hook and a small web dashboard.

> **Not financial advice. Options trading can lose your entire capital.**
> **Only paper mode is functional.** The live Angel One path is an incomplete stub: it can place an entry order but cannot track, exit or square off positions. See [Status](#status) before touching `TRADING_MODE=live`.

System design: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## Problem it addresses

Intraday options traders repeat the same loop: watch an index, wait for a setup, size the position, set exits, and stop after a bad day. This project encodes that loop as code so strategies and risk rules can be tried against simulated and replayed sessions before any real money is involved.

## Status

| Area | State |
|---|---|
| Paper trading loop (`main.py`) | Works end to end: entries, stop-loss, target, trailing stop, 3:15 PM square-off, daily limits |
| Session replay (`simulator.py`) | Replays real cached or downloaded index candles through all strategies; option prices are approximated |
| Live trading via Angel One | **Incomplete.** In live mode `get_open_positions`, `get_closed_trades` and `sell_option` return empty values, intraday candles are not fetched (`_get_candles` returns `[]`), and the entry order has an empty `symboltoken` (`broker/client.py`). Stop-loss, target and square-off therefore do not run on live positions |
| Tests | None |
| Evidence of profitability | None. See [Results so far](#results-so-far) |

## Architecture overview

```
main.py (OptionsBot, APScheduler every 2 min in market hours)
  |-- broker/client.py     BrokerClient: PaperTrader (JSON-backed) or Angel One SmartAPI
  |-- strategies/          orb, momentum_scalp, vwap_bounce, expiry_play  (BaseStrategy -> TradeSignal)
  |-- risk_manager.py      daily limits, position sizing, SL / target / trailing exit
  |-- notifier.py          Telegram alerts (only if token and chat id are set)
  |-- goal_tracker.py      equity snapshots and progress toward GOAL_AMOUNT
  |-- dashboard.py         Flask: / and /api/status
simulator.py + data_scraper.py   replay a past session using yfinance candles (cached in data/history)
```

Details and design decisions: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Setup and run

Requires Python 3.10+ (see `docs/DEPLOYMENT.md`).

```bash
pip install -r requirements.txt
cp .env.example .env        # defaults to TRADING_MODE=paper
python3 main.py             # paper trading; dashboard at http://127.0.0.1:8080
```

Replay a past session (needs network for yfinance on first run, then uses the cache):

```bash
python3 simulator.py                    # last session
python3 simulator.py --date 2026-03-20  # a specific date
python3 simulator.py --history          # list cached sessions
python3 simulator.py --speed fast       # skip pauses
```

Configuration is environment-driven; every variable and its default is in `config.py` and `.env.example`.

## Strategies

All four return a `TradeSignal` (buy CE, buy PE, or hold) with a strength in 0-1.

| Strategy | Rule (from the code) | Window |
|---|---|---|
| `orb` | Range from 9:15-9:30 candles; buy CE above the high, PE below the low; ignores ranges under 50 points (BankNifty) / 20 (Nifty); once per day per index | 9:30-11:30 |
| `momentum_scalp` | Consecutive same-direction 5m candles with RSI confirmation | see `strategies/momentum_scalp.py` |
| `vwap_bounce` | Bounce or rejection at intraday VWAP confirmed by candle pattern | see `strategies/vwap_bounce.py` |
| `expiry_play` | Cheap OTM options (premium 5-50) on expiry-day breakouts; expiry weekday is hard-coded (Wed BankNifty, Thu Nifty) | 10:00-14:00 |

## Risk controls (defaults from `config.py`)

- Max 20% of capital per trade, 5 trades per day, stop trading after a 30% daily loss.
- Exit at -30% premium (stop-loss), +50% (target), or a 20% trailing stop from peak once the premium is up more than 30%.
- No new entries after 14:45 IST; square-off at 15:15 IST.
- These apply to paper positions only (see [Status](#status)). `expiry_play`'s docstring describes a 50% stop and larger targets, but the exit logic enforced is the global one above.

## Results so far

Two simulated sessions are saved in `data/sim_reports/` (not committed; `data/` is git-ignored):

| Session | Trades | Wins / losses | Net P&L (starting capital 5,000) |
|---|---|---|---|
| 2026-03-20 | 3 | 0 / 3 | -839.28 |
| 2026-03-23 | 2 | 2 / 0 | +1,043.46 |

This is five trades with approximated option prices. It says nothing about expected performance. TODO: add a multi-week replay or backtest result with transaction costs.

## Limitations and next steps

- Finish the live broker path: token lookup, position and order-book sync, a real `sell_option`, live candle feed.
- Paper mode generates synthetic random-walk candles each cycle (`_generate_paper_candles`), so paper-mode P&L is not evidence of anything. Replay on real candles is the more meaningful check.
- Option premiums are approximated, not read from a real option chain.
- Expiry weekdays and lot sizes are hard-coded; confirm against current NSE rules before use.
- `goal_tracker.py` computes days left to 31 Dec 2026 (hard-coded year).
- The dashboard has no authentication. Keep `DASHBOARD_HOST=127.0.0.1`; do not expose it publicly.
- Add tests for the risk manager and each strategy, and a LICENSE.
