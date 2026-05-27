"""
Phase 8 — Bitcoin On-Chain Dashboard
Streamlit + ClickHouse + Plotly
"""
import streamlit as st
import clickhouse_connect
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import os

st.set_page_config(page_title="Bitcoin On-Chain Analytics", layout="wide", page_icon="₿")
st.title("₿ Bitcoin On-Chain Analytics Dashboard")
st.caption(f"ClickHouse live data | {datetime.now().strftime('%Y-%m-%d %H:%M')}")

@st.cache_data(ttl=300)
def query(sql):
    client = clickhouse_connect.get_client(host='localhost', port=8123)
    return client.query_df(sql)

# ============================================================
# ROW 1: MÉTRICAS PRINCIPALES
# ============================================================
col1, col2, col3, col4, col5 = st.columns(5)

metrics = query("""
    SELECT 
        count() AS blocks,
        sum(fees_sats)/1e8 AS total_fees,
        max(fees_sats)/1e8 AS max_fee,
        max(height) AS last_block
    FROM block_metrics
""")
price = query("SELECT close FROM btc_1d ORDER BY date DESC LIMIT 1")
vol = query("SELECT volatility_30d FROM btc_1d ORDER BY date DESC LIMIT 1")

col1.metric("Último Bloque", f"{metrics['last_block'].iloc[0]:,.0f}")
col2.metric("Precio BTC", f"${price['close'].iloc[0]:,.0f}")
col3.metric("Volatilidad 30d", f"{vol['volatility_30d'].iloc[0]*100:.2f}%")
col4.metric("Fees Totales", f"{metrics['total_fees'].iloc[0]:,.0f} BTC")
col5.metric("Fee Máximo", f"{metrics['max_fee'].iloc[0]:.2f} BTC")

# ============================================================
# ROW 2: PRECIO + VOLATILIDAD
# ============================================================
st.subheader("💹 Precio BTC & Volatilidad")
df_price = query("""
    SELECT date, close, volatility_30d, volume_usdt
    FROM btc_1d WHERE date >= '2017-07-14' ORDER BY date
""")

fig1 = make_subplots(rows=2, cols=1, shared_xaxes=True, 
                     row_heights=[0.7, 0.3], vertical_spacing=0.05)

fig1.add_trace(go.Scatter(x=df_price['date'], y=df_price['close'], name='BTC/USD',
                          line=dict(color='#1f77b4', width=1.5)), row=1, col=1)
fig1.add_trace(go.Scatter(x=df_price['date'], y=df_price['volatility_30d']*100, name='Volatilidad 30d (%)',
                          line=dict(color='#ff7f0e', width=1), fill='tozeroy', fillcolor='rgba(255,127,14,0.1)'), row=2, col=1)

fig1.update_layout(height=500, margin=dict(l=0, r=0, t=0, b=0),
                   hovermode='x unified', template='plotly_white',
                   showlegend=False)
fig1.update_yaxes(title_text='Precio (USD)', row=1, col=1)
fig1.update_yaxes(title_text='Volatilidad (%)', row=2, col=1)
st.plotly_chart(fig1, use_container_width=True)

# ============================================================
# ROW 3: FEES DIARIOS + VOLUMEN
# ============================================================
st.subheader("📊 Fees & Volumen")
df_fees = query("""
    SELECT toDate(toDateTime(time)) AS date, sum(fees_sats)/1e8 AS fees_btc
    FROM block_metrics WHERE toDate(toDateTime(time)) >= '2017-07-14'
    GROUP BY date ORDER BY date
""")
df_fees = df_fees.merge(df_price[['date', 'volume_usdt']], on='date', how='left')
df_fees['MA30'] = df_fees['fees_btc'].rolling(30).mean()

fig2 = make_subplots(rows=2, cols=1, shared_xaxes=True,
                     row_heights=[0.5, 0.5], vertical_spacing=0.05)

fig2.add_trace(go.Bar(x=df_fees['date'], y=df_fees['fees_btc'], name='Fees diarios',
                      marker_color='orange', marker_line_width=0, opacity=0.4), row=1, col=1)
fig2.add_trace(go.Scatter(x=df_fees['date'], y=df_fees['MA30'], name='MA30',
                          line=dict(color='#ff7f0e', width=2)), row=1, col=1)
fig2.add_trace(go.Bar(x=df_fees['date'], y=df_fees['volume_usdt']/1e9, name='Volumen (B USD)',
                      marker_color='#1f77b4', marker_line_width=0, opacity=0.5), row=2, col=1)

fig2.add_vline(x='2020-05-11', line_dash='dash', line_color='red', opacity=0.5, row=1, col=1)
fig2.add_vline(x='2024-04-20', line_dash='dash', line_color='red', opacity=0.5, row=1, col=1)

