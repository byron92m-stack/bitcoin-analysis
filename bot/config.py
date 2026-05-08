FEATURES = [
    'return_1h', 'return_4h', 'return_24h',
    'volatility_4h', 'volatility_24h',
    'volume_ratio',
    'range_pct', 'close_position',
    'momentum_4h', 'momentum_24h',
    'fees_zscore', 'fees_zscore_ma7', 'fees_zscore_change',
    'zscore_regime',
    'hour', 'day_of_week', 'is_weekend'
]
TARGET = 'target'
LGBM_PARAMS = {
    'num_leaves': 31, 'learning_rate': 0.05, 'n_estimators': 200,
    'min_data_in_leaf': 20, 'lambda_l1': 0.1, 'lambda_l2': 0.1,
    'class_weight': 'balanced', 'bagging_fraction': 0.8,
    'feature_fraction': 0.8, 'random_state': 42,
    'verbose': -1, 'n_jobs': -1
}
MIN_CONFIDENCE = 0.52
INITIAL_CAPITAL = 10000
FEE_RATE = 0.00075
POSITION_SIZE = 0.02  # 2% por trade (menos trades en 1h)
STOP_LOSS = 0.005     # -0.5%
