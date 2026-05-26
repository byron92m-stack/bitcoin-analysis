# Phase 7 — LightGBM Trading Bot v5

5m timeframe trading bot using LightGBM with 25 features. Combines price action, technical analysis, on-chain alpha from Phase 3, and funding rate sentiment. Multi-timeframe backtested: 5m confirmed as optimal.

## Multi-Timeframe Optimization

Tested 5m, 15m, 1h, 4h, 1d. 5m won: +16.76% return, 55.4% win rate, 455K trades, Sharpe 3.34. Full comparison in train.py output.

## Architecture

data.py loads 1m candles from ClickHouse btc_1m table and on-chain fees from block_metrics. Aggregates to 5m candles. Merges Z-Score from Phase 3.

features.py builds 25 features: returns, volatility, volume, position, momentum, RSI, MACD, Bollinger Bands, ATR, SMA crosses, funding rate, on-chain Z-Score and regime, hour, minute, day of week, weekend flag.

train.py compares all timeframes (5m, 15m, 1h, 4h, 1d). Walk-forward backtest with Kelly sizing, trailing stop, max daily loss.

live.py connects to Binance WebSocket for 5m klines. Preloads 100 candles. Gets live Z-Score from ClickHouse. Predicts LONG/WAIT every 5 minutes. Auto-reconnects.

funding_collector.py collects funding rate from Binance Futures WebSocket into ClickHouse.

## Files

config.py — 25 features, LightGBM hyperparameters, risk management constants for 5m.
data.py — Load 1m from ClickHouse, aggregate to chosen timeframe, merge Z-Score.
features.py — Build 25 features including technical analysis and on-chain alpha.
train.py — Multi-timeframe comparison + backtest.
live.py — WebSocket live signals every 5 minutes with auto-reconnect.
funding_collector.py — Collects funding rate from Binance Futures, stores in ClickHouse.

## Features (25)

Market (3): return_tf, return_4tf, return_24tf.
Volatility (2): volatility_4tf, volatility_24tf.
Volume (1): volume_ratio.
Position (2): range_pct, close_position.
Momentum (2): momentum_4tf, momentum_24tf.
Technical Analysis (7): rsi_14, macd, macd_hist, bb_position, bb_width, atr_pct, sma_cross.
Funding Rate (2): funding_rate, funding_signal.
On-Chain from Phase 3 (4): fees_zscore, fees_zscore_ma7, fees_zscore_change, zscore_regime.
Temporal (4): hour, minute, day_of_week, is_weekend.

## Risk Management v5 (5m optimized)

MIN_CONFIDENCE 0.55, BASE_POSITION_SIZE 0.5%, STOP_LOSS -0.2%, TAKE_PROFIT +0.5%, TRAILING_STOP_ACTIVATION +0.3%, TRAILING_STOP_DISTANCE 0.15%, MAX_DAILY_LOSS 2%.

## Performance v5

5m timeframe: +16.76% over 4.5 years. 455,469 trades. Win rate 55.4%. Profit factor 1.73. Sharpe 3.34. Max drawdown 0.02%.

Multi-timeframe comparison: 5m (+16.76%), 15m (+13.09%), 1h (+9.98%), 4h (+5.68%), 1d (+1.94%).

## Usage

Train model: python bot/train.py
Live signals (5m): python bot/live.py
Funding collector: python bot/funding_collector.py &
