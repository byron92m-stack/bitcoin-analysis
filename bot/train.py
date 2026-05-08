"""
Phase 7 — Training Bot v4
- Funding Rate feature
- Kelly Criterion position sizing
- Trailing Stop Loss
- Max Daily Loss
"""
import os, sys, joblib
import numpy as np
import pandas as pd
import lightgbm as lgb
import matplotlib.pyplot as plt
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
from config import *
from data import load_training_data
from features import build_features

def calculate_kelly_size(win_rate, avg_win, avg_loss):
    """Kelly Criterion for position sizing."""
    if avg_loss == 0:
        return BASE_POSITION_SIZE
    kelly = (win_rate * avg_win - (1 - win_rate) * abs(avg_loss)) / (avg_win * abs(avg_loss) + 1e-9)
    kelly = max(0, min(kelly * KELLY_FRACTION, MAX_POSITION_SIZE))
    return max(BASE_POSITION_SIZE, kelly)

def calculate_metrics(trades_df, history):
    if trades_df.empty: return {}
    returns = trades_df['pnl_pct'].values
    win_rate = (returns > 0).mean()
    if len(history) > 2:
        h_returns = np.diff(history) / history[:-1]
        h_returns = h_returns[h_returns != 0]
        sharpe = np.mean(h_returns) / np.std(h_returns) * np.sqrt(24*365) if np.std(h_returns) > 0 else 0
    else:
        sharpe = 0
    downside = h_returns[h_returns < 0] if len(h_returns) > 0 else np.array([0])
    sortino = np.mean(h_returns) / np.std(downside) * np.sqrt(24*365) if len(downside) > 1 and np.std(downside) > 0 else 0
    peak = np.maximum.accumulate(history)
    dd = (np.array(history) - peak) / peak
    max_dd = abs(dd.min())
    total_return = (history[-1] - history[0]) / history[0]
    calmar = total_return / max_dd if max_dd > 0 else 0
    gross_profit = returns[returns > 0].sum()
    gross_loss = abs(returns[returns < 0].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')
    avg_win = returns[returns > 0].mean() if len(returns[returns > 0]) > 0 else 0
    avg_loss = returns[returns < 0].mean() if len(returns[returns < 0]) > 0 else 0
    expectancy = (win_rate * avg_win) - ((1 - win_rate) * abs(avg_loss))
    return {'sharpe': sharpe, 'sortino': sortino, 'calmar': calmar,
            'profit_factor': profit_factor, 'expectancy': expectancy,
            'win_rate': win_rate, 'max_dd': max_dd, 'total_return': total_return,
            'avg_win': avg_win, 'avg_loss': avg_loss}

def backtest_walkforward(df, train_start, train_end, test_start, test_end, period_name):
    train = df[(df['open_time'] >= train_start) & (df['open_time'] < train_end)]
    test = df[(df['open_time'] >= test_start) & (df['open_time'] < test_end)]
    if len(train) < 100 or len(test) < 24:
        return None, None, None
    
    model = lgb.LGBMClassifier(**LGBM_PARAMS)
    model.fit(train[FEATURES].values, train[TARGET].values)
    
    probs = model.predict_proba(test[FEATURES].values)[:, 1]
    cap = INITIAL_CAPITAL
    trades = []
    history = [cap]
    daily_pnl = 0
    last_day = None
    trailing_high = 0
    in_position = False
    entry_price = 0
    
    # Calculate Kelly size from training data
    train_probs = model.predict_proba(train[FEATURES].values)[:, 1]
    train_preds = (train_probs >= MIN_CONFIDENCE).astype(int)
    train_wins = (train_preds == train[TARGET].values).sum()
    train_wr = train_wins / len(train_preds) if len(train_preds) > 0 else 0.5
    kelly_size = calculate_kelly_size(train_wr, 0.004, 0.003)
    
    for i, (idx, prob) in enumerate(zip(test.index, probs)):
        z = test.loc[idx, 'fees_zscore']
        atr = test.loc[idx, 'atr_pct'] if 'atr_pct' in test.columns else 0.005
        current_day = test.loc[idx, 'open_time'].date()
        
        # Reset daily P&L
        if last_day != current_day:
            daily_pnl = 0
            last_day = current_day
        
        # Max daily loss check
        if daily_pnl <= -MAX_DAILY_LOSS * cap:
            in_position = False
        
        if prob >= MIN_CONFIDENCE and z > -1.0 and i + 1 < len(test) and daily_pnl > -MAX_DAILY_LOSS * cap:
            close_now = test.loc[idx, 'close']
            close_next = test.iloc[i + 1]['close']
            actual_return = (close_next - close_now) / close_now
            actual = test.loc[idx, 'target']
            
            # Dynamic stop loss (ATR-based)
            dynamic_sl = min(STOP_LOSS, atr * ATR_MULTIPLIER / 100)
            dynamic_tp = TAKE_PROFIT
            
            # Trailing stop
            if in_position and close_now > trailing_high:
                trailing_high = close_now
            
            if in_position and (close_now - trailing_high) / trailing_high < -TRAILING_STOP_DISTANCE:
                actual_return = (close_now - entry_price) / entry_price
                in_position = False
            
            if not in_position:
                entry_price = close_now
                trailing_high = close_now
                in_position = True
            
            if actual == 1:
                pnl_pct = min(abs(actual_return), dynamic_tp)
            else:
                pnl_pct = -min(abs(actual_return), dynamic_sl)
            
            trade_capital = cap * kelly_size
            cap += trade_capital * pnl_pct
            daily_pnl += trade_capital * pnl_pct
            
            trades.append({
                'time': test.loc[idx, 'open_time'], 'entry': close_now,
                'exit': close_next, 'return': actual_return,
                'pnl_pct': pnl_pct, 'win': actual == 1,
                'prob': prob, 'zscore': z, 'kelly_size': kelly_size
            })
            history.append(cap)
    
    return pd.DataFrame(trades), history, model

def backtest_multi_period(df):
    periods = [
        ('H2 2021', '2021-01-01', '2021-06-30', '2021-07-01', '2021-12-31'),
        ('H1 2022', '2021-07-01', '2021-12-31', '2022-01-01', '2022-06-30'),
        ('H2 2022', '2022-01-01', '2022-06-30', '2022-07-01', '2022-12-31'),
        ('H1 2023', '2022-07-01', '2022-12-31', '2023-01-01', '2023-06-30'),
        ('H2 2023', '2023-01-01', '2023-06-30', '2023-07-01', '2023-12-31'),
        ('H1 2024', '2023-07-01', '2023-12-31', '2024-01-01', '2024-06-30'),
        ('H2 2024', '2024-01-01', '2024-06-30', '2024-07-01', '2024-12-31'),
        ('H1 2025', '2024-07-01', '2024-12-31', '2025-01-01', '2025-06-30'),
        ('H2 2025+', '2025-01-01', '2025-06-30', '2025-07-01', '2026-05-05'),
    ]
    
    all_trades = []
    all_history = [INITIAL_CAPITAL]
    
    print(f"\n{'='*90}")
    print("WALK-FORWARD v4 (Kelly sizing + Trailing Stop + Max Daily Loss)")
    print(f"{'='*90}")
    print(f"{'Period':<15} {'Return':>8} {'Trades':>7} {'Win':>7} {'Sharpe':>8} {'MaxDD':>8} {'PF':>8}")
    print("-" * 90)
    
    for name, tr_start, tr_end, te_start, te_end in periods:
        trades_df, history, model = backtest_walkforward(df, tr_start, tr_end, te_start, te_end, name)
        if trades_df is not None and not trades_df.empty:
            all_trades.append(trades_df)
            last_cap = all_history[-1]
            scaled_history = [last_cap * (h / history[0]) for h in history[1:]]
            all_history.extend(scaled_history)
            metrics = calculate_metrics(trades_df, history)
            ret = metrics['total_return'] * 100
            print(f"{name:<15} {ret:>+7.2f}% {len(trades_df):>6}  {metrics['win_rate']*100:>5.1f}% "
                  f"{metrics['sharpe']:>7.2f} {metrics['max_dd']*100:>7.2f}% {metrics['profit_factor']:>7.2f}")
    
    if all_trades:
        all_trades_df = pd.concat(all_trades, ignore_index=True)
        final_metrics = calculate_metrics(all_trades_df, all_history)
        print(f"\n{'='*90}")
        print("WALK-FORWARD v4 SUMMARY")
        print(f"{'='*90}")
        print(f"  Total Return:  {final_metrics['total_return']*100:+.2f}%")
        print(f"  Total Trades:  {len(all_trades_df):,}")
        print(f"  Win Rate:      {final_metrics['win_rate']*100:.1f}%")
        print(f"  Sharpe:        {final_metrics['sharpe']:.2f}")
        print(f"  Sortino:       {final_metrics['sortino']:.2f}")
        print(f"  Calmar:        {final_metrics['calmar']:.2f}")
        print(f"  Max DD:        {final_metrics['max_dd']*100:.2f}%")
        print(f"  Profit Factor: {final_metrics['profit_factor']:.2f}")
        print(f"  Expectancy:    {final_metrics['expectancy']*100:.4f}% per trade")
        print(f"  Avg Win:       {final_metrics['avg_win']*100:.4f}%")
        print(f"  Avg Loss:      {final_metrics['avg_loss']*100:.4f}%")
        
        os.makedirs('/media/SSD4T/btc-etl/bot/logs', exist_ok=True)
        all_trades_df.to_csv('/media/SSD4T/btc-etl/bot/logs/trades_v4.csv', index=False)
        print(f"\n  Trades saved: bot/logs/trades_v4.csv")
        
        fig, ax = plt.subplots(figsize=(14, 6))
        ax.plot(all_history, color='#1f77b4', linewidth=1.5)
        ax.fill_between(range(len(all_history)), INITIAL_CAPITAL, all_history,
                        where=np.array(all_history) >= INITIAL_CAPITAL, alpha=0.3, color='green')
        ax.fill_between(range(len(all_history)), INITIAL_CAPITAL, all_history,
                        where=np.array(all_history) < INITIAL_CAPITAL, alpha=0.3, color='red')
        ax.axhline(y=INITIAL_CAPITAL, color='black', linestyle='--', linewidth=0.5)
        ax.set_title('Equity Curve — Walk-Forward v4 (Kelly + Trailing Stop)', fontsize=14, fontweight='bold')
        ax.set_xlabel('Trade Number'), ax.set_ylabel('Capital ($)'), ax.grid(True, alpha=0.3)
        plt.tight_layout()
        os.makedirs('/media/SSD4T/btc-etl/notebooks/images', exist_ok=True)
        plt.savefig('/media/SSD4T/btc-etl/notebooks/images/equity_curve_v4.png', dpi=300, bbox_inches='tight')
        print("  Equity curve: notebooks/images/equity_curve_v4.png")
    
    return all_trades_df

def train_and_backtest():
    print("=" * 60)
    print("LightGBM Bot v4 — Kelly + Trailing Stop + Funding Rate")
    print("=" * 60)
    
    print("\n1. Loading 1h data...")
    df = load_training_data()
    
    print("\n2. Building features (v4)...")
    df = build_features(df)
    print(f"   {len(df):,} rows, {len(FEATURES)} features")
    
    print(f"\n3. Feature importance...")
    temp_model = lgb.LGBMClassifier(**LGBM_PARAMS)
    temp_model.fit(df.iloc[:10000][FEATURES].values, df.iloc[:10000][TARGET].values)
    imp = sorted(zip(FEATURES, temp_model.feature_importances_), key=lambda x: -x[1])[:10]
    for name, v in imp:
        print(f"   {name:25s} {v:8.0f}")
    
    backtest_multi_period(df)
    
    MODEL_DIR = "/media/SSD4T/btc-etl/models"
    os.makedirs(MODEL_DIR, exist_ok=True)
    path = os.path.join(MODEL_DIR, f'lgbm_bot_v4_{datetime.now().strftime("%Y%m%d")}.pkl')
    joblib.dump(temp_model, path)
    print(f"\nSaved: {path}")

if __name__ == "__main__":
    train_and_backtest()
