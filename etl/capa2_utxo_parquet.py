#!/usr/bin/env python3
"""
CAPA 2 — UTXO EVENTS (streaming, sin índices)
Lee Capa 1 (outputs/inputs). Spends sin value_sats/address (JOIN delegado a Capa 5).
Escribe: parquet/capa2_utxo_parquet/utxo_events/
Menú: 1=Reset, 2=Continuar, 3=Rollback. 250 bloques por batch. Barra tqdm.
"""
import os, json, shutil, logging, hashlib
import bech32
from datetime import datetime, timezone

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pyarrow.dataset as ds
from tqdm import tqdm

PROJECT_ROOT = "/media/SSD4T/btc-etl"
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
    pa.field("address", pa.string()),
    pa.field("spent_by_txid", pa.string()),
    pa.field("spent_by_vin", pa.int64()),
])

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)s | %(message)s",
                    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler()])
log = logging.getLogger("capa2")

def utc_now(): return datetime.now(timezone.utc).isoformat()
def ensure_dirs():
    os.makedirs(CAPA2_DIR, exist_ok=True)
    os.makedirs(EVENTS_DIR, exist_ok=True)

def load_state():
    if not os.path.exists(STATE_FILE): return {"last_processed": -1}
    with open(STATE_FILE) as f: return json.load(f)

def save_state(h):
    with open(STATE_FILE, "w") as f: json.dump({"last_processed": int(h), "updated_at": utc_now()}, f, indent=2)

def list_parquets(path):
    if not os.path.exists(path): return []
    return sorted(os.path.join(path, f) for f in os.listdir(path) if f.endswith(".parquet"))

def files_for_range(path, start_h, end_h):
    out = []
    for f in list_parquets(path):
        parts = os.path.basename(f).replace(".parquet", "").split("_")
        try: a, b = int(parts[-2]), int(parts[-1])
        except: continue
        if not (b < start_h or a > end_h): out.append(f)
    return out

def get_tip_height():
    files = list_parquets(BLOCKS_DIR)
    if not files: return -1
    last = os.path.basename(files[-1])
    try: a, b = map(int, last.replace(".parquet", "").split("_")[-2:]); return b
    except:
        try: return int(pq.read_table(files[-1]).to_pandas()["height"].max())
        except: return -1

# Crypto
def b58encode(data):
    alphabet = '123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz'
    n = int.from_bytes(data, 'big'); res = []
    while n > 0: n, r = divmod(n, 58); res.append(alphabet[r])
    for byte in data:
        if byte == 0: res.append('1')
        else: break
    return ''.join(reversed(res))

def script_hex_to_address(hex_str):
    if not hex_str or pd.isna(hex_str): return None
    try:
        script = bytes.fromhex(hex_str)
        if len(script) == 25 and script[0] == 0x76 and script[1] == 0xa9 and script[-2] == 0x88 and script[-1] == 0xac:
            return b58encode(b'\x00' + script[3:23] + hashlib.sha256(hashlib.sha256(b'\x00' + script[3:23]).digest()).digest()[:4])
        if len(script) == 23 and script[0] == 0xa9 and script[-1] == 0x87:
            return b58encode(b'\x05' + script[2:22] + hashlib.sha256(hashlib.sha256(b'\x05' + script[2:22]).digest()).digest()[:4])
        if len(script) == 22 and script[0] == 0x00 and script[1] == 0x14: return bech32.encode('bc', 0, script[2:])
        if len(script) == 34 and script[0] == 0x00 and script[1] == 0x20: return bech32.encode('bc', 0, script[2:])
        if len(script) == 34 and script[0] == 0x51 and script[1] == 0x20: return bech32.encode('bc', 1, script[2:])
        return None
    except: return None

def safe_prev_vout_series(s):
    if s is None: return pd.Series(dtype="int64")
    try: return s.astype("int64")
    except: return pd.to_numeric(s, errors="coerce").astype("int64")

