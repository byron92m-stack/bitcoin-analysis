"""
Feature engineering — v2 con análisis técnico + risk management.
"""
import numpy as np
import pandas as pd

def build_features(df):
    # === TARGET ===
    df['target'] = (df['close'].shift(-1) > df['close']).astype(int)
    
    # === PRICE RETURNS ===
    df['return_1h'] = df['close'].pct_change()
    df['return_4h'] = df['close'].pct_change(4)
    df['return_24h'] = df['close'].pct_change(24)
    df['log_return'] = np.log(df['close'] / df['close'].shift(1))
    
    # === VOLATILITY ===
    df['volatility_4h'] = df['log_return'].rolling(4).std()
    df['volatility_24h'] = df['log_return'].rolling(24).std()
    
    # === VOLUME ===
    df['volume_ma4'] = df['volume'].rolling(4).mean()
    df['volume_ma24'] = df['volume'].rolling(24).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma24']
    
    # === PRICE POSITION ===
    df['range_pct'] = (df['high'] - df['low']) / df['open'] * 100
    df['close_position'] = (df['close'] - df['low']) / (df['high'] - df['low'] + 1e-9)
    
    # === MOMENTUM ===
    df['momentum_4h'] = df['close'] - df['close'].shift(4)
    df['momentum_24h'] = df['close'] - df['close'].shift(24)
    
    # === ANÁLISIS TÉCNICO ===
    
    # RSI (Relative Strength Index) — 14 períodos
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / (loss + 1e-9)
    df['rsi_14'] = 100 - (100 / (1 + rs))
    
    # MACD (Moving Average Convergence Divergence)
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']
    
    # Bollinger Bands (20 períodos, 2 desviaciones)
    df['bb_middle'] = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['bb_upper'] = df['bb_middle'] + 2 * bb_std
    df['bb_lower'] = df['bb_middle'] - 2 * bb_std
    df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'] + 1e-9)
    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / df['bb_middle']
    
    # ATR (Average True Range) — 14 períodos
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift(1))
    low_close = np.abs(df['low'] - df['close'].shift(1))
    true_range = np.maximum(high_low, np.maximum(high_close, low_close))
    df['atr_14'] = true_range.rolling(14).mean()
    df['atr_pct'] = df['atr_14'] / df['close'] * 100
    
    # SMA crosses
    df['sma_10'] = df['close'].rolling(10).mean()
    df['sma_50'] = df['close'].rolling(50).mean()
    df['sma_cross'] = (df['sma_10'] > df['sma_50']).astype(int)
    
    # === ON-CHAIN (Phase 3) ===
    df['fees_zscore_ma7'] = df['fees_zscore'].rolling(7).mean()
    df['fees_zscore_change'] = df['fees_zscore'] - df['fees_zscore'].shift(24)
    
    # Z-Score regime
    df['zscore_regime'] = 0
    df.loc[df['fees_zscore'] > 1.0, 'zscore_regime'] = 1
    df.loc[df['fees_zscore'] > 2.0, 'zscore_regime'] = 2
    df.loc[df['fees_zscore'] < -1.0, 'zscore_regime'] = -1
    
    # === TEMPORAL ===
    df['hour'] = df['open_time'].dt.hour
    df['day_of_week'] = df['open_time'].dt.dayofweek
    df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)
    
    return df.dropna()
