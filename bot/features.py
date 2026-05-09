import numpy as np
import pandas as pd

def build_features(df):
    df['target'] = (df['close'].shift(-1) > df['close']).astype(int)
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
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = ema12 - ema26
    df['macd_hist'] = df['macd'] - df['macd'].ewm(span=9, adjust=False).mean()
    df['bb_middle'] = df['close'].rolling(20).mean()
    bb_std = df['close'].rolling(20).std()
    df['bb_position'] = (df['close'] - (df['bb_middle'] - 2*bb_std)) / (4*bb_std + 1e-9)
    df['bb_width'] = (4*bb_std) / df['bb_middle']
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift(1))
    low_close = np.abs(df['low'] - df['close'].shift(1))
    true_range = np.maximum(high_low, np.maximum(high_close, low_close))
    df['atr_pct'] = true_range.rolling(14).mean() / df['close'] * 100
    df['sma_10'] = df['close'].rolling(10).mean()
    df['sma_50'] = df['close'].rolling(50).mean()
    df['sma_cross'] = (df['sma_10'] > df['sma_50']).astype(int)
    if 'funding_rate' not in df.columns: df['funding_rate'] = 0
    df['funding_signal'] = 0
    df['fees_zscore_ma7'] = df['fees_zscore'].rolling(7).mean()
    df['fees_zscore_change'] = df['fees_zscore'] - df['fees_zscore'].shift(1)
    df['zscore_regime'] = 0
    df.loc[df['fees_zscore'] > 1.0, 'zscore_regime'] = 1
    df.loc[df['fees_zscore'] > 2.0, 'zscore_regime'] = 2
    df.loc[df['fees_zscore'] < -1.0, 'zscore_regime'] = -1
    df['hour'] = df['open_time'].dt.hour
    df['minute'] = df['open_time'].dt.minute
    df['day_of_week'] = df['open_time'].dt.dayofweek
    df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)
    return df.dropna()
