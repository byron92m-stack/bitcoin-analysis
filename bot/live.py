"""
Phase 7 - Live Trading Bot v5 (5m) — REST API
Sin WebSocket. Sin desconexiones. Simple y robusto.
"""
import os, sys, time, joblib, glob, csv, warnings
warnings.filterwarnings('ignore')
import pandas as pd, numpy as np
import clickhouse_connect, requests
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
from config import FEATURES, MIN_CONFIDENCE

SIGNALS_FILE = '/media/SSD4T/btc-etl/bot/logs/live_signals.csv'

def load_latest_model():
    model_dir = '/media/SSD4T/btc-etl/models'
    models = sorted(glob.glob(os.path.join(model_dir, 'lgbm_bot_v5_*.pkl')))
    if not models: print("No model"); sys.exit(1)
    print(f"Model: {os.path.basename(models[-1])}")
    return joblib.load(models[-1])

def fetch_last_200_candles():
    """Obtiene últimas 200 velas 5m de Binance REST API (gratis, sin key)."""
    url = "https://api.binance.com/api/v3/klines"
    candles = []
    end_time = int(time.time() * 1000)
    
    for _ in range(3):
        params = {"symbol": "BTCUSDT", "interval": "5m", "limit": 200, "endTime": end_time}
        try:
            resp = requests.get(url, params=params, timeout=10)
            data = resp.json()
            if not data or not isinstance(data, list): break
            
            batch = []
            for k in data:
                batch.append({
                    'open_time': pd.Timestamp(k[0], unit='ms'),
                    'open': float(k[1]), 'high': float(k[2]),
                    'low': float(k[3]), 'close': float(k[4]),
                    'volume': float(k[5]),
                    'quote_volume': float(k[7]), 'trades': int(k[8])
                })
            candles = batch + candles
            end_time = int(data[0][0]) - 1
            if len(candles) >= 200: break
        except Exception as e:
            print(f"  Fetch error: {e}")
            time.sleep(5)
    
    candles = candles[-200:]
    return candles

def build_live_features(df_5m, fees_zscore):
    df = df_5m.copy()
    df['target'] = 0
    df['return_tf'] = df['close'].pct_change()
    df['return_4tf'] = df['close'].pct_change(4)
    df['return_24tf'] = df['close'].pct_change(24)
    df['log_return'] = np.log(df['close'] / df['close'].shift(1))
    df['volatility_4tf'] = df['log_return'].rolling(4).std()
    df['volatility_24tf'] = df['log_return'].rolling(24).std()
    df['volume_ma24'] = df['volume'].rolling(24).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma24']
    df['range_pct'] = (df['high'] - df['low']) / df['open'] * 100
    df['close_position'] = (df['close'] - df['low']) / (df['high'] - df['low'] + 1e-9)
    df['momentum_4tf'] = df['close'] - df['close'].shift(4)
    df['momentum_24tf'] = df['close'] - df['close'].shift(24)
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    df['rsi_14'] = 100 - (100 / (1 + gain / (loss + 1e-9)))
    ema12, ema26 = df['close'].ewm(span=12, adjust=False).mean(), df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['macd_hist'] = df['macd'] - df['macd'].ewm(span=9, adjust=False).mean()
    df['bb_middle'] = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['bb_position'] = (df['close'] - (df['bb_middle'] - 2*bb_std)) / (4*bb_std + 1e-9)
    df['bb_width'] = (4*bb_std) / df['bb_middle']
    tr = np.maximum(df['high'] - df['low'], np.maximum(np.abs(df['high'] - df['close'].shift(1)), np.abs(df['low'] - df['close'].shift(1))))
    df['atr_pct'] = tr.rolling(14).mean() / df['close'] * 100
    df['sma_10'], df['sma_50'] = df['close'].rolling(10).mean(), df['close'].rolling(50).mean()
    df['sma_cross'] = (df['sma_10'] > df['sma_50']).astype(int)
    df['funding_rate'], df['funding_signal'] = 0, 0
    df['fees_zscore'] = fees_zscore
    df['fees_zscore_ma7'] = fees_zscore
    df['fees_zscore_change'] = 0
    df['zscore_regime'] = 0
    if fees_zscore > 1.0: df['zscore_regime'] = 1
    if fees_zscore > 2.0: df['zscore_regime'] = 2
    if fees_zscore < -1.0: df['zscore_regime'] = -1
    now = datetime.now(timezone.utc)
    df['hour'], df['minute'] = now.hour, now.minute
    df['day_of_week'] = now.weekday()
    df['is_weekend'] = 1 if now.weekday() >= 5 else 0
    return df

