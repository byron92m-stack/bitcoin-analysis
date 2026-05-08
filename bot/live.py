"""
Phase 7 — Live Paper Trading Bot v3
WebSocket + Predicción cada 1h con Technical Analysis.
"""
import os, sys, json, time, joblib, glob
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from websocket import create_connection

sys.path.insert(0, os.path.dirname(__file__))
from config import FEATURES, MIN_CONFIDENCE

def load_latest_model():
    model_dir = '/media/SSD4T/btc-etl/models'
    models = sorted(glob.glob(os.path.join(model_dir, 'lgbm_bot_v3_*.pkl')))
    if not models:
        print("❌ No hay modelo v3. Ejecutá: python bot/train.py")
        sys.exit(1)
    latest = models[-1]
    print(f"✅ Cargando: {os.path.basename(latest)}")
    return joblib.load(latest)

def build_live_features(df_1h, fees_zscore):
    """Features completas v3 con Technical Analysis."""
    df = df_1h.copy()
    
    # Target dummy (no se usa en vivo)
    df['target'] = 0
    
    # Returns
    df['return_1h'] = df['close'].pct_change()
    df['return_4h'] = df['close'].pct_change(4)
    df['return_24h'] = df['close'].pct_change(24)
    df['log_return'] = np.log(df['close'] / df['close'].shift(1))
    
    # Volatility
    df['volatility_4h'] = df['log_return'].rolling(4).std()
    df['volatility_24h'] = df['log_return'].rolling(24).std()
    
    # Volume
    df['volume_ma4'] = df['volume'].rolling(4).mean()
    df['volume_ma24'] = df['volume'].rolling(24).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma24']
    
    # Price position
    df['range_pct'] = (df['high'] - df['low']) / df['open'] * 100
    df['close_position'] = (df['close'] - df['low']) / (df['high'] - df['low'] + 1e-9)
    
    # Momentum
    df['momentum_4h'] = df['close'] - df['close'].shift(4)
    df['momentum_24h'] = df['close'] - df['close'].shift(24)
    
    # RSI
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df['rsi_14'] = 100 - (100 / (1 + rs))
    
    # MACD
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']
    
    # Bollinger
    df['bb_middle'] = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['bb_position'] = (df['close'] - (df['bb_middle'] - 2*bb_std)) / (4*bb_std + 1e-9)
    df['bb_width'] = (4*bb_std) / df['bb_middle']
    
    # ATR
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift(1))
    low_close = np.abs(df['low'] - df['close'].shift(1))
    true_range = np.maximum(high_low, np.maximum(high_close, low_close))
    df['atr_pct'] = true_range.rolling(14).mean() / df['close'] * 100
    
    # SMA
    df['sma_10'] = df['close'].rolling(10).mean()
    df['sma_50'] = df['close'].rolling(50).mean()
    df['sma_cross'] = (df['sma_10'] > df['sma_50']).astype(int)
    
    # On-chain
    df['fees_zscore'] = fees_zscore
    df['fees_zscore_ma7'] = fees_zscore
    df['fees_zscore_change'] = 0
    df['zscore_regime'] = 0
    if fees_zscore > 1.0: df['zscore_regime'] = 1
    if fees_zscore > 2.0: df['zscore_regime'] = 2
    if fees_zscore < -1.0: df['zscore_regime'] = -1
    
    # Temporal
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
                FROM block_metrics WHERE toDate(toDateTime(time)) >= today() - 60
            ) LIMIT 1
        ''')
        return result.first_row[0] if result.first_row else 0
    except:
        return 0

def main():
    print("=" * 60)
    print("Phase 7 - Live Trading Bot v3 (Technical Analysis)")
    print("=" * 60)
    
    model = load_latest_model()
    candles = []
    ws = create_connection("wss://stream.binance.com:9443/ws/btcusdt@kline_1h")
    print("Connected. Waiting for 1h candles...\n")
    print(f"{'Time':<8} {'Price':<12} {'Signal':<8} {'Conf':<8} {'Z':<8} {'RSI':<8} {'Action'}")
    print("-" * 75)
    
    while True:
        try:
            data = json.loads(ws.recv())
            kline = data['k']
            if kline['x']:
                candle = {
                    'open_time': pd.Timestamp(kline['t'], unit='ms'),
                    'open': float(kline['o']), 'high': float(kline['h']),
                    'low': float(kline['l']), 'close': float(kline['c']),
                    'volume': float(kline['v']), 'quote_volume': float(kline['q']),
                    'trades': int(kline['n'])
                }
                candles.append(candle)
                if len(candles) > 60: candles = candles[-60:]
                
                if len(candles) >= 50:
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
                        rsi_str = f"{last_row['rsi_14'].values[0]:.0f}" if 'rsi_14' in last_row.columns else "—"
                        
                        if pred == 1:
                            action = "ENTER" if fees_z > 1.0 else "Z low"
                        else:
                            action = "—"
                        
                        print(f"{time_str:<8} ${float(price):<11,.0f} {signal:<8} {conf:<8} {z_str:<8} {rsi_str:<8} {action}")
        except KeyboardInterrupt:
            print("\nBot stopped.")
            ws.close()
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()
