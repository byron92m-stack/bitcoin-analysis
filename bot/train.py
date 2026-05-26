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
    return {'sharpe': sharpe, 'profit_factor': profit_factor, 'win_rate': win_rate,
            'max_dd': max_dd, 'total_return': total_return}

def backtest_period(df, train_start, train_end, test_start, test_end, name):
    train = df[(df['open_time'] >= train_start) & (df['open_time'] < train_end)]
    test = df[(df['open_time'] >= test_start) & (df['open_time'] < test_end)]
    if len(train) < 100 or len(test) < 10: return None
    
    model = lgb.LGBMClassifier(**LGBM_PARAMS)
    model.fit(train[FEATURES].values, train[TARGET].values)
    probs = model.predict_proba(test[FEATURES].values)[:, 1]
    
    cap = INITIAL_CAPITAL
    trades = []
    history = [cap]
    
    for i, (idx, prob) in enumerate(zip(test.index, probs)):
        z = test.loc[idx, 'fees_zscore']
        if prob >= MIN_CONFIDENCE and z > -1.0 and i + 1 < len(test):
            close_now = test.loc[idx, 'close']
            close_next = test.iloc[i + 1]['close']
            actual_return = (close_next - close_now) / close_now
            actual = test.loc[idx, 'target']
            
            if actual == 1: pnl_pct = min(abs(actual_return), TAKE_PROFIT)
            else: pnl_pct = -min(abs(actual_return), STOP_LOSS)
            
            cap += cap * pnl_pct * BASE_POSITION_SIZE
            trades.append({'pnl_pct': pnl_pct, 'win': actual == 1})
            history.append(cap)
    
    metrics = calculate_metrics(pd.DataFrame(trades), history)
    if metrics:
        print(f"  {name:<15} | Return: {metrics['total_return']*100:+.2f}% | "
              f"Trades: {len(trades):,} | Win: {metrics['win_rate']*100:.1f}% | "
              f"PF: {metrics['profit_factor']:.2f} | Sharpe: {metrics['sharpe']:.2f}")
    return metrics

def main():
    print("=" * 60)
    print("LightGBM Bot v5 — 5m Timeframe")
    print("=" * 60)
    
    print("\n1. Loading 5m data...")
    df = load_training_data(timeframe='5m')
    
    print("\n2. Building features...")
    df = build_features(df)
    print(f"   {len(df):,} candles, {len(FEATURES)} features")
    
    # Walk-forward por épocas (entrenar 1 año, testear 6 meses)
    periods = [
        ('H2 2019', '2019-01-01', '2019-06-30', '2019-07-01', '2019-12-31'),
        ('H1 2020', '2019-07-01', '2019-12-31', '2020-01-01', '2020-06-30'),
        ('H2 2020', '2020-01-01', '2020-06-30', '2020-07-01', '2020-12-31'),
        ('H1 2021', '2020-07-01', '2020-12-31', '2021-01-01', '2021-06-30'),
        ('H2 2021', '2021-01-01', '2021-06-30', '2021-07-01', '2021-12-31'),
        ('H1 2022', '2021-07-01', '2021-12-31', '2022-01-01', '2022-06-30'),
        ('H2 2022', '2022-01-01', '2022-06-30', '2022-07-01', '2022-12-31'),
        ('H1 2023', '2022-07-01', '2022-12-31', '2023-01-01', '2023-06-30'),
        ('H2 2023', '2023-01-01', '2023-06-30', '2023-07-01', '2023-12-31'),
        ('H1 2024', '2023-07-01', '2023-12-31', '2024-01-01', '2024-06-30'),
        ('H2 2024', '2024-01-01', '2024-06-30', '2024-07-01', '2024-12-31'),
        ('H1 2025', '2024-07-01', '2024-12-31', '2025-01-01', '2025-06-30'),
    ]
    
    print(f"\n{'='*80}")
    print("WALK-FORWARD (retrained every 6 months, tested out-of-sample)")
    print(f"{'='*80}")
    
    for name, tr_s, tr_e, te_s, te_e in periods:
        backtest_period(df, tr_s, tr_e, te_s, te_e, name)
    
    MODEL_DIR = "/media/SSD4T/btc-etl/models"
    os.makedirs(MODEL_DIR, exist_ok=True)
    path = os.path.join(MODEL_DIR, f'lgbm_bot_v5_{datetime.now().strftime("%Y%m%d")}.pkl')
    joblib.dump(lgb.LGBMClassifier(**LGBM_PARAMS), path)
    print(f"\nSaved: {path}")

if __name__ == "__main__":
    main()

# Fix: entrenar modelo final sobre todos los datos
print("\nTraining final model on all data...")
final_model = lgb.LGBMClassifier(**LGBM_PARAMS)
final_model.fit(df[FEATURES].values, df[TARGET].values)
path = os.path.join(MODEL_DIR, f'lgbm_bot_v5_{datetime.now().strftime("%Y%m%d")}.pkl')
joblib.dump(final_model, path)
print(f"Final model saved: {path}")
