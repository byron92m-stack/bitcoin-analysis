#!/usr/bin/env python3
"""
CAPA 7 — Balance real por address.
Paso 1: External sort por prefix (ambos archivos)
Paso 2: Anti-join por batches de 1024 prefixes (hash tables caben en RAM)
Paso 3: UNION ALL + GROUP BY → capa7_balance.parquet
"""
import os, time, duckdb

PROJECT = "/media/SSD4T/btc-etl"
PARQUET = os.path.join(PROJECT, "parquet")
TMPDIR  = os.path.join(PROJECT, "tmp_duckdb")

CREATES_SRC   = os.path.join(PARQUET, "capa6_creates.parquet")
SPENDS_SRC    = os.path.join(PARQUET, "capa6_spends.parquet")
CREATES_SORT  = os.path.join(PARQUET, "capa6_creates_sorted.parquet")
SPENDS_SORT   = os.path.join(PARQUET, "capa6_spends_sorted.parquet")
C7_OUTPUT     = os.path.join(PARQUET, "capa7_balance.parquet")

os.makedirs(TMPDIR, exist_ok=True)

MEMORY = "16GB"
THREADS = 2
RG_SIZE = 1_000_000
BATCH_PREFIXES = 1024

con = duckdb.connect()
con.execute(f"SET memory_limit = '{MEMORY}'")
con.execute(f"SET threads = {THREADS}")
con.execute(f"SET temp_directory = '{TMPDIR}'")

# ═══════════════════════════════════════════════════════════════
# PASO 1: External sort por prefix
# ═══════════════════════════════════════════════════════════════

for label, src, dst, cols in [
    ("CREATES", CREATES_SRC, CREATES_SORT, "*"),
    ("SPENDS",  SPENDS_SRC,  SPENDS_SORT,  "txid, vout, prefix"),
]:
    if os.path.exists(dst):
        gb = os.path.getsize(dst)/1024**3
        print(f"[{label}] Sorted ya existe ({gb:.1f} GB), saltando...")
        continue
    
    gb_in = os.path.getsize(src)/1024**3
    print(f"\n[{label}] Ordenando {gb_in:.1f} GB por prefix...")
    t0 = time.monotonic()
    
    con.execute(f"""
        COPY (SELECT {cols} FROM read_parquet('{src}') ORDER BY prefix)
        TO '{dst}' (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE {RG_SIZE})
    """)
    
    gb_out = os.path.getsize(dst)/1024**3
    elapsed = time.monotonic() - t0
    print(f"[{label}] {gb_out:.1f} GB en {elapsed/60:.1f} min")

# ═══════════════════════════════════════════════════════════════
# PASO 2: Anti-join por batches (NOT EXISTS)
# ═══════════════════════════════════════════════════════════════

BATCH_DIR = os.path.join(PARQUET, "capa7_batches")
os.makedirs(BATCH_DIR, exist_ok=True)

for f in os.listdir(BATCH_DIR):
    os.remove(os.path.join(BATCH_DIR, f))

TOTAL_PREFIXES = 65536
N_BATCHES = TOTAL_PREFIXES // BATCH_PREFIXES

print(f"\n[PASO 2] Anti-join con NOT EXISTS: {N_BATCHES} batches × {BATCH_PREFIXES} prefixes\n")

for batch_idx in range(N_BATCHES):
    p_start = batch_idx * BATCH_PREFIXES
    p_end   = p_start + BATCH_PREFIXES - 1
    hex_start = f"{p_start:04x}"
    hex_end   = f"{p_end:04x}"
    
    batch_file = os.path.join(BATCH_DIR, f"batch_{batch_idx:04d}.parquet")
    
    t0 = time.monotonic()
    con.execute(f"""
        COPY (
            SELECT c.address, CAST(SUM(c.value_sats) AS BIGINT) as balance, MAX(c.height) as last_seen
            FROM read_parquet('{CREATES_SORT}') c
            WHERE c.prefix >= '{hex_start}' AND c.prefix <= '{hex_end}'
              AND NOT EXISTS (
                SELECT 1 FROM read_parquet('{SPENDS_SORT}') s
                WHERE s.prefix >= '{hex_start}' AND s.prefix <= '{hex_end}'
                  AND s.txid = c.txid AND s.vout = c.vout
              )
            GROUP BY c.address
        ) TO '{batch_file}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    elapsed = time.monotonic() - t0
    
    mb = os.path.getsize(batch_file)/1024**2
    print(f"  Batch {batch_idx+1:>3}/{N_BATCHES} [{hex_start}..{hex_end}]: {mb:.0f} MB en {elapsed:.0f}s")

# ═══════════════════════════════════════════════════════════════
# PASO 3: UNION ALL final
# ═══════════════════════════════════════════════════════════════

print(f"\n[PASO 3] Consolidando {N_BATCHES} batches → capa7_balance.parquet...")
t0 = time.monotonic()

con.execute(f"""
    COPY (
        SELECT address, CAST(SUM(balance) AS BIGINT) as balance_sats, MAX(last_seen) as last_seen_height
        FROM read_parquet('{BATCH_DIR}/batch_*.parquet')
        GROUP BY address
    ) TO '{C7_OUTPUT}' (FORMAT PARQUET, COMPRESSION ZSTD)
""")

gb = os.path.getsize(C7_OUTPUT)/1024**3
n = con.execute(f"SELECT count(*) FROM read_parquet('{C7_OUTPUT}')").fetchone()[0]
elapsed = time.monotonic() - t0
print(f"[PASO 3] {gb:.1f} GB, {n:,.0f} addresses en {elapsed:.0f}s")

print(f"\n{'='*60}")
print(f"✅ Capa 7: {n:,.0f} addresses con balance_sats ({gb:.1f} GB)")

con.close()
