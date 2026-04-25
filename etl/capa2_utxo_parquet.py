#!/usr/bin/env python3
# ============================================================
# CAPA 2 - UTXO EVENTS (INSERT-ONLY, STREAMING, RAM SAFE)
# ============================================================
#
# Lee:
#   /run/media/linux/SSD4T/btc-etl/parquet/capa1_btccore_parquet/{blocks,inputs,outputs}
#
# Escribe:
#   /run/media/linux/SSD4T/btc-etl/parquet/capa2_utxo_parquet/utxo_events_XXXX_YYYY.parquet
#
# Estado:
#   /run/media/linux/SSD4T/btc-etl/state_capa2_utxo_parquet.json
#
# ============================================================

import os
import json
import shutil
import logging
from datetime import datetime, timezone

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pyarrow.dataset as ds
from tqdm import tqdm

# ============================================================
# CONFIG (RUTAS ACTUALIZADAS SSD4T)
# ============================================================

PROJECT_ROOT = "/run/media/linux/SSD4T/btc-etl"

CAPA1_DIR = os.path.join(PROJECT_ROOT, "parquet", "capa1_btccore_parquet")
CAPA2_DIR = os.path.join(PROJECT_ROOT, "parquet", "capa2_utxo_parquet")

BLOCKS_DIR = os.path.join(CAPA1_DIR, "blocks")
INPUTS_DIR = os.path.join(CAPA1_DIR, "inputs")
OUTPUTS_DIR = os.path.join(CAPA1_DIR, "outputs")

EVENTS_DIR = os.path.join(CAPA2_DIR, "utxo_events")

STATE_FILE = os.path.join(PROJECT_ROOT, "state_capa2_utxo_parquet.json")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_FILE = os.path.join(LOG_DIR, "capa2_utxo_parquet.log")

BLOCK_BATCH_SIZE = 250
PARQUET_COMPRESSION = "zstd"

# ============================================================
# ESQUEMA ARROW FIJO PARA TODOS LOS UTXO EVENTS
# ============================================================

ARROW_SCHEMA = pa.schema([
    pa.field("event_type", pa.string()),
    pa.field("height", pa.int64()),
    pa.field("block_hash", pa.string()),
    pa.field("txid", pa.string()),
    pa.field("outpoint_txid", pa.string()),
    pa.field("outpoint_vout", pa.int64()),
    pa.field("value_sats", pa.int64()),
    pa.field("scriptPubKey_type", pa.string()),
    pa.field("scriptPubKey_hex", pa.string()),
    pa.field("spent_by_txid", pa.string()),
    pa.field("spent_by_vin", pa.int64()),
])

# ============================================================
# LOGGING
# ============================================================

os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler()
    ]
)

log = logging.getLogger("capa2_utxo")

# ============================================================
# HELPERS
# ============================================================

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def ensure_dirs():
    os.makedirs(CAPA2_DIR, exist_ok=True)
    os.makedirs(EVENTS_DIR, exist_ok=True)

def load_state():
    if not os.path.exists(STATE_FILE):
        return {"last_processed": -1}
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def save_state(height):
    with open(STATE_FILE, "w") as f:
        json.dump(
            {"last_processed": int(height), "updated_at": utc_now()},
            f,
            indent=2
        )

def list_parquets(path):
    if not os.path.exists(path):
        return []
    return sorted(
        os.path.join(path, f)
        for f in os.listdir(path)
        if f.endswith(".parquet")
    )

def files_for_range(path, start_h, end_h):
    out = []
    for f in list_parquets(path):
        name = os.path.basename(f)
        parts = name.replace(".parquet", "").split("_")
        try:
            a, b = int(parts[-2]), int(parts[-1])
        except Exception:
            continue
        if not (b < start_h or a > end_h):
            out.append(f)
    return out

def get_tip_height():
    files = list_parquets(BLOCKS_DIR)
    if not files:
        return -1
    last = os.path.basename(files[-1])
    try:
        a, b = map(int, last.replace(".parquet", "").split("_")[-2:])
        return b
    except Exception:
        try:
            tbl = pq.read_table(files[-1])
            df = tbl.to_pandas()
            return int(df["height"].max())
        except Exception:
            return -1

# ============================================================
# NORMALIZADORES
# ============================================================

