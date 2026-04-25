import os
import glob
import pandas as pd
from tqdm import tqdm
from io import StringIO

# ============================================================
# SCHEMA BTC_ML (basado en Capa 3 corregida)
# ============================================================

BTC_ML_COLUMNS = [
    ("timestamp", "TIMESTAMPTZ"),
    ("year", "SMALLINT"),
    ("month", "SMALLINT"),
    ("day", "SMALLINT"),
    ("hour", "SMALLINT"),
    ("dow", "SMALLINT"),
    ("is_weekend", "SMALLINT"),

    # Mercado
    ("open", "DOUBLE PRECISION"),
    ("high", "DOUBLE PRECISION"),
    ("low", "DOUBLE PRECISION"),
    ("close", "DOUBLE PRECISION"),
    ("volume", "DOUBLE PRECISION"),
    ("close_time", "TIMESTAMPTZ"),
    ("quote_volume", "DOUBLE PRECISION"),
    ("trades", "BIGINT"),

    # On-chain (Capa 1 FAST V2 corregida)
    ("height", "DOUBLE PRECISION"),
    ("hash", "TEXT"),
    ("time", "DOUBLE PRECISION"),
    ("size", "DOUBLE PRECISION"),
    ("weight", "DOUBLE PRECISION"),
    ("n_tx", "DOUBLE PRECISION"),
    ("difficulty", "DOUBLE PRECISION"),
    ("total_output_value", "DOUBLE PRECISION"),
    ("inputs_count", "DOUBLE PRECISION"),
    ("outputs_count", "DOUBLE PRECISION"),
    ("segwit_tx_count", "DOUBLE PRECISION"),
    ("coinbase_tx_count", "DOUBLE PRECISION"),

    # Features ML
    ("ret_1m", "DOUBLE PRECISION"),
    ("ret_5m", "DOUBLE PRECISION"),
    ("ret_15m", "DOUBLE PRECISION"),
    ("ret_1h", "DOUBLE PRECISION"),
    ("vol_1h", "DOUBLE PRECISION"),
    ("vol_24h", "DOUBLE PRECISION"),
    ("ma_5", "DOUBLE PRECISION"),
    ("ma_15", "DOUBLE PRECISION"),
    ("ma_60", "DOUBLE PRECISION"),
    ("ema_5", "DOUBLE PRECISION"),
    ("ema_15", "DOUBLE PRECISION"),
    ("ema_60", "DOUBLE PRECISION"),

    # Targets
    ("target_ret_15m", "DOUBLE PRECISION"),
    ("target_dir_15m", "SMALLINT"),
    ("target_ret_1h", "DOUBLE PRECISION"),
    ("target_vol_1h", "DOUBLE PRECISION")
]

# ============================================================
# CREATE SCHEMA: POSTGRES
# ============================================================

