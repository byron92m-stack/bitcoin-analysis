#!/bin/bash
# ============================================================
# 🐋 WEEKLY WHALE TRACKER UPDATE — Domingo 10:00 PM
# Abre bitcoind, espera 20 min, corre pipeline, cierra bitcoind
# ============================================================
set -e
export PATH="/usr/bin:/usr/local/bin:/bin:$PATH"

PROJECT="/media/SSD4T/btc-etl"
VENV="$PROJECT/venvetl/bin/activate"
LOG="$PROJECT/logs/weekly_update_$(date +%Y-%m-%d).log"

mkdir -p "$(dirname "$LOG")"
echo "========================================" | tee -a "$LOG"
echo "  🐋 WEEKLY UPDATE — $(date)" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"

# ═══════════════════════════════════════════════════════════
# 1. ABRIR BITCOIN DAEMON
# ═══════════════════════════════════════════════════════════
echo "" | tee -a "$LOG"
echo "🟢 Iniciando bitcoind..." | tee -a "$LOG"
if pgrep -x "bitcoind" > /dev/null; then
    echo "   bitcoind ya está corriendo" | tee -a "$LOG"
else
    bitcoind -daemon
    echo "   Esperando 20 min para sincronizar nuevos bloques..." | tee -a "$LOG"
    sleep 1200
fi

