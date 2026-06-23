#!/usr/bin/env python3
"""CAPA 6 — Streaming scan + filter + write. 2 pasadas lineales."""
import glob, time, duckdb, os

PROJECT_ROOT = "/media/SSD4T/btc-etl"
CAPA5_DIR = os.path.join(PROJECT_ROOT, "parquet", "capa5_filtered")
CREATES_FILE = os.path.join(PROJECT_ROOT, "parquet", "capa6_creates.parquet")
SPENDS_FILE = os.path.join(PROJECT_ROOT, "parquet", "capa6_spends.parquet")

# Siempre borrar archivos anteriores (reset automático)
for f in [CREATES_FILE, SPENDS_FILE]:
    if os.path.exists(f):
        os.remove(f)
        print(f"🗑️  Borrado: {os.path.basename(f)}")

all_files = sorted(glob.glob(f"{CAPA5_DIR}/filtered_*.parquet"))
print(f"Archivos: {len(all_files)}")

con = duckdb.connect()
con.execute("SET memory_limit = '24GB'")
con.execute("SET threads = 8")

# FASE 1: CREATES
print("\n=== FASE 1: CREATES ===")
t0 = time.monotonic()
con.execute(f"""
    COPY (
        SELECT txid, vout, address, value_sats, prefix, height
        FROM read_parquet('{CAPA5_DIR}/filtered_*.parquet')
        WHERE event_type = 'create'
    ) TO '{CREATES_FILE}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 1000000)
""")
gb = os.path.getsize(CREATES_FILE) / 1024**3
elapsed = time.monotonic() - t0
print(f"Creates: {gb:.1f} GB en {elapsed/60:.1f} min")

# FASE 2: SPENDS
print("\n=== FASE 2: SPENDS ===")
t0 = time.monotonic()
con.execute(f"""
    COPY (
        SELECT txid, vout, prefix
        FROM read_parquet('{CAPA5_DIR}/filtered_*.parquet')
        WHERE event_type = 'spend'
    ) TO '{SPENDS_FILE}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 1000000)
""")
gb = os.path.getsize(SPENDS_FILE) / 1024**3
elapsed = time.monotonic() - t0
print(f"Spends:  {gb:.1f} GB en {elapsed/60:.1f} min")

con.close()
print("\n✅ Capa 6 completada")