def create_schema_postgres():
    import psycopg2

    print("\n=== CREANDO SCHEMA EN POSTGRES ===\n")

    conn = psycopg2.connect("dbname=btcetl user=nw host=localhost")
    cur = conn.cursor()

    cols = ",\n    ".join([f"{name} {dtype}" for name, dtype in BTC_ML_COLUMNS])

    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS btc_ml (
            {cols}
        );
    """)

    conn.commit()
    cur.close()
    conn.close()

    print("✔ Tabla btc_ml creada en PostgreSQL.\n")

# ============================================================
# CREATE SCHEMA: CLICKHOUSE
# ============================================================

def create_schema_clickhouse():
    import clickhouse_connect

    print("\n=== CREANDO SCHEMA EN CLICKHOUSE (PRO) ===\n")

    client = clickhouse_connect.get_client(host="localhost", port=8123)

    try:
        client.command("DROP TABLE IF EXISTS btc_ml")
    except Exception as e:
        print(f"⚠ Warning DROP TABLE: {e}")

    cols = []
    for name, dtype in BTC_ML_COLUMNS:
        if dtype == "TIMESTAMPTZ":
            cols.append(f"{name} DateTime64(6)")
        elif dtype == "TEXT":
            cols.append(f"{name} Nullable(String)")
        elif dtype == "SMALLINT":
            cols.append(f"{name} Int16")
        elif dtype == "BIGINT":
            cols.append(f"{name} Int64")
        else:
            cols.append(f"{name} Float64")

    cols_sql = ",\n    ".join(cols)

    client.command(f"""
        CREATE TABLE btc_ml (
            {cols_sql}
        )
        ENGINE = MergeTree()
        ORDER BY (timestamp)
    """)

    print("✔ Tabla btc_ml creada en ClickHouse.\n")

# ============================================================
# LOAD CLICKHOUSE
# ============================================================

def load_clickhouse():
    import clickhouse_connect

    print("\n=== CARGANDO EN CLICKHOUSE (PRO) ===\n")

    client = clickhouse_connect.get_client(host="localhost", port=8123)

    files = glob.glob("/home/nw/btc-etl/parquet/capa3_ml/*/*/*.parquet")
    print(f"Encontrados {len(files)} archivos Parquet\n")

    expected_cols = [name for name, _ in BTC_ML_COLUMNS]

    for f in tqdm(files, desc="ClickHouse", ncols=80):
        try:
            df = pd.read_parquet(f)

            df = df.dropna(how="all")
            df = df.where(pd.notnull(df), None)

            # Mantener solo columnas válidas
            df = df[[c for c in expected_cols if c in df.columns]]

            client.insert_df("btc_ml", df)

        except Exception as e:
            print(f"\n⚠ Error en archivo {f}: {e}\n")

    print("\n✔ ClickHouse: Carga completada.\n")

# ============================================================
# LOAD POSTGRES
# ============================================================

def load_postgres():
    import psycopg2

    print("\n=== CARGANDO EN POSTGRES ===\n")

    conn = psycopg2.connect("dbname=btcetl user=nw host=localhost")
    cur = conn.cursor()

    files = glob.glob("/home/nw/btc-etl/parquet/capa3_ml/*/*/*.parquet")
    print(f"Encontrados {len(files)} archivos Parquet\n")

    expected_cols = [name for name, _ in BTC_ML_COLUMNS]

    for f in tqdm(files, desc="Postgres", ncols=80):
        try:
            df = pd.read_parquet(f)

            # 🔥 ORDENAR COLUMNAS EXACTAMENTE COMO LA TABLA
            df = df[[c for c in expected_cols if c in df.columns]]

            # 🔥 RELLENAR COLUMNAS FALTANTES CON NULL
            for col in expected_cols:
                if col not in df.columns:
                    df[col] = None

            # 🔥 REORDENAR DEFINITIVAMENTE
            df = df[expected_cols]

            buffer = StringIO()
            df.to_csv(buffer, index=False, header=False)
            buffer.seek(0)

            cur.copy_expert("COPY btc_ml FROM STDIN WITH CSV", buffer)
            conn.commit()

        except Exception as e:
            print(f"\n⚠ Error en archivo {f}: {e}\n")
            conn.rollback()

    cur.close()
    conn.close()

    print("\n✔ Postgres: Carga completada.\n")


# ============================================================
# MENU PRINCIPAL
# ============================================================

def main_menu():
    while True:
        print("\n=== CAPA 4: SCHEMA + CARGA ===")
        print("1) Crear schema (ClickHouse + PostgreSQL)")
        print("2) Cargar SOLO ClickHouse")
        print("3) Cargar SOLO PostgreSQL")
        print("4) Cargar TODO (ClickHouse + PostgreSQL)")
        print("5) Salir")

        choice = input("\nSelecciona una opción: ").strip()

        if choice == "1":
            create_schema_clickhouse()
            create_schema_postgres()

        elif choice == "2":
            load_clickhouse()

        elif choice == "3":
            load_postgres()

        elif choice == "4":
            create_schema_clickhouse()
            create_schema_postgres()
            load_clickhouse()
            load_postgres()

        elif choice == "5":
            print("\nSaliendo...\n")
            break

        else:
            print("\nOpción inválida.\n")

if __name__ == "__main__":
    main_menu()