LOCAL=$(curl -s --data-binary '{"jsonrpc":"1.0","id":"curl","method":"getblockcount","params":[]}' -H 'content-type:text/plain;' http://localhost:8332/ 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin)['result'])" 2>/dev/null || echo 0)
echo "   Bloque actual: $LOCAL" | tee -a "$LOG"

# ═══════════════════════════════════════════════════════════
# 2. ACTIVAR VENV
# ═══════════════════════════════════════════════════════════
source "$VENV"
cd "$PROJECT"

# ═══════════════════════════════════════════════════════════
# 3. CAPA 1: Extraer datos (rollback + continuar)
# ═══════════════════════════════════════════════════════════
echo "" | tee -a "$LOG"
echo "=== CAPA 1: Rollback + Continuar ===" | tee -a "$LOG"
python etl/capa1_btccore_parquet.py <<< $'3\n' | tail -3 | tee -a "$LOG"
python etl/capa1_btccore_parquet.py <<< $'2\n' | tail -3 | tee -a "$LOG"

# CERRAR BITCOIN DAEMON después de Capa 1
echo "" | tee -a "$LOG"
echo "🔴 Deteniendo bitcoind..." | tee -a "$LOG"
bitcoin-cli stop 2>/dev/null || pkill bitcoind
sleep 5
echo "   bitcoind detenido" | tee -a "$LOG"

# ═══════════════════════════════════════════════════════════
# 4. CAPAS 2-5: Rollback + Continuar
# ═══════════════════════════════════════════════════════════
for capa in 2 3 4 5; do
    echo "" | tee -a "$LOG"
    echo "=== CAPA $capa: Rollback + Continuar ===" | tee -a "$LOG"
    python etl/capa${capa}_*.py <<< $'3\n' 2>/dev/null | tail -3 | tee -a "$LOG"
    python etl/capa${capa}_*.py <<< $'2\n' 2>/dev/null | tail -3 | tee -a "$LOG"
done

# ═══════════════════════════════════════════════════════════
# 5. CAPAS 6-8: Auto-reset
# ═══════════════════════════════════════════════════════════
echo "" | tee -a "$LOG"
echo "=== CAPA 6: Streaming ===" | tee -a "$LOG"
python etl/capa6_streaming.py | tail -5 | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "=== CAPA 7: Balance ===" | tee -a "$LOG"
python etl/capa7_balance.py | tail -3 | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "=== CAPA 8: >10 BTC ===" | tee -a "$LOG"
python etl/capa8_balance_gt10.py | tail -5 | tee -a "$LOG"

# ═══════════════════════════════════════════════════════════
# 5.5 LIMPIAR ARCHIVOS TEMPORALES
echo "" | tee -a "$LOG"
echo "=== Limpiando temporales ===" | tee -a "$LOG"
rm -f "$PROJECT/parquet/capa6_creates_sorted.parquet"
rm -f "$PROJECT/parquet/capa6_spends_sorted.parquet"
rm -rf "$PROJECT/parquet/capa7_batches"
rm -rf "$PROJECT/tmp_duckdb"
echo "✅ Temporales eliminados" | tee -a "$LOG"

# 6. ACTUALIZAR CLICKHOUSE
# ═══════════════════════════════════════════════════════════
echo "" | tee -a "$LOG"
echo "=== ClickHouse ===" | tee -a "$LOG"
TODAY=$(date +%F)
ln -sf "$PROJECT/parquet/capa7_balance.parquet" /media/SSD4T/clickhouse/user_files/capa7/capa7_balance.parquet
cp "$PROJECT/parquet/capa8_balance_gt10_${TODAY}.parquet" "$PROJECT/parquet/capa8_balance_gt10.parquet"
ln -sf "$PROJECT/parquet/capa8_balance_gt10.parquet" /media/SSD4T/clickhouse/user_files/capa8/capa8_balance_gt10.parquet

for table in blocks txs inputs outputs utxo_events block_metrics btc_1d btc_1m capa7_balance capa8_balance_gt10; do
    curl -s --fail "http://localhost:8123" --data "DETACH TABLE ${table}" > /dev/null 2>&1 || { echo "❌ ClickHouse no responde" | tee -a "$LOG"; exit 1; }
    curl -s --fail "http://localhost:8123" --data "ATTACH TABLE ${table}" > /dev/null 2>&1
done
echo "✅ ClickHouse actualizado" | tee -a "$LOG"

# ═══════════════════════════════════════════════════════════
# 7. SNAPSHOT + DETECCIÓN
# ═══════════════════════════════════════════════════════════
echo "" | tee -a "$LOG"
echo "=== 🐋 Whale Snapshot ===" | tee -a "$LOG"
curl -s --fail "http://localhost:8123" --data "
INSERT INTO whale_snapshots
SELECT toDate('${TODAY}') as week, address, btc
FROM capa8_balance_gt10
WHERE btc >= 10
" && echo "✅ Snapshot: ${TODAY}" | tee -a "$LOG" || { echo "❌ Fallo snapshot" | tee -a "$LOG"; exit 1; }

echo "" | tee -a "$LOG"
echo "=== 📈 Tendencias ===" | tee -a "$LOG"
curl -s "http://localhost:8123" --data "
SELECT 
    CASE 
        WHEN up_weeks >= 3 AND total_delta > 100 THEN 'ACUMULANDO FUERTE'
        WHEN up_weeks >= 2 AND total_delta > 0 THEN 'Acumulando'
        WHEN down_weeks >= 3 AND total_delta < -100 THEN 'VENDIENDO FUERTE'
        WHEN down_weeks >= 2 AND total_delta < 0 THEN 'Vendiendo'
        ELSE 'Estable'
    END as trend,
    COUNT(*) as whales,
    SUM(total_delta) as total_btc
FROM (
    SELECT address, SUM(delta) as total_delta,
           SUM(CASE WHEN delta > 0 THEN 1 ELSE 0 END) as up_weeks,
           SUM(CASE WHEN delta < 0 THEN 1 ELSE 0 END) as down_weeks,
           COUNT(*) as weeks_present,
           AVG(btc) as avg_btc
    FROM (
        SELECT address, week, btc,
               btc - LAG(btc) OVER (PARTITION BY address ORDER BY week) as delta
        FROM whale_snapshots
        WHERE week >= toDate('${TODAY}') - INTERVAL 28 DAY
    ) WHERE delta IS NOT NULL
    GROUP BY address HAVING COUNT(*) >= 3
) GROUP BY trend ORDER BY total_btc DESC
FORMAT PrettyCompact
" | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"
echo "  ✅ WEEKLY UPDATE COMPLETADO — $(date)" | tee -a "$LOG"
echo "  Log: $LOG" | tee -a "$LOG"
echo "========================================" | tee -a "$LOG"
