import clickhouse_connect
import pandas as pd
import numpy as np

def load_training_data():
    client = clickhouse_connect.get_client(host='localhost', port=8123)
    
    # Datos 1m de Binance
    df_1m = client.query_df('''
        SELECT open_time, open, high, low, close, volume, quote_volume, trades
        FROM btc_1m
        WHERE open_time >= '2020-01-01'
        ORDER BY open_time
    ''')
    
    # Fees diarios + Z-Score
    df_fees = client.query_df('''
        SELECT toDate(toDateTime(time)) AS date, sum(fees_sats)/1e8 AS fees_btc
        FROM block_metrics
        WHERE toDate(toDateTime(time)) >= '2019-12-01'
        GROUP BY date ORDER BY date
    ''')
    
    df_fees['fees_ma30'] = df_fees['fees_btc'].rolling(30).mean()
    df_fees['fees_std30'] = df_fees['fees_btc'].rolling(30).std()
    df_fees['fees_zscore'] = (df_fees['fees_btc'] - df_fees['fees_ma30']) / df_fees['fees_std30']
    
    # Forward-fill Z-Score a 1m
    df_1m['date'] = pd.to_datetime(df_1m['open_time']).dt.date
    df_fees['date'] = pd.to_datetime(df_fees['date']).dt.date
    df_fees_map = df_fees[['date', 'fees_zscore']].dropna()
    df_1m = df_1m.merge(df_fees_map, on='date', how='left')
    df_1m['fees_zscore'] = df_1m['fees_zscore'].fillna(0)
    df_1m = df_1m.drop(columns=['date'])
    
    # AGREGAR A VELAS DE 60 MINUTOS
    df_1m['hour_bucket'] = df_1m['open_time'].dt.floor('1h')
    
    df_1h = df_1m.groupby('hour_bucket').agg(
        open=('open', 'first'),
        high=('high', 'max'),
        low=('low', 'min'),
        close=('close', 'last'),
        volume=('volume', 'sum'),
        quote_volume=('quote_volume', 'sum'),
        trades=('trades', 'sum'),
        fees_zscore=('fees_zscore', 'last')
    ).reset_index()
    
    df_1h.rename(columns={'hour_bucket': 'open_time'}, inplace=True)
    
    print(f"   1h candles: {len(df_1h):,} (from 1m: {len(df_1m):,})")
    return df_1h
