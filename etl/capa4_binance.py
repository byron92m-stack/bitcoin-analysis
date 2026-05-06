#!/usr/bin/env python3
"""
CAPA 4 — Binance BTC/USDT (1m + 1d)
Descarga desde API, agrega a diario.
Menú: 1=Reset (borra 1m+1d), 2=Continuar (descarga 1m + regenera 1d), 3=Rollback (borra batch 1m + regenera 1d).
250 velas por batch. Barra tqdm. Schema fijo. Sin duplicados.
"""
import os
import time
import json
import shutil
import logging
from datetime import datetime, timezone

import pandas as pd
import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import requests
from tqdm import tqdm

# ============================================================
# CONFIG
# ============================================================
PROJECT_ROOT = "/media/SSD4T/btc-etl"
CAPA4_DIR = os.path.join(PROJECT_ROOT, "parquet", "capa4_binance")
DIR_1M = os.path.join(CAPA4_DIR, "1m")
DIR_1D = os.path.join(CAPA4_DIR, "1d")

STATE_FILE = os.path.join(PROJECT_ROOT, "state_capa4_binance.json")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_FILE = os.path.join(LOG_DIR, "capa4_binance.log")

SYMBOL = "BTCUSDT"
INTERVAL = "1m"
LIMIT = 1000
SLEEP_TIME = 0.5

# ============================================================
# SCHEMA FIJO (tz-naive)
# ============================================================
SCHEMA_1M = pa.schema([
    pa.field("open_time", pa.timestamp("ms")),
    pa.field("open", pa.float64()),
    pa.field("high", pa.float64()),
    pa.field("low", pa.float64()),
    pa.field("close", pa.float64()),
    pa.field("volume", pa.float64()),
    pa.field("close_time", pa.timestamp("ms")),
    pa.field("quote_volume", pa.float64()),
    pa.field("trades", pa.int64()),
])

SCHEMA_1D = pa.schema([
    pa.field("date", pa.date32()),
    pa.field("open", pa.float64()),
    pa.field("high", pa.float64()),
    pa.field("low", pa.float64()),
    pa.field("close", pa.float64()),
    pa.field("volume_btc", pa.float64()),
    pa.field("volume_usdt", pa.float64()),
    pa.field("trades", pa.int64()),
    pa.field("num_candles", pa.int64()),
    pa.field("return_daily", pa.float64()),
    pa.field("log_return", pa.float64()),
    pa.field("volatility_30d", pa.float64()),
    pa.field("range_pct", pa.float64()),
    pa.field("vwap", pa.float64()),
])

# ============================================================
# DIRS + LOGGING
# ============================================================
os.makedirs(DIR_1M, exist_ok=True)
os.makedirs(DIR_1D, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()]
)
log = logging.getLogger("capa4")

# ============================================================
# STATE
# ============================================================
def load_state():
    if not os.path.exists(STATE_FILE):
        return {"last_processed_ms": None}
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def save_state(ms):
    with open(STATE_FILE, "w") as f:
        json.dump({
            "last_processed_ms": int(ms) if ms else None,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }, f, indent=2)

# ============================================================
# BINANCE API
# ============================================================
def fetch_klines(start_ms):
    url = "https://api.binance.com/api/v3/klines"
    params = {"symbol": SYMBOL, "interval": INTERVAL, "limit": LIMIT, "startTime": int(start_ms)}
    for attempt in range(5):
        try:
            r = requests.get(url, params=params, timeout=30)
            if r.status_code == 429:
                time.sleep(2)
                continue
            r.raise_for_status()
            data = r.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            log.error(f"Error red (intento {attempt+1}): {e}")
            time.sleep(1)
    return []

def get_first_binance_timestamp():
    data = fetch_klines(0)
    if not data:
        raise RuntimeError("Binance no responde")
    return data[0][0]

