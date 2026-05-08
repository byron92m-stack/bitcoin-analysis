import numpy as np

def build_features(df):
    # Target: ¿sube la próxima hora?
    df['target'] = (df['close'].shift(-1) > df['close']).astype(int)
    
    # Returns en diferentes horizontes
    df['return_1h'] = df['close'].pct_change()
    df['return_4h'] = df['close'].pct_change(4)
    df['return_24h'] = df['close'].pct_change(24)
    
    # Volatility
    df['log_return'] = np.log(df['close'] / df['close'].shift(1))
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
    
    # On-chain features
    df['fees_zscore_ma7'] = df['fees_zscore'].rolling(7).mean()
    df['fees_zscore_change'] = df['fees_zscore'] - df['fees_zscore'].shift(24)
    
    # Z-Score regime
    df['zscore_regime'] = 0
    df.loc[df['fees_zscore'] > 1.5, 'zscore_regime'] = 1
    df.loc[df['fees_zscore'] > 2.0, 'zscore_regime'] = 2
    df.loc[df['fees_zscore'] < -1.5, 'zscore_regime'] = -1
    
    # Temporal
    df['hour'] = df['open_time'].dt.hour
    df['day_of_week'] = df['open_time'].dt.dayofweek
    df['is_weekend'] = (df['day_of_week'] >= 5).astype(int)
    
    return df.dropna()
