#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import json
import shutil
import numpy as np
import pandas as pd
from datetime import datetime
from tqdm import tqdm

# ============================================================
# CONFIG
# ============================================================

PROJECT_ROOT = "/home/nw/btc-etl"

BINANCE_DIR = os.path.join(PROJECT_ROOT, "parquet", "binance_1m")
LAYER1_DIR = os.path.join(PROJECT_ROOT, "parquet", "fast_layer1_v2", "blocks")

OUT_DIR = os.path.join(PROJECT_ROOT, "parquet", "capa3_ml")
STATE_FILE = os.path.join(PROJECT_ROOT, "state_capa3_ml.json")

os.makedirs(OUT_DIR, exist_ok=True)

# ============================================================
# STATE
# ============================================================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {"built": False}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_state(state: dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, default=str)

# ============================================================
# IO HELPERS
# ============================================================

def list_parquet_files(base_dir):
    files = []
    for root, _, fnames in os.walk(base_dir):
        for f in fnames:
            if f.endswith(".parquet"):
                files.append(os.path.join(root, f))
    return sorted(files)

def load_binance_all():
    files = list_parquet_files(BINANCE_DIR)
    if not files:
        raise RuntimeError(f"No se encontraron Parquet en {BINANCE_DIR}")

    dfs = []
    print(f"Cargando Binance 1m ({len(files)} archivos)…")
    for f in tqdm(files, desc="Binance 1m"):
        df = pd.read_parquet(f)
        dfs.append(df)

    df = pd.concat(dfs, ignore_index=True)
    df["open_time"] = pd.to_datetime(df["open_time"], utc=False)
    df = df.sort_values("open_time").drop_duplicates(subset=["open_time"])
    return df

def load_layer1_all():
    files = list_parquet_files(LAYER1_DIR)
    if not files:
        raise RuntimeError(f"No se encontraron Parquet de Capa 1 en {LAYER1_DIR}")

    dfs = []
    print(f"Cargando Capa 1 (blocks) ({len(files)} archivos)…")
    for f in tqdm(files, desc="Capa 1 blocks"):
        df = pd.read_parquet(f)
        dfs.append(df)

    df = pd.concat(dfs, ignore_index=True)

    if "time" in df.columns:
        df["timestamp"] = pd.to_datetime(df["time"], unit="s").dt.floor("min")
    else:
        raise RuntimeError("Capa 1 no contiene columna 'time'.")

    df = df.sort_values("timestamp")
    return df

# ============================================================
# FEATURE ENGINEERING
# ============================================================

def safe_log_ratio(series_num, series_den, shift=None):
    if shift is not None:
        series_den = series_den.shift(shift)
    ratio = series_num / series_den
    ratio = ratio.replace([np.inf, -np.inf], np.nan)
    return np.log(ratio).replace([np.inf, -np.inf], np.nan).fillna(0.0)

def add_market_features(df):
    df = df.sort_values("timestamp")

    df["ret_1m"] = safe_log_ratio(df["close"], df["close"], shift=1)
    df["ret_5m"] = safe_log_ratio(df["close"], df["close"], shift=5)
    df["ret_15m"] = safe_log_ratio(df["close"], df["close"], shift=15)
    df["ret_1h"] = safe_log_ratio(df["close"], df["close"], shift=60)

    df["vol_1h"] = df["ret_1m"].rolling(window=60, min_periods=10).std()
    df["vol_24h"] = df["ret_1m"].rolling(window=1440, min_periods=60).std()

    df["ma_5"] = df["close"].rolling(window=5, min_periods=3).mean()
    df["ma_15"] = df["close"].rolling(window=15, min_periods=5).mean()
    df["ma_60"] = df["close"].rolling(window=60, min_periods=10).mean()

    df["ema_5"] = df["close"].ewm(span=5, adjust=False).mean()
    df["ema_15"] = df["close"].ewm(span=15, adjust=False).mean()
    df["ema_60"] = df["close"].ewm(span=60, adjust=False).mean()

    return df

