import os, sys, joblib
import numpy as np
import lightgbm as lgb
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from config import *
from data import load_training_data
from features import build_features

def backtest_period(model, test, period_name, z_filter=False):
    probs = model.predict_proba(test[FEATURES].values)[:, 1]
    test = test.copy()
    test['prob'] = probs
    
    cap = INITIAL_CAPITAL
    trades = wins = 0
    
    for i, idx in enumerate(test.index):
        prob = test.loc[idx, 'prob']
        z = test.loc[idx, 'fees_zscore']
        
        trade_signal = prob >= MIN_CONFIDENCE
        if z_filter:
            trade_signal = trade_signal and z > 1.0
        
        if trade_signal and i + 1 < len(test):
            trades += 1
            close_now = test.loc[idx, 'close']
            close_next = test.iloc[i + 1]['close']
            actual_return = (close_next - close_now) / close_now
            actual = test.loc[idx, 'target']
            
            if actual == 1:
                pnl_pct = abs(actual_return)
                wins += 1
            else:
                pnl_pct = -min(abs(actual_return), STOP_LOSS)
            
            cap += cap * pnl_pct * POSITION_SIZE
    
    ret_pct = (cap - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100
    wr = wins / trades * 100 if trades else 0
    
    return {'period': period_name, 'return_pct': ret_pct, 'trades': trades, 'win_rate': wr, 'final_cap': cap}

def train_and_backtest():
    print("=" * 60)
    print("LightGBM Bot - 1H Timeframe + Z-Score Filter")
    print("=" * 60)
    
    print("\n1. Loading 1h data...")
    df = load_training_data()
    
    print("\n2. Building features...")
    df = build_features(df)
    print(f"   {len(df):,} rows, {len(FEATURES)} features")
    
    train = df[df['open_time'] < '2022-01-01']
    print(f"\n3. Training on {len(train):,} rows (2020-2021)")
    
    model = lgb.LGBMClassifier(**LGBM_PARAMS)
    model.fit(train[FEATURES].values, train[TARGET].values)
    
    imp = sorted(zip(FEATURES, model.feature_importances_), key=lambda x: -x[1])[:10]
    print("   Top 10:")
    for name, v in imp:
        print(f"   {name:25s} {v:8.0f}")
    
    periods = [
        ('BEAR 2022', '2022-01-01', '2022-12-31'),
        ('RECOVERY 2023', '2023-01-01', '2023-12-31'),
        ('PRE-HALVING 2024', '2024-01-01', '2024-12-31'),
        ('BULL 2025-2026', '2025-01-01', '2026-05-05'),
    ]
    
    for filter_name, z_filter in [("WITHOUT Z-Score Filter", False), ("WITH Z-Score Filter (Z > 1.0)", True)]:
        print(f"\n{'='*60}")
        print(filter_name)
        print(f"{'='*60}")
        for name, start, end in periods:
            test = df[(df['open_time'] >= start) & (df['open_time'] < end)]
            r = backtest_period(model, test, name, z_filter=z_filter)
            e = '🟢' if r['return_pct'] > 0 else '🔴'
            print(f"{e} {name:20s} | {r['return_pct']:+.2f}% | {r['trades']:,} trades | Win: {r['win_rate']:.1f}%")
    
    # Guardar en ruta correcta
    MODEL_DIR = "/media/SSD4T/btc-etl/models"
    os.makedirs(MODEL_DIR, exist_ok=True)
    path = os.path.join(MODEL_DIR, f'lgbm_bot_1h_{datetime.now().strftime("%Y%m%d")}.pkl')
    joblib.dump(model, path)
    print(f"\nSaved: {path}")

if __name__ == "__main__":
    train_and_backtest()
