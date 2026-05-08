# === FEATURES (26 total — v4 con Funding Rate) ===
FEATURES = [
    # Price & Returns
    'return_1h', 'return_4h', 'return_24h',
    # Volatility
    'volatility_4h', 'volatility_24h',
    # Volume
    'volume_ratio',
    # Price position
    'range_pct', 'close_position',
    # Momentum
    'momentum_4h', 'momentum_24h',
    # Technical Analysis
    'rsi_14', 'macd', 'macd_hist', 'bb_position', 'bb_width',
    'atr_pct', 'sma_cross',
    # Funding Rate
    'funding_rate', 'funding_signal',
    # On-chain
    'fees_zscore', 'fees_zscore_ma7', 'fees_zscore_change', 'zscore_regime',
    # Temporal
    'hour', 'day_of_week', 'is_weekend'
]

TARGET = 'target'

# === RISK MANAGEMENT v4 (Kelly + Trailing Stop) ===
LGBM_PARAMS = {
    'num_leaves': 31, 'learning_rate': 0.05, 'n_estimators': 200,
    'min_data_in_leaf': 20, 'lambda_l1': 0.1, 'lambda_l2': 0.1,
    'class_weight': 'balanced', 'bagging_fraction': 0.8,
    'feature_fraction': 0.8, 'random_state': 42,
    'verbose': -1, 'n_jobs': -1
}

MIN_CONFIDENCE = 0.55
INITIAL_CAPITAL = 10000
FEE_RATE = 0.00075
BASE_POSITION_SIZE = 0.015   # 1.5% base
MAX_POSITION_SIZE = 0.04     # 4% max (Kelly scaling)
STOP_LOSS = 0.003
TAKE_PROFIT = 0.008
ATR_MULTIPLIER = 1.5
TRAILING_STOP_ACTIVATION = 0.004  # Activar trailing stop when +0.4%
TRAILING_STOP_DISTANCE = 0.002    # Mantener 0.2% debajo del máximo
KELLY_FRACTION = 0.5              # Half-Kelly (conservador)
MAX_DAILY_LOSS = 0.02             # 2% daily loss limit
