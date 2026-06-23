#!/bin/bash
# ============================================================
# 🐋 WEEKLY WHALE TRACKER UPDATE — Domingo 10:00 PM
# ============================================================
set -e

PROJECT="/media/SSD4T/btc-etl"
VENV="$PROJECT/venvetl/bin/activate"
LOG="$PROJECT/logs/weekly_update_$(date +%Y-%m-%d).log"
BTCORE="bitcoin-qt"

echo "========================================" | tee -a "$LOG"
echo "  🐋 WEEKLY UPDATE — $(date)" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"

# 1. ABRIR BITCOIN CORE
echo "" | tee -a "$LOG"
echo "🟢 Abriendo Bitcoin Core..." | tee -a "$LOG"
if pgrep -x "bitcoin-qt" > /dev/null; then
    echo "   Bitcoin Core ya está corriendo" | tee -a "$LOG"
else
    $BTCORE --daemon
    echo "   Esperando 60s a que cargue..." | tee -a "$LOG"
    sleep 60
fi

# 2. ESPERAR SINCRONIZACIÓN
echo "" | tee -a "$LOG"
echo "⏳ Verificando sincronización..." | tee -a "$LOG"
echo "⏳ Esperando 10 min para sincronizar los nuevos bloques..." | tee -a "$LOG"
sleep 600
LOCAL=$(bitcoin-cli getblockcount 2>/dev/null || echo 0)
echo "✅ Listo: bloque local=$LOCAL" | tee -a "$LOG"

# 3. ACTIVAR VENV
# Dar tiempo extra para que termine de procesar el último bloque
echo "" | tee -a "$LOG"
echo "⏳ Esperando 10 min para asegurar procesamiento completo..." | tee -a "$LOG"
sleep 600

source "$VENV"
cd "$PROJECT"

# 4. PIPELINE: Rollback + Continuar
for capa in 1 2 3 4 5; do
    echo "" | tee -a "$LOG"
    echo "=== CAPA $capa: Rollback + Continuar ===" | tee -a "$LOG"
    python etl/capa${capa}_*.py <<< $'3\n' 2>/dev/null | tail -3 | tee -a "$LOG"
    python etl/capa${capa}_*.py <<< $'2\n' 2>/dev/null | tail -3 | tee -a "$LOG"
    if [ $capa -eq 1 ]; then
        echo "" | tee -a "$LOG"
        echo "🔴 Cerrando Bitcoin Core..." | tee -a "$LOG"
        bitcoin-cli stop 2>/dev/null || pkill bitcoin-qt
        sleep 5
        echo "   Bitcoin Core cerrado" | tee -a "$LOG"
    fi
done

# 5. CAPAS AUTO-RESET
echo "" | tee -a "$LOG"
echo "=== CAPA 6: Streaming (auto-reset) ===" | tee -a "$LOG"
python etl/capa6_streaming.py | tail -5 | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "=== CAPA 7: Balance (auto-reset) ===" | tee -a "$LOG"
python etl/capa7_balance.py | tail -3 | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "=== CAPA 8: >10 BTC ===" | tee -a "$LOG"
python etl/capa8_balance_gt10.py | tail -5 | tee -a "$LOG"

# 6. ACTUALIZAR CLICKHOUSE (TODAS las tablas File(Parquet))
echo "" | tee -a "$LOG"
echo "=== ClickHouse: Refrescando todas las tablas ===" | tee -a "$LOG"
TODAY=$(date +%F)

# Actualizar symlinks para capa7 y capa8
ln -sf "$PROJECT/parquet/capa7_balance.parquet" /media/SSD4T/clickhouse/user_files/capa7/capa7_balance.parquet
cp "$PROJECT/parquet/capa8_balance_gt10_${TODAY}.parquet" "$PROJECT/parquet/capa8_balance_gt10.parquet"
ln -sf "$PROJECT/parquet/capa8_balance_gt10.parquet" /media/SSD4T/clickhouse/user_files/capa8/capa8_balance_gt10.parquet

# Refrescar TODAS las tablas que leen de Parquet
for table in blocks txs inputs outputs utxo_events block_metrics btc_1d btc_1m capa7_balance capa8_balance_gt10; do
    curl -s "http://localhost:8123" --data "DETACH TABLE ${table}" > /dev/null 2>&1
    curl -s "http://localhost:8123" --data "ATTACH TABLE ${table}" > /dev/null 2>&1
done
echo "✅ ClickHouse: 10 tablas refrescadas" | tee -a "$LOG"

# 7. COMPARACIÓN SEMANAL
echo "" | tee -a "$LOG"
echo "=== 📊 Comparación semanal ===" | tee -a "$LOG"
python3 - "$PROJECT" "$LOG" << 'PYEOF'
import duckdb, os, sys
PROJECT = sys.argv[1]
files = sorted([f for f in os.listdir(f"{PROJECT}/parquet") if f.startswith("capa8_balance_gt10_") and f.endswith(".parquet")])
if len(files) >= 2:
    old_f = f"{PROJECT}/parquet/{files[-2]}"
    new_f = f"{PROJECT}/parquet/{files[-1]}"
    con = duckdb.connect()
    old = con.execute(f"SELECT address, btc FROM read_parquet('{old_f}')").fetchdf()
    new = con.execute(f"SELECT address, btc FROM read_parquet('{new_f}')").fetchdf()
    na, nl = len(set(new['address']) - set(old['address'])), len(set(old['address']) - set(new['address']))
    print(f"📊 {os.path.basename(old_f)} → {os.path.basename(new_f)}")
    print(f"   🆕 Nuevas: {na:,} | 🚪 Salieron: {nl:,}")
    merged = old.merge(new, on='address', suffixes=('_old','_new'))
    merged['delta'] = merged['btc_new'] - merged['btc_old']
    for label, df in [("📈 Aumentos", merged.nlargest(5,'delta')), ("📉 Bajadas", merged.nsmallest(5,'delta'))]:
        print(f"   {label}:")
        for _, r in df.iterrows():
            print(f"      {r['address'][:35]}: {r['btc_old']:,.0f} → {r['btc_new']:,.0f} BTC (Δ{r['delta']:+,.0f})")
    con.close()
else:
    print("   (Primera corrida, sin histórico)")
PYEOF

echo "" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"
echo "  ✅ WEEKLY UPDATE COMPLETADO — $(date)" | tee -a "$LOG"
echo "  Log: $LOG" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"