# ============================================================
# DOWNLOAD 1M
# ============================================================
def download_1m(start_ms):
    current = int(start_ms)
    total_rows = 0
    
    pbar = tqdm(desc="Descargando 1m", unit="batch")
    
    while True:
        data = fetch_klines(current)
        if not data:
            break
        
        rows = []
        for k in data:
            rows.append({
                "open_time": pd.Timestamp(k[0], unit="ms").tz_localize(None),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "close_time": pd.Timestamp(k[6], unit="ms").tz_localize(None),
                "quote_volume": float(k[7]),
                "trades": int(k[8]),
            })
        
        df = pd.DataFrame(rows)
        if df.empty:
            break
        
        df['year'] = df['open_time'].dt.year
        df['month'] = df['open_time'].dt.month
        
        for (y, m), chunk in df.groupby(['year', 'month']):
            fname = f"btcusdt_1m_{y}_{m:02d}.parquet"
            out_file = os.path.join(DIR_1M, fname)
            tmp = out_file + ".tmp"
            
            chunk_clean = chunk.drop(columns=['year', 'month'])
            chunk_clean = chunk_clean.drop_duplicates(subset=['open_time'])
            
            if os.path.exists(out_file):
                old = pq.read_table(out_file).to_pandas()
                for col in ['open_time', 'close_time']:
                    if hasattr(old[col].dtype, 'tz') and old[col].dtype.tz is not None:
                        old[col] = old[col].dt.tz_localize(None)
                chunk_clean = pd.concat([old, chunk_clean], ignore_index=True)
            
            chunk_clean = chunk_clean.drop_duplicates(subset=['open_time'])
            chunk_clean = chunk_clean.sort_values('open_time')
            
            for col in ['open_time', 'close_time']:
                if hasattr(chunk_clean[col].dtype, 'tz') and chunk_clean[col].dtype.tz is not None:
                    chunk_clean[col] = chunk_clean[col].dt.tz_localize(None)
            
            table = pa.Table.from_pandas(chunk_clean, schema=SCHEMA_1M)
            pq.write_table(table, tmp, compression="zstd", compression_level=6)
            os.replace(tmp, out_file)
        
        total_rows += len(df)
        last_ts = int(df['open_time'].max().timestamp() * 1000)
        save_state(last_ts)
        
        pbar.update(1)
        pbar.set_postfix({"filas": f"{total_rows:,}"})
        
        current = last_ts + 60_000
        time.sleep(SLEEP_TIME)
    
    pbar.close()
    log.info(f"Descarga 1m: {total_rows:,} filas")
    return total_rows

# ============================================================
# AGREGAR 1M → 1D
# ============================================================
def aggregate_to_1d():
    if not os.path.exists(DIR_1M):
        log.error("No existe directorio 1m")
        return
    
    files = sorted([os.path.join(DIR_1M, f) for f in os.listdir(DIR_1M) 
                    if f.endswith('.parquet') and '.tmp' not in f])
    
    if not files:
        log.error("No hay archivos 1m para agregar")
        return
    
    log.info(f"Agregando {len(files)} archivos 1m → 1d")
    
    dfs = []
    for f in tqdm(files, desc="Agregando 1m → 1d", unit="file"):
        df = pq.read_table(f).to_pandas()
        if not df.empty:
            dfs.append(df)
    
    df_all = pd.concat(dfs, ignore_index=True)
    df_all = df_all.drop_duplicates(subset=['open_time'])
    df_all['date'] = df_all['open_time'].dt.date
    
    daily = df_all.groupby('date').agg(
        open=('open', 'first'),
        high=('high', 'max'),
        low=('low', 'min'),
        close=('close', 'last'),
        volume_btc=('volume', 'sum'),
        volume_usdt=('quote_volume', 'sum'),
        trades=('trades', 'sum'),
        num_candles=('open', 'count'),
    ).reset_index()
    
    daily['date'] = pd.to_datetime(daily['date']).dt.date
    daily = daily.sort_values('date').reset_index(drop=True)
    
    daily['return_daily'] = daily['close'].pct_change()
    daily['log_return'] = np.log(daily['close'] / daily['close'].shift(1))
    daily['volatility_30d'] = daily['log_return'].rolling(30).std() * np.sqrt(365)
    daily['range_pct'] = (daily['high'] - daily['low']) / daily['open'] * 100
    daily['vwap'] = np.where(daily['volume_btc'] > 0, daily['volume_usdt'] / daily['volume_btc'], 0)
    
    # Limpiar directorio 1d antes de guardar
    if os.path.exists(DIR_1D):
        for f in os.listdir(DIR_1D):
            if f.endswith('.parquet'):
                os.remove(os.path.join(DIR_1D, f))
    
    # Guardar por año
    daily['year'] = pd.to_datetime(daily['date']).dt.year
    for year, chunk in daily.groupby('year'):
        out_file = os.path.join(DIR_1D, f"btcusdt_1d_{year}.parquet")
        tmp = out_file + ".tmp"
        chunk_out = chunk.drop(columns=['year']).reset_index(drop=True)
        table = pa.Table.from_pandas(chunk_out, schema=SCHEMA_1D)
        pq.write_table(table, tmp, compression="zstd", compression_level=6)
        os.replace(tmp, out_file)
    
    log.info(f"1d generado: {len(daily):,} días ({daily['date'].min()} → {daily['date'].max()})")
    print(f"\n✅ 1d: {len(daily):,} días ({daily['date'].min()} → {daily['date'].max()})")

