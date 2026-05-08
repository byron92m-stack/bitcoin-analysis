"""
Phase 7 — Paper Trading Simulator
Simula trades con $10,000 falsos usando el modelo entrenado.
Registra P&L, win rate, drawdown.
"""
import os, sys, json, time, joblib
import pandas as pd
import numpy as np
from datetime import datetime, timezone
from websocket import create_connection

sys.path.insert(0, os.path.dirname(__file__))
from config import *
from features import build_features
from live import load_model, build_live_features, get_fees_zscore

class PaperTrader:
    def __init__(self, initial_capital=10000):
        self.capital = initial_capital
        self.initial_capital = initial_capital
        self.position = 0  # 0 = flat, 1 = long
        self.entry_price = 0
        self.trades = []
        self.history = [initial_capital]
        
    def execute_signal(self, signal, price, confidence, zscore):
        """Ejecuta orden simulada."""
        if signal == 1 and self.position == 0:
            # LONG entry
            self.position = 1
            self.entry_price = price
            amount = self.capital * POSITION_SIZE
            print(f"   📈 LONG  | ${price:,.0f} | Size: ${amount:,.0f} | Conf: {confidence:.1%} | Z: {zscore:.2f}")
            
        elif signal == 0 and self.position == 1:
            # LONG exit
            ret = (price - self.entry_price) / self.entry_price
            pnl = self.capital * ret * POSITION_SIZE
            
            # Aplicar stop loss
            if ret < -STOP_LOSS:
                pnl = self.capital * (-STOP_LOSS) * POSITION_SIZE
            
            self.capital += pnl
            self.position = 0
            
            win = ret > 0
            self.trades.append({
                'entry': self.entry_price,
                'exit': price,
                'return': ret,
                'pnl': pnl,
                'win': win,
                'confidence': confidence,
                'zscore': zscore
            })
            
            emoji = "✅" if win else "❌"
            print(f"   {emoji} EXIT  | ${price:,.0f} | P&L: ${pnl:+,.0f} | Return: {ret:+.2%} | Capital: ${self.capital:,.0f}")
            
            self.history.append(self.capital)
    
    def print_summary(self):
        """Imprime resumen de performance."""
        if not self.trades:
            print("\n⚠️  No trades executed.")
            return
        
        returns = [t['return'] for t in self.trades]
        wins = sum(1 for t in self.trades if t['win'])
        total_return = (self.capital - self.initial_capital) / self.initial_capital
        
        # Sharpe
        if len(self.history) > 2:
            r = np.diff(self.history) / self.history[:-1]
            sharpe = np.mean(r) / np.std(r) * np.sqrt(24 * 365) if np.std(r) > 0 else 0
        else:
            sharpe = 0
        
        # Max drawdown
        peak = np.maximum.accumulate(self.history)
        dd = (np.array(self.history) - peak) / peak
        max_dd = dd.min() * 100
        
        print(f"\n{'='*60}")
        print(f"PAPER TRADING SUMMARY")
        print(f"{'='*60}")
        print(f"   Initial:     ${self.initial_capital:,.0f}")
        print(f"   Final:       ${self.capital:,.0f}")
        print(f"   Return:      {total_return:+.2%}")
        print(f"   Trades:      {len(self.trades)}")
        print(f"   Win Rate:    {wins/len(self.trades)*100:.1f}%")
        print(f"   Avg Return:  {np.mean(returns):+.4%}")
        print(f"   Sharpe:      {sharpe:.2f}")
        print(f"   Max DD:      {max_dd:.2f}%")
        print(f"{'='*60}")

def main():
    print("=" * 60)
    print("📊 Phase 7 — Paper Trading Simulator")
    print("=" * 60)
    
    model = load_model()
    trader = PaperTrader(INITIAL_CAPITAL)
    
    candles = []
    print("\n📡 Conectando a Binance WebSocket...")
    ws = create_connection("wss://stream.binance.com:9443/ws/btcusdt@kline_1h")
    print("✅ Conectado. Esperando velas de 1h...")
    print("   (Ctrl+C para detener y ver resultados)\n")
    
    try:
        while True:
            data = json.loads(ws.recv())
            kline = data['k']
            
            if kline['x']:
                candle = {
                    'open_time': pd.Timestamp(kline['t'], unit='ms'),
                    'open': float(kline['o']),
                    'high': float(kline['h']),
                    'low': float(kline['l']),
                    'close': float(kline['c']),
                    'volume': float(kline['v']),
                    'quote_volume': float(kline['q']),
                    'trades': int(kline['n'])
                }
                candles.append(candle)
                
                if len(candles) > 48:
                    candles = candles[-48:]
                
                if len(candles) >= 25:
                    df_1h = pd.DataFrame(candles)
                    fees_z = get_fees_zscore()
                    df_features = build_live_features(df_1h, fees_z)
                    
                    last_row = df_features.iloc[-1:][FEATURES]
                    
                    if not last_row.isna().any().any():
                        prob = model.predict_proba(last_row.values)[0, 1]
                        pred = 1 if prob >= MIN_CONFIDENCE else 0
                        
                        # Filtro Z-Score
                        if pred == 1 and fees_z <= 1.0:
                            pred = 0
                        
                        time_str = datetime.now().strftime("%Y-%m-%d %H:00")
                        print(f"\n{time_str} | Price: ${float(kline['c']):,.0f} | "
                              f"Signal: {'LONG' if pred==1 else 'WAIT'} | "
                              f"Conf: {prob:.1%} | Z: {fees_z:.2f}")
                        
                        trader.execute_signal(pred, float(kline['c']), prob, fees_z)
                        
    except KeyboardInterrupt:
        ws.close()
        trader.print_summary()
        print("\n👋 Paper trading terminado.")

if __name__ == "__main__":
    main()
