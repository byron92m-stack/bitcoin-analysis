# === FEATURES (25 total — v2 con análisis técnico) ===
FEATURES = [
    # Price & Returns (4)
    'return_1h', 'return_4h', 'return_24h',
    # Volatility (2)
    'volatility_4h', 'volatility_24h',
    # Volume (1)
    'volume_ratio',
    # Price position (2)
    'range_pct', 'close_position',
    # Momentum (2)
    'momentum_4h', 'momentum_24h',
    # Technical Analysis (7)
    'rsi_14', 'macd', 'macd_hist', 'bb_position', 'bb_width',
    'atr_pct', 'sma_cross',
    # On-chain (3)
    'fees_zscore', 'fees_zscore_ma7', 'fees_zscore_change',
    'zscore_regime',
    # Temporal (3)
    'hour', 'day_of_week', 'is_weekend'
]

TARGET = 'target'

# === RISK MANAGEMENT (v2 mejorado) ===
LGBM_PARAMS = {
    'num_leaves': 31, 'learning_rate': 0.05, 'n_estimators': 200,
    'min_data_in_leaf': 20, 'lambda_l1': 0.1, 'lambda_l2': 0.1,
    'class_weight': 'balanced', 'bagging_fraction': 0.8,
    'feature_fraction': 0.8, 'random_state': 42,
    'verbose': -1, 'n_jobs': -1
}

MIN_CONFIDENCE = 0.55  # Más exigente (antes 0.52)
INITIAL_CAPITAL = 10000
FEE_RATE = 0.00075
POSITION_SIZE = 0.015  # 1.5% por trade (más conservador)
STOP_LOSS = 0.003      # -0.3% stop loss
TAKE_PROFIT = 0.008    # +0.8% take profit
MAX_POSITIONS = 3      # Máximo 3 posiciones simultáneas
ATR_MULTIPLIER = 1.5   # Stop loss = ATR * multiplier (dinámico)