fig2.update_layout(height=500, margin=dict(l=0, r=0, t=0, b=0),
                   hovermode='x unified', template='plotly_white', showlegend=False)
fig2.update_yaxes(title_text='Fees (BTC)', type='log', row=1, col=1)
fig2.update_yaxes(title_text='Volumen (B USD)', row=2, col=1)
st.plotly_chart(fig2, use_container_width=True)

# ============================================================
# ROW 4: Z-SCORE + FEES VS PRECIO
# ============================================================
col_left, col_right = st.columns(2)

with col_left:
    st.subheader("🎯 Fee Z-Score")
    df_z_raw = query("""
        SELECT toDate(toDateTime(time)) AS date, sum(fees_sats)/1e8 AS fees_btc
        FROM block_metrics WHERE toDate(toDateTime(time)) >= '2017-07-14'
        GROUP BY date ORDER BY date
    """)
    df_z_raw['fees_ma30'] = df_z_raw['fees_btc'].rolling(30).mean()
    df_z_raw['fees_std30'] = df_z_raw['fees_btc'].rolling(30).std()
    df_z_raw['fees_zscore'] = (df_z_raw['fees_btc'] - df_z_raw['fees_ma30']) / df_z_raw['fees_std30']
    df_z = df_z_raw.dropna()

    fig3 = go.Figure()
    fig3.add_trace(go.Scatter(x=df_z['date'], y=df_z['fees_zscore'], name='Z-Score',
                              line=dict(color='purple', width=1)))
    fig3.add_hline(y=2, line_dash='dash', line_color='red', annotation_text='+2')
    fig3.add_hline(y=-2, line_dash='dash', line_color='green', annotation_text='-2')
    fig3.add_hline(y=0, line_color='gray', line_width=0.5)
    fig3.update_layout(height=350, margin=dict(l=0, r=0, t=0, b=0),
                       yaxis_title='Z-Score', template='plotly_white')
    st.plotly_chart(fig3, use_container_width=True)

with col_right:
    st.subheader("🔵 Fees vs Precio (log-log)")
    df_scatter = df_fees.merge(df_price[['date', 'close']], on='date', how='inner')
    
    fig4 = go.Figure()
    fig4.add_trace(go.Scatter(
        x=df_scatter['close'], y=df_scatter['fees_btc'],
        mode='markers', marker=dict(size=3, color='#1f77b4', opacity=0.3),
        name='Fees vs Precio', text=df_scatter['date'].astype(str)
    ))
    fig4.update_layout(height=350, margin=dict(l=0, r=0, t=0, b=0),
                       xaxis_title='Precio BTC (USD)', yaxis_title='Fees (BTC)',
                       xaxis_type='log', yaxis_type='log', template='plotly_white')
    st.plotly_chart(fig4, use_container_width=True)

# ============================================================
# ROW 5: BOT SIGNALS + TOP 10
# ============================================================
col_left2, col_right2 = st.columns(2)

with col_left2:
    st.subheader("🤖 Señales del Bot (últimas 50)")
    signals_file = '/media/SSD4T/btc-etl/bot/logs/live_signals.csv'
    if os.path.exists(signals_file):
        df_signals = pd.read_csv(signals_file).tail(50)
        df_signals['color'] = df_signals['signal'].map({'LONG': 'green', 'WAIT': 'gray'})
        
        fig5 = go.Figure()
        fig5.add_trace(go.Scatter(
            x=df_signals['timestamp'], y=df_signals['confidence'],
            mode='markers', marker=dict(color=df_signals['color'], size=8),
            text=df_signals['signal'] + ' | $' + df_signals['price'].astype(str),
            name='Señales'
        ))
        fig5.add_hline(y=0.60, line_dash='dash', line_color='green', annotation_text='LONG threshold')
        fig5.update_layout(height=350, margin=dict(l=0, r=0, t=0, b=0),
                           yaxis_title='Confianza', template='plotly_white')
        st.plotly_chart(fig5, use_container_width=True)
    else:
        st.info("Señales no disponibles. Ejecutá python bot/live.py")

with col_right2:
    st.subheader("🔝 Top 10 Días con Más Fees")
    df_top = query("""
        SELECT toDate(toDateTime(time)) AS Fecha,
               sum(fees_sats)/1e8 AS Fees_BTC,
               count() AS Bloques
        FROM block_metrics WHERE toDate(toDateTime(time)) >= '2017-07-14'
        GROUP BY Fecha ORDER BY Fees_BTC DESC LIMIT 10
    """)
    st.dataframe(df_top, use_container_width=True, hide_index=True)

st.caption("Built by Byron • Bitcoin Core + ClickHouse + Streamlit • MIT License")
