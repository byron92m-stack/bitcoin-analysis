#!/usr/bin/env python3
"""
CAPA 3 — Block Metrics (Fees + Subsidios) - FAST VERSION
Estrategia: cargar outputs del batch en RAM, merge masivo.
Velocidad: ~5-10 segundos por batch de 250 bloques.
"""
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
# CONFIG
# ============================================================
PROJECT_ROOT = "/media/SSD4T/btc-etl"
CAPA1_DIR = os.path.join(PROJECT_ROOT, "parquet", "capa1_btccore_parquet")
CAPA3_DIR = os.path.join(PROJECT_ROOT, "parquet", "capa3_block_metrics")

INPUTS_DIR = os.path.join(CAPA1_DIR, "inputs")
OUTPUTS_DIR = os.path.join(CAPA1_DIR, "outputs")
BLOCKS_DIR = os.path.join(CAPA1_DIR, "blocks")

METRICS_DIR = os.path.join(CAPA3_DIR, "blocks")

STATE_FILE = os.path.join(PROJECT_ROOT, "state_capa3_block_metrics.json")
LOG_DIR = os.path.join(PROJECT_ROOT, "logs")
LOG_FILE = os.path.join(LOG_DIR, "capa3_block_metrics.log")

BLOCK_BATCH_SIZE = 250

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
log = logging.getLogger("capa3")

# ============================================================
# HELPERS
# ============================================================
def get_subsidy(height):
    halvings = int(height) // 210000
    if halvings >= 64:
        return 0
    return int(50 * 100_000_000 / (2 ** halvings))

def utc_now():
    return datetime.now(timezone.utc).isoformat()

def load_state():
    if not os.path.exists(STATE_FILE):
        return {"last_processed": -1}
    with open(STATE_FILE, "r") as f:
        return json.load(f)

def save_state(height):
    with open(STATE_FILE, "w") as f:
        json.dump({
            "last_processed": int(height),
            "updated_at": utc_now()
        }, f, indent=2)

def ensure_dirs():
    os.makedirs(CAPA3_DIR, exist_ok=True)
    os.makedirs(METRICS_DIR, exist_ok=True)

def get_tip_height():
    files = sorted([f for f in os.listdir(BLOCKS_DIR) 
                    if f.endswith('.parquet') and '.tmp' not in f])
    if not files:
        return -1
    parts = files[-1].replace(".parquet", "").split("_")
    return int(parts[-1])

def files_for_range(base_dir, start_h, end_h):
    result = []
    if not os.path.exists(base_dir):
        return result
    for f in os.listdir(base_dir):
        if not f.endswith('.parquet') or '.tmp' in f:
            continue
        parts = f.replace(".parquet", "").split("_")
        try:
            a, b = int(parts[-2]), int(parts[-1])
        except:
            continue
        if not (b < start_h or a > end_h):
            result.append(os.path.join(base_dir, f))
    return sorted(result)

# ============================================================
# CORE RÁPIDO
# ============================================================
def process_batch_fast(start_h, end_h):
    """Procesa un batch de 250 bloques con merge masivo en RAM."""
    
    # 1. Cargar bloques del rango (fuente principal: height, hash, time, nTx)
    block_files = files_for_range(BLOCKS_DIR, start_h, end_h)
    df_blocks = None
    if block_files:
        df_blocks = ds.dataset(block_files, format="parquet").to_table(
            filter=(ds.field("height") >= start_h) & (ds.field("height") <= end_h)
        ).to_pandas()
        df_blocks = df_blocks[['height', 'hash', 'time', 'nTx']].rename(columns={'hash': 'block_hash'})
    else:
        print(f"  ⚠ No se encontraron bloques para {start_h}-{end_h}")
        return
    
    # 2. Cargar inputs coinbase del rango
    input_files = files_for_range(INPUTS_DIR, start_h, end_h)
    df_coinbase_txs = pd.DataFrame()
    if input_files:
        df_inputs = ds.dataset(input_files, format="parquet").to_table(
            filter=(ds.field("height") >= start_h) & (ds.field("height") <= end_h) &
                   (ds.field("is_coinbase") == True)
        ).to_pandas()
        df_coinbase_txs = df_inputs[['txid', 'height']].drop_duplicates()
    
    # 3. Cargar outputs del rango
    output_files = files_for_range(OUTPUTS_DIR, start_h, end_h)
    df_outputs = pd.DataFrame()
    if output_files:
        df_outputs = ds.dataset(output_files, format="parquet").to_table(
            filter=(ds.field("height") >= start_h) & (ds.field("height") <= end_h)
        ).to_pandas()
    
    # 4. Calcular fees: sumar outputs de coinbase por altura
    if not df_outputs.empty and not df_coinbase_txs.empty:
        # Filtrar solo outputs de transacciones coinbase
        coinbase_outputs = df_outputs.merge(
            df_coinbase_txs,
            on=['txid', 'height'],
            how='inner'
        )
        # Sumar por altura
        fees_df = coinbase_outputs.groupby('height').agg(
            coinbase_total_sats=('value_sats', 'sum')
        ).reset_index()
    else:
        fees_df = pd.DataFrame(columns=['height', 'coinbase_total_sats'])
    
    # 5. Merge con bloques
    result = df_blocks.merge(fees_df, on='height', how='left')
    result['coinbase_total_sats'] = result['coinbase_total_sats'].fillna(0).astype('int64')
    
    # 6. Calcular subsidio y fees
    result['subsidy_sats'] = result['height'].apply(get_subsidy)
    result['fees_sats'] = result['coinbase_total_sats'] - result['subsidy_sats']
    
    # Si no hay datos de coinbase, fees = 0 (bloques sin transacciones o error)
    result.loc[result['fees_sats'] < 0, 'fees_sats'] = 0
    
    # 7. Seleccionar columnas finales
    cols = ['height', 'block_hash', 'time', 'nTx', 'subsidy_sats', 'fees_sats']
    result = result[cols].sort_values('height')
    
    # 8. Guardar
    metrics_file = os.path.join(METRICS_DIR, f"block_metrics_{start_h:07d}_{end_h:07d}.parquet")
    tmp = metrics_file + ".tmp"
    
    pq.write_table(
        pa.Table.from_pandas(result, preserve_index=False),
        tmp,
        compression="zstd",
        compression_level=6
    )
    os.replace(tmp, metrics_file)
    
    total_fees = result['fees_sats'].sum()
    total_btc = total_fees / 1e8
    log.info(f"Batch {start_h}-{end_h}: {len(result)} bloques, fees={total_btc:.4f} BTC")

