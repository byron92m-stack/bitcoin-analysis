"""
Phase 7 — Live Paper Trading Bot
"""
import os, sys, json, time, joblib, glob
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from websocket import create_connection

sys.path.insert(0, os.path.dirname(__file__))
from config import *

def load_latest_model():
    # Path absoluto
    model_dir = '/media/SSD4T/btc-etl/models'
    models = sorted(glob.glob(os.path.join(model_dir, 'lgbm_bot_1h_*.pkl')))
    print(f"   Buscando en: {model_dir}")
    print(f"   Encontrados: {len(models)} modelos")
    if not models:
        print("❌ Ejecutá primero: cd /media/SSD4T/btc-etl && python bot/train.py")
        sys.exit(1)
    latest = models[-1]
    print(f"✅ Cargando: {os.path.basename(latest)}")
    return joblib.load(latest)

def build_live_features(df_1h, fees_zscore):
    df = df_1h.copy()
    df['return_1h'] = df['close'].pct_change()
    df['return_4h'] = df['close'].pct_change(4)
    df['return_24h'] = df['close'].pct_change(24)
    df['log_return'] = np.log(df['close'] / df['close'].shift(1))
    df['volatility_4h'] = df['log_return'].rolling(4).std()
    df['volatility_24h'] = df['log_return'].rolling(24).std()
    df['volume_ma4'] = df['volume'].rolling(4).mean()
    df['volume_ma24'] = df['volume'].rolling(24).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma24']
    df['range_pct'] = (df['high'] - df['low']) / df['open'] * 100
    df['close_position'] = (df['close'] - df['low']) / (df['high'] - df['low'] + 1e-9)
    df['momentum_4h'] = df['close'] - df['close'].shift(4)
    df['momentum_24h'] = df['close'] - df['close'].shift(24)
    df['fees_zscore'] = fees_zscore
    df['fees_zscore_ma7'] = fees_zscore
    df['fees_zscore_change'] = 0
    df['zscore_regime'] = 0
    if fees_zscore > 1.5: df['zscore_regime'] = 1
    if fees_zscore > 2.0: df['zscore_regime'] = 2
    now = datetime.now(timezone.utc)
    df['hour'] = now.hour
    df['day_of_week'] = now.weekday()
    df['is_weekend'] = 1 if now.weekday() >= 5 else 0
    return df

def get_fees_zscore():
    try:
        import clickhouse_connect
        client = clickhouse_connect.get_client(host='localhost', port=8123)
        result = client.query('''
            SELECT (sum(fees_sats)/1e8 - avg_30) / nullIf(std_30, 0) AS fees_zscore
            FROM (
                SELECT fees_sats,
                    avg(fees_sats/1e8) OVER (ORDER BY toDate(toDateTime(time))
                        ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) AS avg_30,
                    stddevPop(fees_sats/1e8) OVER (ORDER BY toDate(toDateTime(time))
                        ROWS BETWEEN 29 PRECEDING AND CURRENT ROW) AS std_30
                FROM block_metrics
                WHERE toDate(toDateTime(time)) >= today() - 60
            )
            LIMIT 1
        ''')
        return result.first_row[0] if result.first_row else 0
    except:
        return 0

def main():
    print("=" * 60)
    print("Phase 7 - Live Paper Trading Bot")
    print("=" * 60)
    
    model = load_latest_model()
    
    candles = []
    ws = create_connection("wss://stream.binance.com:9443/ws/btcusdt@kline_1h")
    print("Connected. Waiting for 1h candles...\n")
    
    print(f"{'Time':<8} {'Price':<12} {'Signal':<8} {'Conf':<8} {'Z-Score':<10} {'Action'}")
    print("-" * 65)
    
    while True:
        try:
            data = json.loads(ws.recv())
            kline = data['k']
            
            if kline['x']:
                candle = {
                    'open_time': pd.Timestamp(kline['t'], unit='ms'),
                    'open': float(kline['o']),
                    'high': float(kline['h']),
                    'low': float(kline['l']),
                    'close': float(kline['c']),
                    'volume': float(kline['v']),
                    'quote_volume': float(kline['q']),
                    'trades': int(kline['n'])
                }
                candles.append(candle)
                if len(candles) > 48: candles = candles[-48:]
                
                if len(candles) >= 25:
                    df_1h = pd.DataFrame(candles)
                    fees_z = get_fees_zscore()
                    df_features = build_live_features(df_1h, fees_z)
                    last_row = df_features.iloc[-1:][FEATURES]
                    
                    if not last_row.isna().any().any():
                        prob = model.predict_proba(last_row.values)[0, 1]
                        pred = 1 if prob >= MIN_CONFIDENCE else 0
                        
                        time_str = datetime.now().strftime("%H:%M:%S")
                        price = kline['c']
                        signal = "LONG" if pred == 1 else "WAIT"
                        conf = f"{prob*100:.1f}%"
                        z_str = f"{fees_z:.2f}"
                        action = "ENTER" if (pred == 1 and fees_z > 1.0) else ("Z low" if pred == 1 else "-")
                        
                        print(f"{time_str:<8} ${float(price):<11,.0f} {signal:<8} {conf:<8} {z_str:<10} {action}")
                        
        except KeyboardInterrupt:
            print("\nBot stopped.")
            ws.close()
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()