def normalize_outputs_df(df):
    if df.empty: return df
    df = df.copy()
    if "value_sats" in df.columns: df["value_sats"] = pd.to_numeric(df["value_sats"], errors="coerce").round().astype("int64")
    elif "value" in df.columns: df["value_sats"] = (pd.to_numeric(df["value"], errors="coerce") * 100_000_000).round().astype("int64")
    else: df["value_sats"] = pd.NA
    if "vout" not in df.columns and "vout_index" in df.columns: df["vout"] = df["vout_index"]
    if "vout" in df.columns: df["vout"] = pd.to_numeric(df["vout"], errors="coerce").astype("int64")
    else: df["vout"] = pd.NA
    if "script_type" in df.columns: df["scriptPubKey_type"] = df["script_type"].astype("string")
    elif "scriptPubKey_type" in df.columns: df["scriptPubKey_type"] = df["scriptPubKey_type"].astype("string")
    else: df["scriptPubKey_type"] = pd.NA
    if "script_hex" in df.columns: df["scriptPubKey_hex"] = df["script_hex"].astype("string")
    elif "scriptPubKey_hex" in df.columns: df["scriptPubKey_hex"] = df["scriptPubKey_hex"].astype("string")
    else: df["scriptPubKey_hex"] = pd.NA
    if "scriptPubKey_hex" in df.columns:
        mask = df["scriptPubKey_hex"].notna()
        if mask.any():
            df.loc[mask, "address"] = df.loc[mask, "scriptPubKey_hex"].apply(script_hex_to_address)
        else:
            df["address"] = pd.NA
    else:
        df["address"] = pd.NA
    for col in ["height", "block_hash", "txid"]:
        if col not in df.columns: df[col] = pd.NA
    return df

EVENT_COLS = ["event_type", "height", "block_hash", "txid", "outpoint_txid", "outpoint_vout",
              "value_sats", "scriptPubKey_type", "scriptPubKey_hex", "address",
              "spent_by_txid", "spent_by_vin"]

def build_create_events(outputs):
    if outputs.empty: return pd.DataFrame(columns=EVENT_COLS)
    df = normalize_outputs_df(outputs)
    df["event_type"] = "create"
    df["outpoint_txid"] = df["txid"].astype("string")
    df["outpoint_vout"] = df["vout"].astype("int64")
    df["value_sats"] = df["value_sats"].astype("int64")
    df["spent_by_txid"] = pd.NA
    df["spent_by_vin"] = 0
    for c in EVENT_COLS:
        if c not in df.columns: df[c] = pd.NA
    return df[EVENT_COLS]

def build_spend_events(inputs):
    if inputs.empty: return pd.DataFrame(columns=EVENT_COLS)
    df = inputs.copy()
    if "is_coinbase" in df.columns: df = df[df["is_coinbase"] == False]
    if df.empty: return pd.DataFrame(columns=EVENT_COLS)
    df["event_type"] = "spend"
    df["outpoint_txid"] = df.get("prev_txid").astype("string")
    df["outpoint_vout"] = safe_prev_vout_series(df.get("prev_vout"))
    df["spent_by_txid"] = df.get("txid").astype("string")
    if "vin_index" in df.columns:
        df["spent_by_vin"] = pd.to_numeric(df["vin_index"], errors="coerce").fillna(0).astype("int64")
    else: df["spent_by_vin"] = 0
    df["value_sats"] = 0
    df["address"] = pd.NA
    df["scriptPubKey_type"] = pd.NA
    df["scriptPubKey_hex"] = pd.NA
    for c in EVENT_COLS:
        if c not in df.columns: df[c] = pd.NA
    return df[EVENT_COLS]