# ============================================================
# MAIN
# ============================================================
def main():
    print("\n" + "=" * 60)
    print("  CAPA 3 — Block Metrics (Fees + Subsidios) FAST")
    print("=" * 60)
    print("  1) Borrar todo y empezar desde 0")
    print("  2) Continuar desde el último bloque procesado")
    print("  3) Rollback último batch completo")
    print("=" * 60)
    
    choice = input("Selecciona una opción [1-3]: ").strip()
    
    if choice == "1":
        print("\n🗑 Reset completo solicitado.")
        if os.path.exists(CAPA3_DIR):
            shutil.rmtree(CAPA3_DIR)
        ensure_dirs()
        if os.path.exists(STATE_FILE):
            os.remove(STATE_FILE)
        save_state(-1)
        print("✅ Reset ejecutado.")
    
    elif choice == "3":
        state = load_state()
        last = int(state.get("last_processed", -1))
        if last < 0:
            print("❌ No hay estado válido.")
            return
        batch_start = (last // BLOCK_BATCH_SIZE) * BLOCK_BATCH_SIZE
        batch_end = batch_start + BLOCK_BATCH_SIZE - 1
        target = f"block_metrics_{batch_start:07d}_{batch_end:07d}.parquet"
        if os.path.exists(os.path.join(METRICS_DIR, target)):
            os.remove(os.path.join(METRICS_DIR, target))
            log.info(f"Rollback: eliminado {target}")
        save_state(batch_start - 1)
        print(f"✅ Rollback batch {batch_start}-{batch_end}")
        return
    
    else:
        print("\n▶ Continuando desde el último estado.")
    
    ensure_dirs()
    state = load_state()
    start = int(state.get("last_processed", -1)) + 1
    tip = get_tip_height()
    
    if tip < 0:
        print("❌ No se encontraron bloques en Capa 1.")
        return
    
    if start > tip:
        print(f"✅ Sin bloques nuevos. Tip: {tip}, Último: {start - 1}")
        return
    
    total_blocks = tip - start + 1
    total_batches = (total_blocks + BLOCK_BATCH_SIZE - 1) // BLOCK_BATCH_SIZE
    
    print(f"\n⚡ CAPA 3 FAST MODE")
    print(f"   Bloques: {start:,} → {tip:,}")
    print(f"   Total: {total_blocks:,} bloques")
    print(f"   Batches: {total_batches} (de {BLOCK_BATCH_SIZE} bloques)")
    print(f"   Est. tiempo: ~{total_batches * 8 / 60:.0f} min\n")
    
    current = start
    batch_num = 0
    start_time = datetime.now()
    
    while current <= tip:
        batch_start = current
        batch_end = min(current + BLOCK_BATCH_SIZE - 1, tip)
        batch_num += 1
        
        elapsed = (datetime.now() - start_time).total_seconds()
        rate = (batch_num - 1) / elapsed * 60 if elapsed > 0 else 0
        
        print(f"Batch {batch_num}/{total_batches}: {batch_start:,}→{batch_end:,} "
              f"[{rate:.0f} batches/min]", end=" ", flush=True)
        
        try:
            t0 = datetime.now()
            process_batch_fast(batch_start, batch_end)
            save_state(batch_end)
            dt = (datetime.now() - t0).total_seconds()
            print(f"✓ {dt:.1f}s")
            current = batch_end + 1
        except Exception as e:
            print(f"❌ Error: {e}")
            log.error(f"Error en batch {batch_start}-{batch_end}: {e}")
            return
    
    total_time = (datetime.now() - start_time).total_seconds()
    print(f"\n✅ Capa 3 completada en {total_time/60:.1f} minutos")
    print(f"   Último bloque: {tip:,}")
    log.info(f"Capa 3 completada. {total_blocks} bloques en {total_time/60:.1f} min")

if __name__ == "__main__":
    main()