def add_onchain_features(df):

    rename_map = {
        "total_output_value_block": "total_output_value",
        "num_inputs_block": "inputs_count",
        "num_outputs_block": "outputs_count",
    }

    df = df.rename(columns=rename_map)

    if {"total_fees", "n_tx"}.issubset(df.columns):
        df["fees_per_tx"] = df["total_fees"] / df["n_tx"].replace(0, np.nan)

    if {"total_input_value", "inputs_count"}.issubset(df.columns):
        df["avg_input_value"] = df["total_input_value"] / df["inputs_count"].replace(0, np.nan)

    if {"total_output_value", "outputs_count"}.issubset(df.columns):
        df["avg_output_value"] = df["total_output_value"] / df["outputs_count"].replace(0, np.nan)

    return df

def add_time_features(df):
    df["year"] = df["timestamp"].dt.year.astype("int16")
    df["month"] = df["timestamp"].dt.month.astype("int8")
    df["day"] = df["timestamp"].dt.day.astype("int8")
    df["hour"] = df["timestamp"].dt.hour.astype("int8")
    df["dow"] = df["timestamp"].dt.dayofweek.astype("int8")
    df["is_weekend"] = df["dow"].isin([5, 6]).astype("int8")
    return df

def add_targets(df):
    df = df.sort_values("timestamp")

    future_15m = df["close"].shift(-15)
    df["target_ret_15m"] = safe_log_ratio(future_15m, df["close"])
    df["target_dir_15m"] = df["target_ret_15m"].apply(
        lambda x: 1 if x > 0 else (-1 if x < 0 else 0)
    ).astype("int8")

    future_1h = df["close"].shift(-60)
    df["target_ret_1h"] = safe_log_ratio(future_1h, df["close"])

    df["target_vol_1h"] = (
        df["ret_1m"].shift(-60).rolling(window=60, min_periods=10).std()
    )

    return df

# ============================================================
# BUILD CAPA 3
# ============================================================

def build_capa3_full():
    print("Cargando datos de Binance (Capa 2)…")
    df_bin = load_binance_all()
    df_bin = df_bin.rename(columns={"open_time": "timestamp"})
    df_bin["timestamp"] = pd.to_datetime(df_bin["timestamp"], utc=False)

    print("Cargando datos de Capa 1 (blocks)…")
    df_l1 = load_layer1_all()
    df_l1["timestamp"] = pd.to_datetime(df_l1["timestamp"], utc=False)

    print("Haciendo merge Capa 1 + Capa 2 por minuto…")
    df = pd.merge(
        df_bin,
        df_l1,
        on="timestamp",
        how="left",
    )

    print("Generando features de mercado…")
    df = add_market_features(df)

    print("Generando features on-chain…")
    df = add_onchain_features(df)

    print("Generando features temporales…")
    df = add_time_features(df)

    print("Generando targets…")
    df = add_targets(df)

    cols = df.columns.tolist()
    ordered = ["timestamp", "year", "month", "day", "hour", "dow", "is_weekend"]
    ordered += [c for c in cols if c not in ordered and not c.startswith("target_")]
    ordered += [c for c in cols if c.startswith("target_")]
    df = df[ordered]

    print("Escribiendo Parquet particionado por año/mes…")
    for (y, m), chunk in tqdm(df.groupby(["year", "month"]), desc="Escribiendo"):
        out_dir = os.path.join(OUT_DIR, f"{y}", f"{m:02d}")
        os.makedirs(out_dir, exist_ok=True)
        fname = f"btc_ml_{y}_{m:02d}.parquet"
        fpath = os.path.join(out_dir, fname)
        chunk.to_parquet(fpath, index=False)

    save_state({"built": True, "last_build": datetime.utcnow().isoformat()})
    print("Capa 3 completada.")

# ============================================================
# MENU
# ============================================================

def main():
    print("\n=== CAPA 3 — Dataset ML (BTC, Binance 1m + On-chain) ===")
    print("1) Borrar Capa 3 y recomputar todo")
    print("2) Reprocesar todo (sobrescribe archivos)")
    print("3) Salir")
    choice = input("Selecciona 1, 2 o 3: ").strip()

    if choice == "1":
        print("Borrando Capa 3…")
        if os.path.exists(OUT_DIR):
            shutil.rmtree(OUT_DIR)
        os.makedirs(OUT_DIR, exist_ok=True)
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
        print("Reset completo. Recomputando Capa 3…")
        build_capa3_full()

    elif choice == "2":
        print("Recomputando Capa 3 (sobrescribe archivos existentes)…")
        build_capa3_full()

    else:
        print("Saliendo sin cambios.")

if __name__ == "__main__":
    main()