# ============================================================
# MENU
# ============================================================
def main():
    print("\n" + "=" * 60)
    print("  CAPA 4 — Binance BTC/USDT (1m + 1d)")
    print("=" * 60)
    print("  1) Borrar todo y empezar desde 0 (borra 1m + 1d)")
    print("  2) Continuar desde el último timestamp (descarga 1m + regenera 1d)")
    print("  3) Rollback último batch (borra batch 1m + regenera 1d)")
    print("=" * 60)
    
    choice = input("Selecciona una opción [1-3]: ").strip()
    
    # ============================================================
    # OPCIÓN 1: RESET COMPLETO (BORRA 1M + 1D)
    # ============================================================
    if choice == "1":
        print("\n🗑 Reset completo (1m + 1d).")
        log.info("Reset completo.")
        if os.path.exists(CAPA4_DIR):
            shutil.rmtree(CAPA4_DIR)
        os.makedirs(DIR_1M, exist_ok=True)
        os.makedirs(DIR_1D, exist_ok=True)
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
        first_ts = get_first_binance_timestamp()
        download_1m(first_ts)
        aggregate_to_1d()
        print("\n✅ Capa 4 regenerada desde 0.")
    
    # ============================================================
    # OPCIÓN 2: CONTINUAR (DESCARGA 1M + REGENERA 1D)
    # ============================================================
    elif choice == "2":
        print("\n▶ Continuando (descarga 1m + regenera 1d).")
        log.info("Continuación.")
        state = load_state()
        last_ms = state.get("last_processed_ms")
        if last_ms is None:
            first_ts = get_first_binance_timestamp()
            download_1m(first_ts)
        else:
            download_1m(int(last_ms) + 60_000)
        aggregate_to_1d()
        print("\n✅ Capa 4 actualizada.")
    
    # ============================================================
    # OPCIÓN 3: ROLLBACK (BORRA BATCH 1M + REGENERA 1D)
    # ============================================================
    elif choice == "3":
        print("\n↩ Rollback último batch (borra batch 1m + regenera 1d).")
        log.info("Rollback.")
        state = load_state()
        last_ms = state.get("last_processed_ms")
        if last_ms is None:
            print("❌ No hay estado para rollback.")
            return
        
        rollback_ts = int(last_ms) - (60_000 * LIMIT)
        rollback_dt = datetime.fromtimestamp(rollback_ts/1000, timezone.utc)
        print(f"   Rollback a: {rollback_dt}")
        
        deleted = 0
        if os.path.exists(DIR_1M):
            for f in list(os.listdir(DIR_1M)):
                if not f.endswith('.parquet'):
                    continue
                fpath = os.path.join(DIR_1M, f)
                try:
                    df = pq.read_table(fpath).to_pandas()
                    if df.empty:
                        continue
                    if df['open_time'].max() > pd.Timestamp(rollback_ts, unit='ms'):
                        os.remove(fpath)
                        log.info(f"  Eliminado 1m: {f}")
                        deleted += 1
                except Exception as e:
                    log.error(f"Error en {f}: {e}")
        
        save_state(rollback_ts)
        log.info(f"Rollback: {deleted} archivos 1m borrados. Regenerando 1d.")
        print(f"✅ Rollback: {deleted} archivos 1m borrados.")
        aggregate_to_1d()
        print("✅ 1d regenerado.")
    
    else:
        print("Saliendo...")

if __name__ == "__main__":
    main()
