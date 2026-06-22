#!/usr/bin/env python3
"""
CAPA 5 — Filtra creates y spends (TODOS los creates, COALESCE address)
Corrección: COALESCE(address, 'UNKNOWN') para no perder creates sin address.
Escribe: parquet/capa5_filtered/filtered_0000000_0000249.parquet
"""
import os, json, shutil, duckdb
from tqdm import tqdm

PROJECT_ROOT = "/media/SSD4T/btc-etl"
CAPA2_DIR = os.path.join(PROJECT_ROOT, "parquet", "capa2_utxo_parquet", "utxo_events")
CAPA5_DIR = os.path.join(PROJECT_ROOT, "parquet", "capa5_filtered")
STATE_FILE = os.path.join(PROJECT_ROOT, "state_capa5_filtered.json")
BLOCK_BATCH_SIZE = 250

def load_state():
    if not os.path.exists(STATE_FILE): return {"last_processed_height": -1}
    with open(STATE_FILE) as f: return json.load(f)
def save_state(h):
    with open(STATE_FILE, "w") as f: json.dump({"last_processed_height": int(h)}, f)

def get_event_files():
    if not os.path.exists(CAPA2_DIR): return []
    return sorted([f for f in os.listdir(CAPA2_DIR) if f.endswith('.parquet') and '.tmp' not in f])
def get_tip():
    files = get_event_files()
    if not files: return -1
    try: return int(files[-1].replace(".parquet","").split("_")[-1])
    except: return -1

def process_batch(start_h, end_h, con):
    batch_files = [os.path.join(CAPA2_DIR, f) for f in get_event_files()
                   if not (int(f.replace(".parquet","").split("_")[-1]) < start_h or int(f.replace(".parquet","").split("_")[-2]) > end_h)]
    if not batch_files: return
    file_list = ', '.join([f"'{f}'" for f in batch_files])
    out = os.path.join(CAPA5_DIR, f"filtered_{start_h:07d}_{end_h:07d}.parquet")
    
    con.execute(f"""
        COPY (
            SELECT 'create' AS event_type, outpoint_txid AS txid, outpoint_vout AS vout, 
                   value_sats, COALESCE(address, outpoint_txid || ':' || outpoint_vout) AS address, height,
                   SUBSTRING(outpoint_txid, 1, 4) AS prefix
            FROM read_parquet([{file_list}])
            WHERE event_type = 'create'
            UNION ALL
            SELECT 'spend' AS event_type, outpoint_txid, outpoint_vout,
                   0 AS value_sats, '' AS address, height,
                   SUBSTRING(outpoint_txid, 1, 4) AS prefix
            FROM read_parquet([{file_list}])
            WHERE event_type = 'spend'
        ) TO '{out}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 500000)
    """)

def main():
    os.makedirs(CAPA5_DIR, exist_ok=True)
    print("\n" + "=" * 60)
    print("  CAPA 5 — Filtrar creates + spends (TODO address)")
    print("=" * 60)
    print("  1) Borrar todo y empezar desde 0")
    print("  2) Continuar desde el último bloque procesado")
    print("  3) Rollback último batch")
    print("=" * 60)
    choice = input("Selecciona [1-3]: ").strip()
    
    if choice == "1":
        if os.path.exists(CAPA5_DIR): shutil.rmtree(CAPA5_DIR)
        os.makedirs(CAPA5_DIR, exist_ok=True)
        if os.path.exists(STATE_FILE): os.remove(STATE_FILE)
        save_state(-1)
        print("✅ Reset ejecutado.")
        return
    elif choice == "3":
        state = load_state(); last = int(state.get("last_processed_height", -1))
        if last < 0: print("No hay estado."); return
        batch_start = (last // BLOCK_BATCH_SIZE) * BLOCK_BATCH_SIZE
        batch_end = batch_start + BLOCK_BATCH_SIZE - 1
        f = os.path.join(CAPA5_DIR, f"filtered_{batch_start:07d}_{batch_end:07d}.parquet")
        if os.path.exists(f): os.remove(f)
        save_state(batch_start - 1)
        print(f"✅ Rollback batch {batch_start}-{batch_end}")
        return
    
    state = load_state()
    start = int(state.get("last_processed_height", -1)) + 1
    tip = get_tip()
    if tip < 0: print("No hay Capa 2."); return
    if start > tip: print("Sin bloques nuevos."); return
    
    total_batches = (tip - start + 1 + BLOCK_BATCH_SIZE - 1) // BLOCK_BATCH_SIZE
    
    con = duckdb.connect()
    con.execute("SET memory_limit = '8GB'")
    con.execute("SET temp_directory = '/media/SSD4T/btc-etl/tmp'")
    con.execute("SET threads = 2")
    
    print(f"\nBloques: {start:,} → {tip:,} | Batches: {total_batches}\n")
    
    for h in tqdm(range(start, tip + 1, BLOCK_BATCH_SIZE), desc="Filtrando", unit="batch"):
        batch_end = min(h + BLOCK_BATCH_SIZE - 1, tip)
        try:
            process_batch(h, batch_end, con)
            save_state(batch_end)
        except Exception as e:
            print(f"Error batch {h}: {e}"); con.close(); return
    
    con.close()
    
    import glob
    total_files = len(glob.glob(f'{CAPA5_DIR}/filtered_*.parquet'))
    total_gb = sum(os.path.getsize(f) for f in glob.glob(f'{CAPA5_DIR}/filtered_*.parquet')) / 1024**3
    print(f"\n✅ Capa 5 completada: {total_files} archivos, {total_gb:.1f} GB")

if __name__ == "__main__":
    main()
