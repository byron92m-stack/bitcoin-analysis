#!/usr/bin/env python3
"""
CAPA 8 — Filtra >10 BTC. Archivo con fecha para mantener histórico.
También copia a capa8_balance_gt10.parquet (latest) para el notebook y ClickHouse.
"""
import os, duckdb, shutil
from datetime import date

PROJECT = "/media/SSD4T/btc-etl"
PARQUET = os.path.join(PROJECT, "parquet")
C7_INPUT = os.path.join(PARQUET, "capa7_balance.parquet")

today = date.today().isoformat()
C8_HISTORICO = os.path.join(PARQUET, f"capa8_balance_gt10_{today}.parquet")
C8_LATEST = os.path.join(PARQUET, "capa8_balance_gt10.parquet")

MIN_SATS = 1_000_000_000  # 10 BTC

con = duckdb.connect()
con.execute("SET memory_limit = '4GB'")

n_total = con.execute(f"SELECT count(*) FROM read_parquet('{C7_INPUT}')").fetchone()[0]

con.execute(f"""
    COPY (
        SELECT address, balance_sats,
               balance_sats / 100_000_000.0 AS btc, last_seen_height
        FROM read_parquet('{C7_INPUT}')
        WHERE balance_sats >= {MIN_SATS}
        ORDER BY balance_sats DESC
    ) TO '{C8_HISTORICO}' (FORMAT PARQUET, COMPRESSION ZSTD)
""")

# Copiar a latest para el notebook y ClickHouse
shutil.copy(C8_HISTORICO, C8_LATEST)

gb = os.path.getsize(C8_HISTORICO) / 1024**3
n_filtered = con.execute(f"SELECT count(*) FROM read_parquet('{C8_HISTORICO}')").fetchone()[0]

print(f"✅ Capa 8: {n_filtered:,} addresses >10 BTC ({gb:.2f} GB)")
print(f"   Filtradas de {n_total:,} totales ({n_filtered/n_total*100:.2f}%)")
print(f"   Histórico: capa8_balance_gt10_{today}.parquet")
print(f"   Último:    capa8_balance_gt10.parquet")

con.close()
