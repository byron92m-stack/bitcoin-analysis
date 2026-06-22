#!/usr/bin/env python3
# ============================================================
# BTC ETL — CAPA 1 (Bitcoin Core → Parquet)
# UTXO-safe, compact, reproducible
# Rutas corregidas para /media/SSD4T
# ============================================================

import os
import json
import time
import shutil
import logging
from typing import Any, Dict, List, Optional
from decimal import Decimal, InvalidOperation, ROUND_DOWN

import pandas as pd
import requests
from tqdm import tqdm
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from requests.exceptions import ConnectionError as ReqConnectionError, ReadTimeout
from urllib3.exceptions import ProtocolError
from http.client import RemoteDisconnected

# ============================================================
# CONFIG
# ============================================================

RPC_USER = "bitcoinrpc"
RPC_PASSWORD = "superseguro123"
RPC_URL = "http://127.0.0.1:8332"

PROJECT_ROOT = "/media/SSD4T/btc-etl"
PARQUET_ROOT = os.path.join(PROJECT_ROOT, "parquet")
FAST_BASE = os.path.join(PARQUET_ROOT, "capa1_btccore_parquet")

STATE_FILE = os.path.join(PROJECT_ROOT, "state_capa1_btccore_parquet.json")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_FILE = os.path.join(LOG_DIR, "etl_capa1_btccore_parquet.log")

DIRS = {
    "blocks": os.path.join(FAST_BASE, "blocks"),
    "txs": os.path.join(FAST_BASE, "txs"),
    "inputs": os.path.join(FAST_BASE, "inputs"),
    "outputs": os.path.join(FAST_BASE, "outputs"),
}

BLOCK_BATCH_SIZE = 250

RPC_TIMEOUT = 120
RPC_RETRIES_TOTAL = 8
RPC_RETRY_BACKOFF = 0.6

SATOSHI = 100_000_000

# ============================================================
# LOGGING
# ============================================================

def setup_logger() -> logging.Logger:
    os.makedirs(LOG_DIR, exist_ok=True)
    logger = logging.getLogger("capa1_btccore_parquet")
    logger.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s")

    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)

    sh = logging.StreamHandler()
    sh.setFormatter(fmt)

    if not logger.handlers:
        logger.addHandler(fh)
        logger.addHandler(sh)

    return logger


logger = setup_logger()

# ============================================================
# HTTP SESSION
# ============================================================

