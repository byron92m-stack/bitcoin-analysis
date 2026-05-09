import os, sys, joblib
import numpy as np
import pandas as pd
import lightgbm as lgb
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from config import *
from data import load_training_data
from features import build_features

def calculate_metrics(trades_df, history):
    if trades_df.empty: return {}
    returns = trades_df['pnl_pct'].values
    win_rate = (returns > 0).mean()
    if len(history) > 2:
        h_returns = np.diff(history) / history[:-1]
        h_returns = h_returns[h_returns != 0]
        sharpe = np.mean(h_returns) / np.std(h_returns) * np.sqrt(252) if np.std(h_returns) > 0 else 0
    else:
        sharpe = 0
    peak = np.maximum.accumulate(history)
    dd = (np.array(history) - peak) / peak
    max_dd = abs(dd.min())
    total_return = (history[-1] - history[0]) / history[0]
    gross_profit = returns[returns > 0].sum()
    gross_loss = abs(returns[returns < 0].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    avg_win = returns[returns > 0].mean() if len(returns[returns > 0]) > 0 else 0
    avg_loss = returns[returns < 0].mean() if len(returns[returns < 0]) > 0 else 0
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * abs(avg_loss))
    return {'sharpe': sharpe, 'profit_factor': profit_factor, 'expectancy': expectancy,
            'win_rate': win_rate, 'max_dd': max_dd, 'total_return': total_return,
            'avg_win': avg_win, 'avg_loss': avg_loss}

def backtest(df):
    train = df[df['open_time'] < '2022-01-01']
    test = df[df['open_time'] >= '2022-01-01'].copy()
    if len(train) < 100 or len(test) < 10: return None, len(test)
    
    model = lgb.LGBMClassifier(**LGBM_PARAMS)
    model.fit(train[FEATURES].values, train[TARGET].values)
    probs = model.predict_proba(test[FEATURES].values)[:, 1]
    
    cap = INITIAL_CAPITAL
    trades = []
    history = [cap]
    in_position = False
    entry_price = trailing_high = 0
    
    for i, (idx, prob) in enumerate(zip(test.index, probs)):
        z = test.loc[idx, 'fees_zscore']
        if prob >= MIN_CONFIDENCE and z > -1.0 and i + 1 < len(test):
            close_now = test.loc[idx, 'close']
            close_next = test.iloc[i + 1]['close']
            actual_return = (close_next - close_now) / close_now
            actual = test.loc[idx, 'target']
            
            if not in_position:
                entry_price = close_now
                trailing_high = close_now
                in_position = True
            if close_now > trailing_high: trailing_high = close_now
            if (close_now - trailing_high) / trailing_high < -TRAILING_STOP_DISTANCE:
                actual_return = (close_now - entry_price) / entry_price
                in_position = False
            
            if actual == 1: pnl_pct = min(abs(actual_return), TAKE_PROFIT)
            else: pnl_pct = -min(abs(actual_return), STOP_LOSS)
            
            cap += cap * pnl_pct * BASE_POSITION_SIZE
            trades.append({'pnl_pct': pnl_pct, 'win': actual == 1})
            history.append(cap)
    
    return calculate_metrics(pd.DataFrame(trades), history), len(test)

def main():
    print("=" * 60)
    print("Multi-Timeframe: 5m, 15m, 1h, 4h, 1d")
    print("=" * 60)
    
    results = []
    for tf in ['5m', '15m', '1h', '4h', '1d']:
        print(f"\n--- {tf.upper()} ---")
        df = load_training_data(timeframe=tf)
        df = build_features(df)
        metrics, n_candles = backtest(df)
        if metrics:
            print(f"  Candles: {n_candles:,}")
            print(f"  Return: {metrics['total_return']*100:+.2f}% | Win: {metrics['win_rate']*100:.1f}% | PF: {metrics['profit_factor']:.2f} | Sharpe: {metrics['sharpe']:.2f}")
            results.append({'tf': tf, 'candles': n_candles, **metrics})
    
    if results:
        print(f"\n{'='*80}")
        print(f"{'TF':<6} {'Candles':>9} {'Return':>10} {'Win':>8} {'PF':>8} {'Sharpe':>8} {'MaxDD':>8}")
        print("-" * 80)
        for r in results:
            print(f"{r['tf']:<6} {r['candles']:>9,} {r['total_return']*100:>+9.2f}% {r['win_rate']*100:>7.1f}% {r['profit_factor']:>7.2f} {r['sharpe']:>7.2f} {r['max_dd']*100:>7.2f}%")
    
    MODEL_DIR = "/media/SSD4T/btc-etl/models"
    os.makedirs(MODEL_DIR, exist_ok=True)
    path = os.path.join(MODEL_DIR, f'lgbm_bot_v5_{datetime.now().strftime("%Y%m%d")}.pkl')
    joblib.dump(lgb.LGBMClassifier(**LGBM_PARAMS), path)

if __name__ == "__main__":
    main()