def normalize_outputs_df(df):
    if df.empty:
        return df
    df = df.copy()

    # value_sats
    if "value_sats" in df.columns:
        try:
            df["value_sats"] = df["value_sats"].astype("Int64")
        except Exception:
            df["value_sats"] = (
                pd.to_numeric(df["value_sats"], errors="coerce")
                .round()
                .astype("Int64")
            )
    elif "value" in df.columns:
        df["value_sats"] = (
            pd.to_numeric(df["value"], errors="coerce") * 100_000_000
        ).round().astype("Int64")
    else:
        df["value_sats"] = pd.Series(pd.NA, index=df.index, dtype="Int64")

    # vout
    if "vout" not in df.columns and "vout_index" in df.columns:
        df["vout"] = df["vout_index"]
    if "vout" in df.columns:
        try:
            df["vout"] = df["vout"].astype("Int64")
        except Exception:
            df["vout"] = pd.to_numeric(df["vout"], errors="coerce").astype("Int64")
    else:
        df["vout"] = pd.Series(pd.NA, index=df.index, dtype="Int64")

    # script type
    if "script_type" in df.columns:
        df["scriptPubKey_type"] = df["script_type"].astype("string")
    elif "scriptPubKey_type" in df.columns:
        df["scriptPubKey_type"] = df["scriptPubKey_type"].astype("string")
    else:
        df["scriptPubKey_type"] = pd.Series(pd.NA, index=df.index, dtype="string")

    # script hex
    if "scriptPubKey_hex" in df.columns:
        df["scriptPubKey_hex"] = df["scriptPubKey_hex"].astype("string")
    else:
        df["scriptPubKey_hex"] = pd.Series(pd.NA, index=df.index, dtype="string")

    # height, block_hash, txid
    if "height" not in df.columns:
        df["height"] = pd.Series(pd.NA, index=df.index, dtype="Int64")
    if "block_hash" not in df.columns:
        df["block_hash"] = pd.Series(pd.NA, index=df.index, dtype="string")
    if "txid" not in df.columns:
        df["txid"] = pd.Series(pd.NA, index=df.index, dtype="string")

    return df

def safe_prev_vout_series(s):
    if s is None:
        return pd.Series(dtype="Int64")
    if getattr(s, "dtype", None) and s.dtype.name == "Int64":
        return s
    try:
        return s.astype("Int64")
    except Exception:
        return pd.to_numeric(s, errors="coerce").astype("Int64")

# ============================================================
# EVENT BUILDERS
# ============================================================

EVENT_COLS = [
    "event_type",
    "height",
    "block_hash",
    "txid",
    "outpoint_txid",
    "outpoint_vout",
    "value_sats",
    "scriptPubKey_type",
    "scriptPubKey_hex",
    "spent_by_txid",
    "spent_by_vin",
]

def build_create_events(outputs):
    if outputs.empty:
        return pd.DataFrame(columns=EVENT_COLS)

    df = normalize_outputs_df(outputs)

    df["event_type"] = "create"
    df["outpoint_txid"] = df["txid"].astype("string")
    df["outpoint_vout"] = df["vout"].astype("Int64")
    df["value_sats"] = df["value_sats"].astype("Int64")

    df["spent_by_txid"] = pd.NA
    df["spent_by_vin"] = pd.NA

    df["event_type"] = df["event_type"].astype("string")
    df["height"] = df["height"].astype("Int64")
    df["block_hash"] = df["block_hash"].astype("string")
    df["txid"] = df["txid"].astype("string")
    df["scriptPubKey_type"] = df["scriptPubKey_type"].astype("string")
    df["scriptPubKey_hex"] = df["scriptPubKey_hex"].astype("string")

    for c in EVENT_COLS:
        if c not in df.columns:
            df[c] = pd.NA

    return df[EVENT_COLS]

def build_spend_events(inputs):
    if inputs.empty:
        return pd.DataFrame(columns=EVENT_COLS)

    df = inputs.copy()
    if "is_coinbase" in df.columns:
        df = df[df["is_coinbase"] == False]

    if df.empty:
        return pd.DataFrame(columns=EVENT_COLS)

    df["event_type"] = "spend"
    df["outpoint_txid"] = df.get("prev_txid").astype("string")
    df["outpoint_vout"] = safe_prev_vout_series(df.get("prev_vout"))
    df["spent_by_txid"] = df.get("txid").astype("string")

    if "vin_index" in df.columns:
        try:
            df["spent_by_vin"] = df["vin_index"].astype("Int64")
        except Exception:
            df["spent_by_vin"] = pd.to_numeric(df["vin_index"], errors="coerce").astype("Int64")
    else:
        df["spent_by_vin"] = pd.NA

    df["value_sats"] = pd.NA
    df["scriptPubKey_type"] = pd.NA
    df["scriptPubKey_hex"] = pd.NA

    df["event_type"] = df["event_type"].astype("string")
    df["height"] = df["height"].astype("Int64")
    df["block_hash"] = df["block_hash"].astype("string")
    df["txid"] = df["txid"].astype("string")

    for c in EVENT_COLS:
        if c not in df.columns:
            df[c] = pd.NA

    return df[EVENT_COLS]

# ============================================================
# PROCESS RANGE STREAMING
# ============================================================