def get_fees_zscore():
    try:
        client = clickhouse_connect.get_client(host='localhost', port=8123)
        result = client.query("""SELECT (avg_today - avg_30) / nullIf(std_30, 0) AS zscore FROM (SELECT (SELECT avg(fees_sats/1e8) FROM block_metrics WHERE toDate(toDateTime(time)) = today()) AS avg_today, (SELECT avg(fees_sats/1e8) FROM block_metrics WHERE toDate(toDateTime(time)) >= today() - 30) AS avg_30, (SELECT stddevPop(fees_sats/1e8) FROM block_metrics WHERE toDate(toDateTime(time)) >= today() - 30) AS std_30)""")
        return result.first_row[0] if result.first_row and result.first_row[0] else 0
    except: return 0

def init_signals_log():
    if not Path(SIGNALS_FILE).exists():
        with open(SIGNALS_FILE, 'w', newline='') as f:
            csv.writer(f).writerow(['timestamp', 'price', 'signal', 'confidence', 'zscore', 'rsi'])

def log_signal(ts, price, signal, conf, z, rsi):
    with open(SIGNALS_FILE, 'a', newline='') as f:
        csv.writer(f).writerow([ts, price, signal, conf, z, rsi])

def wait_until_next_5min():
    """Espera hasta el próximo múltiplo de 5 minutos."""
    now = datetime.now()
    next_minute = (now.minute // 5 + 1) * 5
    if next_minute >= 60:
        next_minute = 0
        next_hour = now.hour + 1
        if next_hour >= 24:
            next_hour = 0
        next_5 = now.replace(hour=next_hour, minute=next_minute, second=5, microsecond=0)
    else:
        next_5 = now.replace(minute=next_minute, second=5, microsecond=0)
    wait = (next_5 - now).total_seconds()
    if wait > 0:
        time.sleep(wait)

def main():
    print("=" * 60)
    print("Phase 7 - Live Trading Bot v5 (5m) — REST API")
    print("=" * 60)
    
    init_signals_log()
    model = load_latest_model()
    
    print(f"\n{'Time':<8} {'Price':<12} {'Signal':<8} {'Conf':<8} {'Z':<8} {'RSI':<8}")
    print("-" * 65)
    
    while True:
        try:
            wait_until_next_5min()
            candles = fetch_last_200_candles()
            if not candles:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] No candles fetched. Retrying...")
                time.sleep(30)
                continue
            
            df_5m = pd.DataFrame(candles)
            fees_z = get_fees_zscore()
            df_f = build_live_features(df_5m, fees_z)
            last_row = df_f.iloc[-1:][FEATURES]
            
            if not last_row.isna().any().any():
                prob = model.predict_proba(last_row.values)[0, 1]
                pred = 1 if prob >= MIN_CONFIDENCE else 0
                time_str = datetime.now().strftime("%H:%M:%S")
                price = candles[-1]['close']
                signal = "LONG" if pred == 1 else "WAIT"
                conf = f"{prob*100:.1f}%"
                z_str = f"{fees_z:.2f}"
                rsi_str = f"{last_row['rsi_14'].values[0]:.0f}"
                
                print(f"{time_str:<8} ${price:<11,.0f} {signal:<8} {conf:<8} {z_str:<8} {rsi_str:<8}")
                log_signal(time_str, price, signal, prob, fees_z, last_row['rsi_14'].values[0])
        
        except KeyboardInterrupt:
            print(f"\nBot stopped. Signals: {SIGNALS_FILE}")
            break
        except Exception as e:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] Error: {e}")
            time.sleep(30)

if __name__ == "__main__":
    main()
