#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import json
import pandas as pd
import requests
from datetime import datetime, timezone

# ============================================================
# CONFIG
# ============================================================

PROJECT_ROOT = "/home/nw/btc-etl"
BINANCE_DIR = os.path.join(PROJECT_ROOT, "parquet", "binance_1m")

STATE_FILE = os.path.join(PROJECT_ROOT, "state_binance_1m.json")

SYMBOL = "BTCUSDT"
INTERVAL = "1m"
LIMIT = 1000  # máximo permitido por Binance

os.makedirs(BINANCE_DIR, exist_ok=True)

# ============================================================
# STATE
# ============================================================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {"last_timestamp": None}
    return json.load(open(STATE_FILE))

def save_state(ts):
    json.dump({"last_timestamp": ts}, open(STATE_FILE, "w"), indent=2)

# ============================================================
# BINANCE API
# ============================================================

def fetch_klines(start_ms):
    url = "https://api.binance.com/api/v3/klines"
    params = {
        "symbol": SYMBOL,
        "interval": INTERVAL,
        "limit": LIMIT,
        "startTime": start_ms,
    }

    for _ in range(5):  # retries
        try:
            r = requests.get(url, params=params, timeout=10)
            if r.status_code == 429:
                print("Rate limit… esperando 1s")
                time.sleep(1)
                continue
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print("Error de red:", e)
            time.sleep(1)

    return []

# ============================================================
# WRITE PARQUET
# ============================================================

def write_parquet(df):
    if df.empty:
        return

    df["year"] = df["open_time"].dt.year
    df["month"] = df["open_time"].dt.month

    for (y, m), chunk in df.groupby(["year", "month"]):
        out_dir = os.path.join(BINANCE_DIR, f"{y}", f"{m:02d}")
        os.makedirs(out_dir, exist_ok=True)
        fname = f"BTCUSDT_1m_{y}_{m:02d}.parquet"
        fpath = os.path.join(out_dir, fname)

        if os.path.exists(fpath):
            old = pd.read_parquet(fpath)
            chunk = pd.concat([old, chunk], ignore_index=True)

        chunk = (
            chunk
            .drop_duplicates(subset=["open_time"])
            .sort_values("open_time")
            .reset_index(drop=True)
        )

        chunk.to_parquet(fpath, index=False)

# ============================================================
# DETECT FIRST TIMESTAMP
# ============================================================

def detect_first_timestamp():
    print("Detectando primer timestamp disponible en Binance…")
    probe = fetch_klines(0)
    if not probe:
        raise RuntimeError("No se pudo detectar el primer timestamp.")
    ts = probe[0][0]
    print("Primer timestamp:", datetime.fromtimestamp(ts/1000, timezone.utc))
    return ts

# ============================================================
# MAIN
# ============================================================

def run_full():
    print("Descargando TODO el histórico…")
    start_ms = detect_first_timestamp()

    state = {"last_timestamp": None}
    save_state(start_ms)

    run_incremental(start_ms)

def run_incremental(start_ms=None):
    state = load_state()
    last_ts = state["last_timestamp"]

    if start_ms is None:
        start_ms = last_ts + 60_000

    print(f"Descargando desde {datetime.fromtimestamp(start_ms/1000, timezone.utc)}")

    while True:
        data = fetch_klines(start_ms)
        if not data:
            print("No hay más datos nuevos.")
            break

        rows = []
        for k in data:
            rows.append({
                "open_time": datetime.fromtimestamp(k[0] / 1000, timezone.utc),
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "close_time": datetime.fromtimestamp(k[6] / 1000, timezone.utc),
                "quote_volume": float(k[7]),
                "trades": int(k[8]),
            })

        df = pd.DataFrame(rows)

        # limpieza para merge con capa 1
        df["open_time"] = df["open_time"].dt.tz_convert(None)

        write_parquet(df)

        last_ts = int(df["open_time"].max().timestamp() * 1000)
        save_state(last_ts)

        print("Hasta:", df["open_time"].max())
        start_ms = last_ts + 60_000
        time.sleep(0.2)

    print("Capa 2 completada.")

# ============================================================
# MENU
# ============================================================

def menu():
    print("\n=== CAPA 2 — Binance OHLCV 1m ===")
    print("1) Borrar todo y empezar desde 0")
    print("2) Continuar incremental")
    print("3) Reprocesar último batch (rollback 1 paso)")
    print("4) Salir")

    choice = input("Selecciona 1, 2, 3 o 4: ").strip()

    if choice == "1":
        print("Borrando Capa 2…")
        if os.path.exists(BINANCE_DIR):
            os.system(f"rm -rf {BINANCE_DIR}")
        os.makedirs(BINANCE_DIR, exist_ok=True)
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
        run_full()

    elif choice == "2":
        state = load_state()
        if state["last_timestamp"] is None:
            run_full()
        else:
            run_incremental()

    elif choice == "3":
        print("Rollback 1 batch…")
        state = load_state()
        last = state["last_timestamp"]
        rollback_to = last - 60_000 * LIMIT
        save_state(rollback_to)
        run_incremental()

    else:
        print("Saliendo…")

if __name__ == "__main__":
    menu()