def process_range_streaming(start_h, end_h):
    log.info("Processing blocks %s–%s (streaming)", start_h, end_h)

    out_files = files_for_range(OUTPUTS_DIR, start_h, end_h)
    in_files = files_for_range(INPUTS_DIR, start_h, end_h)

    out_ds = ds.dataset(out_files, format="parquet") if out_files else None
    in_ds = ds.dataset(in_files, format="parquet") if in_files else None

    out_file = os.path.join(EVENTS_DIR, f"utxo_events_{start_h:07d}_{end_h:07d}.parquet")
    tmp = out_file + ".tmp"

    writer = None
    total_written = 0

    try:
        # CREATES
        if out_ds is not None:
            out_filter = (ds.field("height") >= start_h) & (ds.field("height") <= end_h)
            for rb in out_ds.to_batches(filter=out_filter):
                df_out = rb.to_pandas()
                if df_out.empty:
                    continue
                creates = build_create_events(df_out)
                if creates.empty:
                    continue
                table = pa.Table.from_pandas(creates, schema=ARROW_SCHEMA, preserve_index=False)
                if writer is None:
                    writer = pq.ParquetWriter(tmp, ARROW_SCHEMA, compression=PARQUET_COMPRESSION)
                writer.write_table(table)
                total_written += table.num_rows

        # SPENDS
        if in_ds is not None:
            in_filter = (ds.field("height") >= start_h) & (ds.field("height") <= end_h)
            for rb in in_ds.to_batches(filter=in_filter):
                df_in = rb.to_pandas()
                if df_in.empty:
                    continue
                spends = build_spend_events(df_in)
                if spends.empty:
                    continue
                table = pa.Table.from_pandas(spends, schema=ARROW_SCHEMA, preserve_index=False)
                if writer is None:
                    writer = pq.ParquetWriter(tmp, ARROW_SCHEMA, compression=PARQUET_COMPRESSION)
                writer.write_table(table)
                total_written += table.num_rows

        # finalize
        if writer is not None:
            writer.close()
            os.replace(tmp, out_file)
            log.info("Wrote %d events → %s", total_written, out_file)
        else:
            if os.path.exists(tmp):
                os.remove(tmp)
            log.info("No events for range %s-%s", start_h, end_h)

    except Exception as e:
        log.exception("Error streaming range %s-%s: %s", start_h, end_h, e)
        if writer is not None:
            try:
                writer.close()
            except:
                pass
        if os.path.exists(tmp):
            os.remove(tmp)
        raise

# ============================================================
# MAIN
# ============================================================

def main():
    ensure_dirs()

    print("¿Qué deseas hacer?")
    print("1) Borrar todo y empezar desde 0 (capa2_utxo_parquet)")
    print("2) Continuar desde donde se cortó")
    print("3) Rollback último batch completo")
    choice = input("Selecciona 1, 2 o 3: ").strip()

    if choice == "1":
        if os.path.exists(CAPA2_DIR):
            shutil.rmtree(CAPA2_DIR)
        ensure_dirs()
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
        save_state(-1)
        log.info("Reset completo")

    elif choice == "3":
        state = load_state()
        last = int(state.get("last_processed", -1))
        if last < 0:
            print("No hay estado válido para rollback.")
            log.info("Rollback solicitado pero no hay estado válido.")
            return

        batch_start = (last // BLOCK_BATCH_SIZE) * BLOCK_BATCH_SIZE
        batch_end = batch_start + BLOCK_BATCH_SIZE - 1

        deleted = 0
        if os.path.exists(EVENTS_DIR):
            for f in os.listdir(EVENTS_DIR):
                if not f.endswith(".parquet"):
                    continue
                try:
                    a, b = map(int, f.replace(".parquet", "").split("_")[-2:])
                except Exception:
                    continue
                if a == batch_start and b == batch_end:
                    os.remove(os.path.join(EVENTS_DIR, f))
                    log.info("Deleted %s", f)
                    deleted += 1

        save_state(batch_start - 1)
        print(f"Rollback completado for batch {batch_start}-{batch_end}.")
        log.info("Rollback completado for batch %s-%s (deleted files: %d)", batch_start, batch_end, deleted)
        return

    else:
        state = load_state()

    tip = get_tip_height()
    if tip < 0:
        print("No hay archivos de blocks en capa1 o no se pudo determinar tip.")
        log.error("Tip not found, aborting.")
        return

    start = int(state.get("last_processed", -1)) + 1
    if start > tip:
        print("No hay bloques nuevos para procesar.")
        log.info("No hay bloques nuevos para procesar.")
        return

    log.info("Starting processing from %d to %d", start, tip)

    for h in range(start, tip + 1, BLOCK_BATCH_SIZE):
        a = h
        b = min(h + BLOCK_BATCH_SIZE - 1, tip)

        for _ in tqdm(range(a, b + 1), desc=f"Bloques {a}-{b}", unit="blk"):
            pass

        try:
            process_range_streaming(a, b)
            save_state(b)
        except Exception as e:
            log.error("Error processing range %s-%s: %s", a, b, e)
            print(f"Error processing range {a}-{b}: {e}")
            return

    log.info("Capa2 UTXO events completada")
    print("Capa2 UTXO events completada")

if __name__ == "__main__":
    main()
