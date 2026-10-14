import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(page_title="NETCD 15 Dk Terminali", layout="wide", page_icon="⚡")

st.markdown("""
<style>
    div[data-testid="stMetricValue"] { font-size: 1.4rem; font-weight: bold; }
    .stAlert { padding: 10px; margin-bottom: 10px; }
</style>
""", unsafe_allow_html=True)

st.title("⚡ NETCD.IS 15 Dakikalık Gün İçi Terminali")

st.sidebar.header("Ayarlar")
ticker = st.sidebar.text_input("Hisse", value="NETCD.IS")
days = st.sidebar.selectbox("Görünüm Aralığı", ["5 Gün", "15 Gün", "30 Gün"], index=0)
day_map = {"5 Gün": "5d", "15 Gün": "15d", "30 Gün": "30d"}

# 60 saniye önbellek: Sayfa her açıldığında anında yüklenir
@st.cache_data(ttl=60)
def fetch_data(symbol, p_15m):
    d_15m = yf.download(symbol, period=p_15m, interval="15m", progress=False)
    d_daily = yf.download(symbol, period="5d", interval="1d", progress=False)
    return d_15m, d_daily

try:
    df_15m, df_daily = fetch_data(ticker, day_map[days])
except Exception as e:
    st.error("Veri çekilirken hata oluştu.")
    st.stop()

if df_15m.empty or df_daily.empty:
    st.warning("Veri bulunamadı veya borsa kapalı.")
    st.stop()

if isinstance(df_15m.columns, pd.MultiIndex):
    df_15m.columns = df_15m.columns.get_level_values(0)
if isinstance(df_daily.columns, pd.MultiIndex):
    df_daily.columns = df_daily.columns.get_level_values(0)

# Dünün Günlük Kapanışından Klasik Pivotlar (Hatasız Tarih Kontrolü)
# Eğer listenin son satırı bugüne aitse dünü (iloc[-2]), değilse en son tamamlanan günü (iloc[-1]) alır
today_date = pd.Timestamp.now().date()
if df_daily.index[-1].date() == today_date and len(df_daily) >= 2:
    last_closed_day = df_daily.iloc[-2]
else:
    last_closed_day = df_daily.iloc[-1]

H_day = float(last_closed_day['High'])
L_day = float(last_closed_day['Low'])
C_day = float(last_closed_day['Close'])

Pivot = (H_day + L_day + C_day) / 3
R1 = (2 * Pivot) - L_day
S1 = (2 * Pivot) - H_day
R2 = Pivot + (H_day - L_day)
S2 = Pivot - (H_day - L_day)

# 15 Dk Göstergeler
df_15m['EMA9'] = df_15m['Close'].ewm(span=9, adjust=False).mean()
df_15m['EMA21'] = df_15m['Close'].ewm(span=21, adjust=False).mean()

delta = df_15m['Close'].diff()
gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
loss = (-delta.where(delta < 0, 0)).abs().rolling(window=14).mean()
rs = gain / loss.replace(0, np.nan)
df_15m['RSI'] = 100 - (100 / (1 + rs))

# VWAP Hesabı
df_15m['Typical_Price'] = (df_15m['High'] + df_15m['Low'] + df_15m['Close']) / 3
df_15m['Date'] = df_15m.index.date
df_15m['Vol_Price'] = df_15m['Typical_Price'] * df_15m['Volume']
df_15m['Cum_Vol_Price'] = df_15m.groupby('Date')['Vol_Price'].cumsum()
df_15m['Cum_Vol'] = df_15m.groupby('Date')['Volume'].cumsum()
df_15m['VWAP'] = df_15m['Cum_Vol_Price'] / df_15m['Cum_Vol'].replace(0, np.nan)
df_15m['VWAP'] = df_15m['VWAP'].bfill().ffill()

curr = df_15m.iloc[-1]
prev = df_15m.iloc[-2]
last_price = float(curr['Close'])
curr_vwap = float(curr['VWAP'])
curr_rsi = float(curr['RSI'])
curr_ema9 = float(curr['EMA9'])
curr_ema21 = float(curr['EMA21'])