def build_session() -> requests.Session:
    s = requests.Session()
    retry = Retry(
        total=RPC_RETRIES_TOTAL,
        connect=RPC_RETRIES_TOTAL,
        read=RPC_RETRIES_TOTAL,
        status=RPC_RETRIES_TOTAL,
        backoff_factor=RPC_RETRY_BACKOFF,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["POST"],
        raise_on_status=False,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    s.mount("http://", adapter)
    return s


SESSION = build_session()

# ============================================================
# STATE
# ============================================================

def load_state() -> Dict[str, Any]:
    if not os.path.exists(STATE_FILE):
        return {"last_processed_height": -1, "last_processed_hash": None}
    with open(STATE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(state: Dict[str, Any]) -> None:
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)

# ============================================================
# RPC
# ============================================================

_rpc_id = 0


def rpc_call(method: str, params: Optional[List[Any]] = None) -> Any:
    global _rpc_id
    _rpc_id += 1
    payload = {"jsonrpc": "1.0", "id": _rpc_id, "method": method, "params": params or []}
    auth = (RPC_USER, RPC_PASSWORD)

    for attempt in range(1, RPC_RETRIES_TOTAL + 1):
        try:
            r = SESSION.post(RPC_URL, json=payload, auth=auth, timeout=RPC_TIMEOUT)
            data = r.json()
            if data.get("error"):
                raise RuntimeError(data["error"])
            return data["result"]
        except (ReqConnectionError, ReadTimeout, RemoteDisconnected, ProtocolError):
            time.sleep(min(10.0, RPC_RETRY_BACKOFF * (2 ** (attempt - 1))))
    raise RuntimeError(f"RPC failed: {method}")


def get_block_count() -> int:
    return int(rpc_call("getblockcount"))


def get_block_hash(height: int) -> str:
    return rpc_call("getblockhash", [height])


def get_block(block_hash: str) -> Dict[str, Any]:
    return rpc_call("getblock", [block_hash, 2])

# ============================================================
# HELPERS
# ============================================================

def safe_int(x: Any) -> Optional[int]:
    try:
        return int(x) if x is not None else None
    except Exception:
        return None


def btc_to_sats(x: Any) -> Optional[int]:
    if x is None:
        return None
    try:
        d = Decimal(str(x)).quantize(Decimal("0.00000001"), rounding=ROUND_DOWN)
        return int(d * SATOSHI)
    except (InvalidOperation, ValueError, TypeError):
        return None


def vin_is_coinbase(vin: Dict[str, Any]) -> bool:
    return "coinbase" in vin

# ============================================================
# PROCESS BLOCK
# ============================================================

def process_block(blk: Dict[str, Any]):
    height = safe_int(blk.get("height"))
    bh = blk.get("hash")

    blocks, txs, inputs, outputs = [], [], [], []

    blocks.append({
        "height": height,
        "hash": bh,
        "time": safe_int(blk.get("time")),
        "mediantime": safe_int(blk.get("mediantime")),
        "version": safe_int(blk.get("version")),
        "bits": blk.get("bits"),
        "difficulty": blk.get("difficulty"),
        "chainwork": blk.get("chainwork"),
        "size": safe_int(blk.get("size")),
        "weight": safe_int(blk.get("weight")),
        "strippedsize": safe_int(blk.get("strippedsize")),
        "nTx": safe_int(blk.get("nTx")),
        "previousblockhash": blk.get("previousblockhash"),
        "nextblockhash": blk.get("nextblockhash"),
    })

    for tx in blk.get("tx", []):
        txid = tx.get("txid")
        wtxid = tx.get("hash")

        txs.append({
            "height": height,
            "block_hash": bh,
            "txid": txid,
            "wtxid": wtxid,
            "version": safe_int(tx.get("version")),
            "size": safe_int(tx.get("size")),
            "vsize": safe_int(tx.get("vsize")),
            "weight": safe_int(tx.get("weight")),
            "locktime": safe_int(tx.get("locktime")),
            "vin_count": len(tx.get("vin", [])),
            "vout_count": len(tx.get("vout", [])),
        })

        for idx, vin in enumerate(tx.get("vin", [])):
            if vin_is_coinbase(vin):
                inputs.append({
                    "height": height,
                    "block_hash": bh,
                    "txid": txid,
                    "vin_index": idx,
                    "is_coinbase": True,
                    "sequence": safe_int(vin.get("sequence")),
                    "prev_txid": None,
                    "prev_vout": None,
                })
            else:
                inputs.append({
                    "height": height,
                    "block_hash": bh,
                    "txid": txid,
                    "vin_index": idx,
                    "is_coinbase": False,
                    "sequence": safe_int(vin.get("sequence")),
                    "prev_txid": vin.get("txid"),
                    "prev_vout": safe_int(vin.get("vout")),
                })

        for vout in tx.get("vout", []):
            spk = vout.get("scriptPubKey", {}) or {}
            outputs.append({
                "height": height,
                "block_hash": bh,
                "txid": txid,
                "vout": safe_int(vout.get("n")),
                "value_sats": btc_to_sats(vout.get("value")),
                "script_type": spk.get("type"),
                "script_hex": spk.get("hex"),
            })

    return blocks, txs, inputs, outputs

# ============================================================
# WRITE PARQUET
# ============================================================

def write_parquet(df: pd.DataFrame, table: str, start: int, end: int):
    if df.empty:
        return

    if table == "inputs" and "prev_vout" in df.columns:
        df["prev_vout"] = df["prev_vout"].astype("Int64")

    path = DIRS[table]
    os.makedirs(path, exist_ok=True)

    fname = f"{table}_{start:07d}_{end:07d}.parquet"
    tmp = os.path.join(path, fname + ".tmp")
    final = os.path.join(path, fname)

    df.to_parquet(
        tmp,
        index=False,
        engine="pyarrow",
        compression="zstd",
        compression_level=6,
    )
    os.replace(tmp, final)

# ============================================================
# MAIN
# ============================================================

def ensure_dirs():
    os.makedirs(FAST_BASE, exist_ok=True)
    for d in DIRS.values():
        os.makedirs(d, exist_ok=True)


def main():
    print("\n=== CAPA 1 — Bitcoin Core → Parquet ===")
    print("1) Reset completo (borrar parquet + state)")
    print("2) Continuar desde último bloque procesado")
    print("3) Rollback último batch completo")
    print("======================================")

    choice = input("Selecciona una opción [1-3]: ").strip()

    # OPCIÓN 1 — RESET COMPLETO
    if choice == "1":
        print("Reset completo solicitado.")
        logger.info("Reset completo solicitado.")

        if os.path.exists(FAST_BASE):
            shutil.rmtree(FAST_BASE)

        ensure_dirs()

        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)

        print("Reset completo ejecutado. Empezando desde bloque 0.")
        logger.info("Reset completo ejecutado.")

    # OPCIÓN 3 — ROLLBACK ÚLTIMO BATCH
    elif choice == "3":
        print("Rollback de último batch solicitado.")
        logger.info("Rollback de último batch solicitado.")

        ensure_dirs()
        state = load_state()
        last = int(state.get("last_processed_height", -1))

        if last < 0:
            print("No hay estado válido para rollback.")
            return

        batch_start = (last // BLOCK_BATCH_SIZE) * BLOCK_BATCH_SIZE
        batch_end = batch_start + BLOCK_BATCH_SIZE - 1

        print(f"Eliminando batch completo: {batch_start} - {batch_end}")
        logger.info(f"Rollback batch {batch_start}-{batch_end}")

        for name, path in DIRS.items():
            if not os.path.exists(path):
                continue
            for fname in os.listdir(path):
                if not fname.endswith(".parquet"):
                    continue
                try:
                    s, e = map(int, fname.replace(".parquet", "").split("_")[-2:])
                except Exception:
                    continue
                if s == batch_start and e == batch_end:
                    os.remove(os.path.join(path, fname))
                    logger.info(f"Eliminado {fname}")

        save_state({
            "last_processed_height": batch_start - 1,
            "last_processed_hash": None
        })

        print("Rollback de batch completado.")
        logger.info("Rollback de batch completado.")
        return

    else:
        print("Continuando desde el último estado.")
        logger.info("Continuación solicitada.")

    # INGESTA NORMAL
    ensure_dirs()
    state = load_state()
    last = int(state.get("last_processed_height", -1))
    tip = get_block_count()

    start_height = last + 1
    if start_height > tip:
        print("No hay bloques nuevos para procesar.")
        logger.info("No hay bloques nuevos para procesar.")
        return

    print(f"\nProcesando bloques {start_height} → {tip}")
    logger.info(f"Procesando bloques {start_height} → {tip}")

    current = start_height
    while current <= tip:
        batch_start = current
        batch_end = min(current + BLOCK_BATCH_SIZE - 1, tip)

        print(f"\n=== Procesando batch {batch_start} → {batch_end} ===")
        logger.info(f"Procesando batch {batch_start}-{batch_end}")

        blocks_rows = []
        txs_rows = []
        inputs_rows = []
        outputs_rows = []

        for h in tqdm(
            range(batch_start, batch_end + 1),
            desc=f"Bloques {batch_start}-{batch_end}",
            unit="blk"
        ):
            try:
                bh = get_block_hash(h)
                blk = get_block(bh)

                b, t, i, o = process_block(blk)

                blocks_rows.extend(b)
                txs_rows.extend(t)
                inputs_rows.extend(i)
                outputs_rows.extend(o)

                state["last_processed_height"] = h
                state["last_processed_hash"] = bh

            except Exception as e:
                logger.error(f"Error procesando bloque {h}: {e}")
                print(f"Error procesando bloque {h}: {e}")
                print("Guardando estado y saliendo.")
                save_state(state)
                return

        write_parquet(pd.DataFrame(blocks_rows), "blocks", batch_start, batch_end)
        write_parquet(pd.DataFrame(txs_rows), "txs", batch_start, batch_end)
        write_parquet(pd.DataFrame(inputs_rows), "inputs", batch_start, batch_end)
        write_parquet(pd.DataFrame(outputs_rows), "outputs", batch_start, batch_end)

        save_state(state)
        current = batch_end + 1

    print("\nCapa 1 completada correctamente.")
    logger.info("Capa 1 completada correctamente.")


if __name__ == "__main__":
    main()
