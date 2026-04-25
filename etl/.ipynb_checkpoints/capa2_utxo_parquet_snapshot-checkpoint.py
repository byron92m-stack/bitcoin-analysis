#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
from datetime import datetime, timezone

import plyvel
import pyarrow as pa
import pyarrow.parquet as pq
from tqdm import tqdm

# ============================================================
# CONFIG
# ============================================================

# RUTA CORREGIDA PARA TU SISTEMA
PROJECT_ROOT = "/media/SSD4T/btc-etl"

UTXO_EVENTS_DIR = os.path.join(
    PROJECT_ROOT,
    "parquet",
    "capa2_utxo_parquet",
    "utxo_events",
)

SNAPSHOT_EXPORT_DIR = os.path.join(
    PROJECT_ROOT,
    "parquet",
    "capa2_utxo_parquet",
    "utxo_snapshot_incremental",
)

LEVELDB_DIR = os.path.join(
    PROJECT_ROOT,
    "leveldb",
    "utxo_snapshot_leveldb",
)

STATE_FILE = os.path.join(
    PROJECT_ROOT,
    "leveldb",
    "utxo_snapshot_state.json",
)

os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
os.makedirs(SNAPSHOT_EXPORT_DIR, exist_ok=True)

# Columnas esperadas en los Parquet de eventos
COL_EVENT_TYPE = "event_type"
COL_HEIGHT = "height"
COL_OUT_TXID = "outpoint_txid"
COL_OUT_VOUT = "outpoint_vout"
COL_VALUE = "value_sats"
COL_SCRIPT_TYPE = "scriptPubKey_type"
COL_SCRIPT_HEX = "scriptPubKey_hex"

# ============================================================
# STATE
# ============================================================

def load_state():
    if not os.path.exists(STATE_FILE):
        return {
            "last_batch_start": None,
            "last_batch_end": None,
            "updated_at": None,
        }
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# ============================================================
# BATCH DISCOVERY
# ============================================================

def list_batches():
    files = []
    if not os.path.exists(UTXO_EVENTS_DIR):
        return files

    for fname in os.listdir(UTXO_EVENTS_DIR):
        if not fname.endswith(".parquet"):
            continue
        try:
            base = fname.replace(".parquet", "")
            parts = base.split("_")
            start = int(parts[-2])
            end = int(parts[-1])
            files.append((start, end, fname))
        except Exception:
            continue

    files.sort(key=lambda x: x[0])
    return files


def find_next_batches(state, batches):
    last_end = state["last_batch_end"]
    if last_end is None:
        return batches
    return [b for b in batches if b[0] > last_end]


# ============================================================
# LEVELDB HELPERS
# ============================================================

def open_db():
    os.makedirs(os.path.dirname(LEVELDB_DIR), exist_ok=True)
    db = plyvel.DB(LEVELDB_DIR, create_if_missing=True)
    return db


def utxo_key(txid: str, vout: int) -> bytes:
    return f"{txid}:{vout}".encode("utf-8")


def utxo_value(height: int, value_sats: int, script_type: str, script_hex: str) -> bytes:
    obj = {
        "height": height,
        "value_sats": int(value_sats),
        "script_type": script_type,
        "script_hex": script_hex,
    }
    return json.dumps(obj).encode("utf-8")


# ============================================================
# PROCESS ONE BATCH (PyArrow + LevelDB)
# ============================================================

def process_batch(db, fname, start, end):
    path = os.path.join(UTXO_EVENTS_DIR, fname)

    table = pq.read_table(
        path,
        columns=[
            COL_EVENT_TYPE,
            COL_HEIGHT,
            COL_OUT_TXID,
            COL_OUT_VOUT,
            COL_VALUE,
            COL_SCRIPT_TYPE,
            COL_SCRIPT_HEX,
        ],
    )

    event_type_arr = table[COL_EVENT_TYPE]
    height_arr = table[COL_HEIGHT]
    txid_arr = table[COL_OUT_TXID]
    vout_arr = table[COL_OUT_VOUT]
    value_arr = table[COL_VALUE]
    stype_arr = table[COL_SCRIPT_TYPE]
    shex_arr = table[COL_SCRIPT_HEX]

    wb = db.write_batch()

    for i in range(table.num_rows):
        ev = event_type_arr[i].as_py()
        h = height_arr[i].as_py()
        txid = txid_arr[i].as_py()
        vout = vout_arr[i].as_py()

        key = utxo_key(txid, vout)

        if ev == "create":
            val = value_arr[i].as_py()
            stype = stype_arr[i].as_py()
            shex = shex_arr[i].as_py()
            wb.put(key, utxo_value(h, val, stype, shex))
        elif ev == "spend":
            wb.delete(key)
        else:
            continue

    wb.write()