# Metrikler
m1, m2, m3, m4 = st.columns(4)
m1.metric("Son Fiyat", f"{last_price:.2f} TL", f"{last_price - float(prev['Close']):.2f} TL")
m2.metric("Gün İçi VWAP", f"{curr_vwap:.2f} TL", "VWAP Üstü" if last_price >= curr_vwap else "VWAP Altı")
m3.metric("RSI (14)", f"{curr_rsi:.2f}")
m4.metric("9 / 21 EMA", f"{curr_ema9:.2f} / {curr_ema21:.2f}")

# Durum Değerlendirmesi
bullish = (curr_ema9 > curr_ema21) and (last_price > curr_vwap)
if bullish and curr_rsi < 65:
    st.success(f"🟢 **GÜÇLÜ ALIM BÖLGESİ:** Fiyat VWAP ({curr_vwap:.2f} TL) üstünde, ivme yukarı.")
elif curr_rsi >= 70 or last_price >= R1:
    st.warning(f"⚠️ **DİRENÇ / AŞIRI ALIM:** R1 ({R1:.2f} TL) test ediliyor, kâr realizasyonu düşünülebilir.")
elif last_price < curr_vwap and curr_ema9 < curr_ema21:
    st.error(f"🔴 **SATICILI SEYİR:** Fiyat VWAP ve EMA'ların altında.")
else:
    st.info(f"⚪ **KONSOLİDASYON:** Denge seviyeleri etrafında yatay hareket.")

# Seviye Tablosu
st.markdown("### 📋 Günlük Seviye Tablosu (Midas Atlas Girişleri İçin)")
c_s, c_p, c_r = st.columns(3)
with c_s:
    st.write(f"🛑 **S1 Destek:** `{S1:.2f} TL` | **S2 Destek:** `{S2:.2f} TL`")
with c_p:
    st.write(f"⚖️ **Günlük Pivot:** `{Pivot:.2f} TL` | **VWAP:** `{curr_vwap:.2f} TL`")
with c_r:
    st.write(f"🚀 **R1 Kâr Al:** `{R1:.2f} TL` | **R2 Direnç:** `{R2:.2f} TL`")

# Grafik
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.07, row_heights=[0.72, 0.28])
fig.add_trace(go.Candlestick(x=df_15m.index, open=df_15m['Open'], high=df_15m['High'], low=df_15m['Low'], close=df_15m['Close'], name="15 Dk"), row=1, col=1)
fig.add_trace(go.Scatter(x=df_15m.index, y=df_15m['EMA9'], line=dict(color='#00e5ff', width=1.2), name="9 EMA"), row=1, col=1)
fig.add_trace(go.Scatter(x=df_15m.index, y=df_15m['EMA21'], line=dict(color='#ffab00', width=1.2), name="21 EMA"), row=1, col=1)
fig.add_trace(go.Scatter(x=df_15m.index, y=df_15m['VWAP'], line=dict(color='#e040fb', width=1.5, dash='dash'), name="VWAP"), row=1, col=1)

fig.add_hline(y=R2, line_dash="dash", line_color="#ff1744", annotation_text=f"R2: {R2:.2f}", row=1, col=1)
fig.add_hline(y=R1, line_dash="dot", line_color="#ff5252", annotation_text=f"R1: {R1:.2f}", row=1, col=1)
fig.add_hline(y=Pivot, line_dash="solid", line_color="#ffd600", annotation_text=f"Pivot: {Pivot:.2f}", row=1, col=1)
fig.add_hline(y=S1, line_dash="dot", line_color="#69f0ae", annotation_text=f"S1: {S1:.2f}", row=1, col=1)
fig.add_hline(y=S2, line_dash="dash", line_color="#00e676", annotation_text=f"S2: {S2:.2f}", row=1, col=1)

fig.add_trace(go.Scatter(x=df_15m.index, y=df_15m['RSI'], line=dict(color='#ffffff', width=1.2), name="RSI"), row=2, col=1)
fig.add_hline(y=70, line_dash="dash", line_color="red", row=2, col=1)
fig.add_hline(y=30, line_dash="dash", line_color="green", row=2, col=1)

fig.update_layout(height=650, template="plotly_dark", xaxis_rangeslider_visible=False, margin=dict(l=10, r=10, t=10, b=10))
st.plotly_chart(fig, use_container_width=True)
