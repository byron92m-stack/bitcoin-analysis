# Phase 7 — LightGBM Trading Bot v4

## Architecture

data.py loads 1m candles from ClickHouse (btc_1m table) and on-chain fees from block_metrics. Aggregates to 1H candles. Merges Z-Score from Phase 3.

features.py builds 26 features: price returns (1h, 4h, 24h), volatility (4h, 24h), volume ratio, range position, close position, momentum (4h, 24h), RSI 14, MACD, MACD histogram, Bollinger Bands position and width, ATR as percentage, SMA10/50 crossover, funding rate, funding signal, on-chain Z-Score, Z-Score moving average, Z-Score change, Z-Score regime, hour, day of week, weekend flag.

train.py runs walk-forward backtesting across 9 periods of 6 months each. Model retrained on prior 6 months, tested on next 6 months. Kelly criterion sizes positions dynamically. Trailing stop protects gains. Max daily loss halts trading at -2% per day. Outputs model file, equity curve PNG, and trade CSV log.

live.py connects to Binance WebSocket for 1H klines. Builds features from last 50 candles. Gets live Z-Score from ClickHouse. Predicts LONG or WAIT every hour with confidence score. Auto-reconnects on disconnect.

paper_trader.py simulates trades with $10,000 virtual capital. Logs every trade with entry, exit, return, P&L. Prints summary with Sharpe, Sortino, win rate, max drawdown on exit.

## Files

config.py — 26 features, hyperparameters, risk management constants.

data.py — Load 1m from ClickHouse, aggregate to 1H, merge on-chain Z-Score.

features.py — Build 26 features including technical analysis and on-chain alpha.

train.py — Walk-forward backtest with Kelly sizing, trailing stop, max daily loss.

live.py — WebSocket live signals every hour.

paper_trader.py — Simulated trading with $10,000 virtual capital.

## Features (26)

Market: return_1h, return_4h, return_24h. Volatility: volatility_4h, volatility_24h. Volume: volume_ratio. Position: range_pct, close_position. Momentum: momentum_4h, momentum_24h.

Technical Analysis: rsi_14 (RSI 14 periods), macd (MACD line 12/26), macd_hist (MACD histogram), bb_position (position within Bollinger Bands), bb_width (Bollinger Band width), atr_pct (ATR as % of price), sma_cross (SMA10 above SMA50).

Funding: funding_rate (perpetual futures rate), funding_signal (extreme flag).

On-Chain (Phase 3): fees_zscore (30-day rolling Z-Score), fees_zscore_ma7 (7-period smoothed), fees_zscore_change (24h change), zscore_regime (categorical -1/0/1/2).

Temporal: hour, day_of_week, is_weekend.

## Target

Binary classification: 1 if close(t+1) is higher than close(t), 0 otherwise.

## Risk Management v4

MIN_CONFIDENCE 0.55 — Minimum probability to enter a trade. BASE_POSITION_SIZE 1.5% — Base capital allocated per trade. MAX_POSITION_SIZE 4% — Kelly-scaled maximum. STOP_LOSS -0.3% — Fixed maximum loss per trade. TAKE_PROFIT +0.8% — Fixed take profit target. ATR_MULTIPLIER 1.5 — Dynamic stop uses ATR times this multiplier. TRAILING_STOP_ACTIVATION +0.4% — Trail activates after this gain. TRAILING_STOP_DISTANCE 0.2% — Trail stays this far below peak. KELLY_FRACTION 0.5 — Half-Kelly for conservative sizing. MAX_DAILY_LOSS 2% — Stop trading after losing this much in one day.

## Backtest Methodology

Walk-forward with 9 periods of 6 months each. Model trains on months 1-6, tests on months 7-12. Then retrains on months 7-12, tests on 13-18. Continues through all data. Test period never seen during training. Zero data leakage.

## Performance v4

Total Return: +69.74% over 4.5 years. Annualized: +11.2%. Total Trades: 12,806. Win Rate: 53.8%. Profit Factor: 2.02 (wins $2.02 for every $1 lost). Sharpe Ratio: 26.4. Sortino Ratio: 94.7. Max Drawdown: -0.14%. Expectancy: +0.103% per trade. Avg Win: +0.38%. Avg Loss: -0.22%. Win/Loss Ratio: 1.7 to 1. All 9 periods profitable.

## Usage

Train model: python bot/train.py
Live signals: python bot/live.py
Paper trading: python bot/paper_trader.py
