# Architecture

A single-process Python application: a scheduler drives a trading cycle that turns market data into strategy signals, filters them through a risk manager, and executes them against a broker abstraction. Paper trading is a local simulator behind the same interface as the live broker.

## System context

```
                 +-------------------+          +------------------------+
 NSE index API ->|  BrokerClient     |<-------->| PaperTrader (JSON)     |  mode = paper
 (spot price)    |  broker/client.py |          +------------------------+
                 |                   |<-------->| Angel One SmartAPI     |  mode = live (incomplete)
                 +---------+---------+          +------------------------+
                           ^
                           |  spot, option chain, orders
 +-------------+   +-------+---------+   signals   +----------------------+
 | APScheduler |-->| OptionsBot      |<------------| strategies/*         |
 | every 2 min |   | main.py         |             | orb, momentum_scalp, |
 +-------------+   |  run_cycle()    |------------>| vwap_bounce,         |
                   +---+---------+---+  candles,   | expiry_play          |
                       |         |      chain      +----------------------+
              checks   |         |  alerts
                       v         v
              +---------------+  +-------------+   +--------------+
              | RiskManager   |  | Notifier    |   | GoalTracker  |
              | risk_manager  |  | (Telegram)  |   | equity log   |
              +---------------+  +-------------+   +--------------+

 Flask dashboard (thread)  --reads-->  broker, risk, goal          (http://127.0.0.1:8080)

 Offline path:  simulator.py -> data_scraper.py (yfinance, cached in data/history) -> same strategies
```

## Components

| Module | Responsibility |
|---|---|
| `main.py` | `OptionsBot` orchestrator. `run_cycle` monitors open positions, squares off after 15:15 IST, otherwise runs every strategy on every configured index. Schedules the cycle (2 min), a 15:15 square-off job and a 15:25 daily summary; starts the dashboard thread |
| `broker/client.py` | `BrokerClient` facade over `PaperTrader` (local simulated account persisted to JSON) or Angel One SmartAPI. Provides spot price, an approximated option chain, order placement and account state |
| `strategies/` | `BaseStrategy.analyze(index, spot, chain, candles_5m, candles_15m) -> TradeSignal`. Four implementations registered in `ALL_STRATEGIES`. Strategies keep their own per-day state (e.g. ORB range, triggered flag) and reset on a new IST date |
| `risk_manager.py` | Pre-trade gate (`can_trade`: trades per day, daily loss limit), sizing (`can_afford_lot`), and exit rules (`check_exit`: stop-loss, target, trailing stop from tracked peak). State persisted to `data/risk_state.json` |
| `notifier.py` | Logs every message and, if token and chat id are set, posts to the Telegram Bot API. Failures are logged, never raised |
| `goal_tracker.py` | One equity snapshot per day, required versus actual daily return toward `GOAL_AMOUNT` |
| `dashboard.py` | Flask app with `/` (inline HTML) and `/api/status` (JSON) |
| `simulator.py`, `data_scraper.py` | Session replay on real index candles (yfinance), with a local cache and JSON reports |
| `config.py` | All settings from environment (`.env` via python-dotenv) with defaults; lot sizes and strike intervals |

## Cycle flow (`run_cycle`)

1. Return if outside Mon-Fri 09:15-15:30 IST.
2. Read capital; for each open position fetch spot and chain, update its premium, and ask `RiskManager.check_exit`. Exit on stop-loss, target or trailing stop.
3. If past 15:15, square off everything and stop.
4. If before 14:45, for each index: `RiskManager.can_trade` -> fetch spot, chain and candles -> run all strategies -> take the strongest non-hold signal (strength multiplied by 1.3, capped at 1.0, when other strategies agree on direction) -> `RiskManager.can_afford_lot` (one lot must cost at most 20% of capital; lots = that budget / cost per lot) -> `BrokerClient.buy_option` -> record trade and alert.
5. Any exception in the cycle is logged and sent as an alert; the scheduler keeps running.

## Key design decisions

- **Broker abstraction with a paper implementation.** Strategy, risk and orchestration code is mode-agnostic; paper mode swaps only the broker. This is what lets the same loop run safely without credentials.
- **Strategy as a pure-ish interface.** Each strategy turns a market snapshot into a `TradeSignal` with a 0-1 strength; the orchestrator and risk manager decide whether and how much to trade. Adding a strategy means one class and one registry entry.
- **Risk is centralised, not per strategy.** One place owns daily limits, sizing and exit rules, so no strategy can bypass them. (The `expiry_play` docstring mentions different stop and target values than the enforced global ones.)
- **Defaults fail safe.** Mode defaults to paper, the dashboard binds to 127.0.0.1, and Telegram is disabled unless both values are present.
- **File-based persistence.** Paper account, risk state, goal snapshots, cached candles and simulation reports are JSON files under `data/`. Simple and inspectable; survives restarts. `data/` is git-ignored.
- **IST handled explicitly.** All time gating uses an IST-aware clock rather than the host timezone.
- **Replay for offline validation.** `simulator.py` runs the real strategy classes over real candles, separate from the live loop.

## Concurrency and state

Three actors share in-memory objects: the APScheduler worker (cycle, square-off and summary jobs, `max_instances=1` for the cycle), the Flask dashboard thread, and the main thread's heartbeat loop. There are no locks, and JSON state is written with plain `write_text` (not atomic), so a dashboard read can race a write.

## Known limitations

- **Live mode is incomplete.** `get_open_positions`, `get_closed_trades` and `sell_option` return empty values; `_get_candles` returns `[]`; the entry order carries an empty `symboltoken`. Exits and square-off do not operate on live positions.
- **Paper data is synthetic.** Paper mode builds candles from a random walk around the spot price each cycle, and option premiums come from an approximation, so paper results are not evidence of strategy quality.
- **Spot fallback.** If the NSE endpoint fails, hard-coded fallback spot values are used.
- **Hard-coded market rules.** Lot sizes, strike intervals and weekly expiry weekdays are constants.
- **Dashboard has no authentication** and exposes capital, positions and trade history at `/api/status`.
- **No tests.**
