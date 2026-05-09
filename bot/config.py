FEATURES = [
    'return_tf', 'return_4tf', 'return_24tf',
    'volatility_4tf', 'volatility_24tf',
    'volume_ratio',
    'range_pct', 'close_position',
    'momentum_4tf', 'momentum_24tf',
    'rsi_14', 'macd', 'macd_hist', 'bb_position', 'bb_width',
    'atr_pct', 'sma_cross',
    'funding_rate', 'funding_signal',
    'fees_zscore', 'fees_zscore_ma7', 'fees_zscore_change', 'zscore_regime',
    'hour', 'minute', 'day_of_week', 'is_weekend'
]
TARGET = 'target'
LGBM_PARAMS = {
    'num_leaves': 31, 'learning_rate': 0.05, 'n_estimators': 200,
    'min_data_in_leaf': 100, 'lambda_l1': 0.1, 'lambda_l2': 0.1,
    'class_weight': 'balanced', 'bagging_fraction': 0.8,
    'feature_fraction': 0.8, 'random_state': 42, 'verbose': -1, 'n_jobs': -1
}
MIN_CONFIDENCE = 0.55
INITIAL_CAPITAL = 10000
FEE_RATE = 0.00075
BASE_POSITION_SIZE = 0.005  # 0.5% por trade (455K trades)
MAX_POSITION_SIZE = 0.02
STOP_LOSS = 0.002           # -0.2%
TAKE_PROFIT = 0.005         # +0.5%
ATR_MULTIPLIER = 1.5
TRAILING_STOP_ACTIVATION = 0.003
TRAILING_STOP_DISTANCE = 0.0015
KELLY_FRACTION = 0.5
MAX_DAILY_LOSS = 0.02