def process_range_streaming(start_h, end_h):
    log.info("Processing blocks %s–%s", start_h, end_h)
    out_files = files_for_range(OUTPUTS_DIR, start_h, end_h)
    in_files = files_for_range(INPUTS_DIR, start_h, end_h)
    out_ds = ds.dataset(out_files, format="parquet") if out_files else None
    in_ds = ds.dataset(in_files, format="parquet") if in_files else None
    out_file = os.path.join(EVENTS_DIR, f"utxo_events_{start_h:07d}_{end_h:07d}.parquet")
    tmp = out_file + ".tmp"
    writer = None
    total = 0

    try:
        if out_ds is not None:
            out_filter = (ds.field("height") >= start_h) & (ds.field("height") <= end_h)
            for rb in out_ds.to_batches(filter=out_filter):
                df_out = rb.to_pandas()
                if df_out.empty: continue
                c = build_create_events(df_out)
                if c.empty: continue
                table = pa.Table.from_pandas(c, schema=ARROW_SCHEMA, preserve_index=False)
                if writer is None: writer = pq.ParquetWriter(tmp, ARROW_SCHEMA, compression=PARQUET_COMPRESSION)
                writer.write_table(table); total += table.num_rows

        if in_ds is not None:
            in_filter = (ds.field("height") >= start_h) & (ds.field("height") <= end_h)
            for rb in in_ds.to_batches(filter=in_filter):
                df_in = rb.to_pandas()
                if df_in.empty: continue
                s = build_spend_events(df_in)
                if s.empty: continue
                table = pa.Table.from_pandas(s, schema=ARROW_SCHEMA, preserve_index=False)
                if writer is None: writer = pq.ParquetWriter(tmp, ARROW_SCHEMA, compression=PARQUET_COMPRESSION)
                writer.write_table(table); total += table.num_rows

        if writer is not None:
            writer.close()
            os.replace(tmp, out_file)
            log.info("Wrote %d events → %s", total, out_file)
        else:
            if os.path.exists(tmp): os.remove(tmp)
            log.info("No events for range %s-%s", start_h, end_h)
    except Exception as e:
        log.exception("Error batch %s-%s: %s", start_h, end_h, e)
        if writer is not None:
            try: writer.close()
            except: pass
        if os.path.exists(tmp): os.remove(tmp)
        raise

def main():
    ensure_dirs()
    print("\n" + "=" * 60)
    print("  CAPA 2 — UTXO Events (streaming, sin índices)")
    print("=" * 60)
    print("  1) Borrar todo y empezar desde 0")
    print("  2) Continuar desde el último bloque procesado")
    print("  3) Rollback último batch completo")
    print("=" * 60)
    choice = input("Selecciona 1, 2 o 3: ").strip()

    if choice == "1":
        if os.path.exists(CAPA2_DIR): shutil.rmtree(CAPA2_DIR)
        ensure_dirs()
        if os.path.exists(STATE_FILE): os.remove(STATE_FILE)
        save_state(-1)
        log.info("Reset completo")
        return
    elif choice == "3":
        state = load_state(); last = int(state.get("last_processed", -1))
        if last < 0: print("No hay estado."); return
        batch_start = (last // BLOCK_BATCH_SIZE) * BLOCK_BATCH_SIZE
        batch_end = batch_start + BLOCK_BATCH_SIZE - 1
        deleted = 0
        if os.path.exists(EVENTS_DIR):
            for f in os.listdir(EVENTS_DIR):
                if not f.endswith(".parquet"): continue
                try: a, b = map(int, f.replace(".parquet", "").split("_")[-2:])
                except: continue
                if a == batch_start and b == batch_end:
                    os.remove(os.path.join(EVENTS_DIR, f)); deleted += 1
        save_state(batch_start - 1)
        print(f"Rollback batch {batch_start}-{batch_end} ({deleted} archivos).")
        return
    else:
        state = load_state()

    tip = get_tip_height()
    if tip < 0: print("No hay Capa 1."); return
    start = int(state.get("last_processed", -1)) + 1
    if start > tip: print("Sin bloques nuevos."); return

    total_batches = (tip - start + 1 + BLOCK_BATCH_SIZE - 1) // BLOCK_BATCH_SIZE
    print(f"\nBloques: {start:,} → {tip:,} | Batches: {total_batches}\n")
    
    for h in tqdm(range(start, tip + 1, BLOCK_BATCH_SIZE), desc="Procesando", unit="batch"):
        batch_end = min(h + BLOCK_BATCH_SIZE - 1, tip)
        try:
            process_range_streaming(h, batch_end)
            save_state(batch_end)
        except Exception as e:
            log.error("Error batch %d: %s", h, e); return
    log.info("Capa 2 completada")
    print("✅ Capa 2 completada")

if __name__ == "__main__":
    main()