# ============================================================
# EXPORT SNAPSHOT A PARQUET POR VENTANA DE HEIGHT
# ============================================================

def export_snapshot_window(height_min: int, height_max: int):
    db = open_db()
    try:
        keys = []
        heights = []
        values = []
        script_types = []
        script_hexes = []
        vouts = []

        for k, v in tqdm(db, desc="Iterando UTXO LevelDB", unit="utxo"):
            obj = json.loads(v.decode("utf-8"))
            h = obj["height"]
            if h < height_min or h > height_max:
                continue

            key_str = k.decode("utf-8")
            txid, vout_str = key_str.split(":", 1)
            vout = int(vout_str)

            keys.append(txid)
            vouts.append(vout)
            heights.append(h)
            values.append(obj["value_sats"])
            script_types.append(obj["script_type"])
            script_hexes.append(obj["script_hex"])

        if not keys:
            print(f"No hay UTXOs en ventana {height_min}-{height_max}")
            return

        out_table = pa.Table.from_arrays(
            [
                pa.array(keys, type=pa.string()),
                pa.array(vouts, type=pa.int64()),
                pa.array(heights, type=pa.int64()),
                pa.array(values, type=pa.int64()),
                pa.array(script_types, type=pa.string()),
                pa.array(script_hexes, type=pa.string()),
            ],
            names=[
                COL_OUT_TXID,
                COL_OUT_VOUT,
                COL_HEIGHT,
                COL_VALUE,
                COL_SCRIPT_TYPE,
                COL_SCRIPT_HEX,
            ],
        )

        out_path = os.path.join(
            SNAPSHOT_EXPORT_DIR,
            f"utxo_snapshot_window_{height_min:07d}_{height_max:07d}.parquet",
        )
        pq.write_table(out_table, out_path)
        print(f"Snapshot ventana escrito: {out_path}")

    finally:
        db.close()


# ============================================================
# RESET / INCREMENTAL
# ============================================================

def reset_all():
    if os.path.exists(LEVELDB_DIR):
        for root, dirs, files in os.walk(LEVELDB_DIR, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
        os.rmdir(LEVELDB_DIR)

    if os.path.exists(SNAPSHOT_EXPORT_DIR):
        for root, dirs, files in os.walk(SNAPSHOT_EXPORT_DIR, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
        os.makedirs(SNAPSHOT_EXPORT_DIR, exist_ok=True)

    os.makedirs(LEVELDB_DIR, exist_ok=True)

    save_state({
        "last_batch_start": None,
        "last_batch_end": None,
        "updated_at": None,
    })


def process_incremental():
    state = load_state()
    batches = list_batches()
    next_batches = find_next_batches(state, batches)

    if not next_batches:
        print("No hay batches nuevos.")
        return

    db = open_db()
    try:
        for start, end, fname in tqdm(next_batches, desc="Procesando batches", unit="batch"):
            process_batch(db, fname, start, end)

            state["last_batch_start"] = start
            state["last_batch_end"] = end
            state["updated_at"] = datetime.now(timezone.utc).isoformat()
            save_state(state)

        print(f"Incremental completado. Último batch: {end}")
    finally:
        db.close()


def rollback_one_batch():
    print("Rollback del último batch NO soportado en esta versión RAM-safe incremental.")
    print("Usa reset total (opción 1) si necesitas recomputar desde 0.")


# ============================================================
# MENU
# ============================================================

def main():
    print("=== SNAPSHOT UTXO (PyArrow + LevelDB, RAM-safe, incremental real) ===")
    print("1) Reset total y recomputar desde 0")
    print("2) Continuar incrementalmente")
    print("3) Rollback del último batch (no soportado en esta versión)")
    print("4) Snapshot por ventana de height (export a Parquet)")
    choice = input("Selecciona 1, 2, 3 o 4: ").strip()

    if choice == "1":
        print("Reset total...")
        reset_all()
        process_incremental()

    elif choice == "2":
        process_incremental()

    elif choice == "3":
        rollback_one_batch()

    elif choice == "4":
        hmin = int(input("Height inicio: "))
        hmax = int(input("Height fin: "))
        export_snapshot_window(hmin, hmax)

    else:
        print("Opción inválida.")


if __name__ == "__main__":
    main()
