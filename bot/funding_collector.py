"""
Funding Rate Collector — Binance Futures WebSocket
Guarda funding rate histórico en ClickHouse para el bot.
Ejecutar en background: python bot/funding_collector.py &
"""
import os, sys, json, time
import clickhouse_connect
from datetime import datetime, timezone
from websocket import create_connection

sys.path.insert(0, os.path.dirname(__file__))

def create_table():
    client = clickhouse_connect.get_client(host='localhost', port=8123)
    client.command('''
        CREATE TABLE IF NOT EXISTS funding_rates (
            timestamp DateTime64(3),
            symbol String,
            funding_rate Float64,
            mark_price Float64
        )
        ENGINE = MergeTree()
        ORDER BY (symbol, timestamp)
    ''')
    return client

def main():
    print("Funding Rate Collector — Starting...")
    client = create_table()
    print("Table ready.")
    
    ws = create_connection("wss://fstream.binance.com/ws/btcusdt@markPrice@1s")
    print("Connected to Binance Futures WebSocket.\n")
    
    last_save = datetime.now(timezone.utc)
    
    while True:
        try:
            data = json.loads(ws.recv())
            
            now = datetime.now(timezone.utc)
            timestamp = datetime.fromtimestamp(data['E'] / 1000, timezone.utc)
            funding_rate = float(data['r'])
            mark_price = float(data['p'])
            
            # Guardar cada 1 minuto para no saturar
            if (now - last_save).seconds >= 60:
                client.insert(
                    'funding_rates',
                    [[timestamp, 'BTCUSDT', funding_rate, mark_price]],
                    column_names=['timestamp', 'symbol', 'funding_rate', 'mark_price']
                )
                last_save = now
                print(f"[{timestamp.strftime('%Y-%m-%d %H:%M')}] Funding: {funding_rate*100:+.4f}% | Mark: ${mark_price:,.0f}")
                
        except KeyboardInterrupt:
            print("\nCollector stopped.")
            ws.close()
            break
        except Exception as e:
            print(f"Error: {e}")
            time.sleep(1)

if __name__ == "__main__":
    main()
