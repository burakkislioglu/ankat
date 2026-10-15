import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

# Sayfa Ayarları
st.set_page_config(page_title="NETCD Karar ve Emir Motoru", layout="wide")

# --- SOL MENÜ: PORTFÖY VE RİSK AYARLARI ---
st.sidebar.header("💼 Portföy ve Pozisyon Bilgileri")
ticker = st.sidebar.text_input("Hisse Kodu", value="NETCD.IS")
mevcut_adet = st.sidebar.number_input("Mevcut Lot Adedi", min_value=0, value=140, step=1)
ortalama_maliyet = st.sidebar.number_input("Ortalama Maliyet (₺)", min_value=0.0, value=115.70, step=0.05, format="%.2f")
toplam_portfoy = st.sidebar.number_input("Toplam Portföy Büyüklüğü (₺)", min_value=1000.0, value=92897.0, step=500.0)
max_agirlik_limiti = st.sidebar.slider("Maksimum Tek Hisse Ağırlık Limiti (%)", min_value=5.0, max_value=30.0, value=15.0, step=0.5)

st.sidebar.markdown("---")
st.sidebar.header("⚙️ Teknik Motor Ayarları")
periyot = st.sidebar.selectbox("İzleme Periyodu", ["15m", "1h", "1d", "1wk"], index=0)
atr_carpani = st.sidebar.slider("ATR Stop-Loss Çarpanı", min_value=1.0, max_value=3.5, value=2.0, step=0.1)

# --- VERİ ÇEKME VE İNDİKATÖR HESAPLAMA ---
@st.cache_data(ttl=60)
def veri_getir(sembol, interval):
    period_map = {"15m": "5d", "1h": "1mo", "1d": "6mo", "1wk": "2y"}
    df = yf.download(sembol, period=period_map[interval], interval=interval, progress=False)
    if df.empty:
        return df
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    
    # EMA 9 ve EMA 21
    df["EMA9"] = df["Close"].ewm(span=9, adjust=False).mean()
    df["EMA21"] = df["Close"].ewm(span=21, adjust=False).mean()
    
    # RSI (14)
    delta = df["Close"].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df["RSI"] = 100 - (100 / (1 + rs))
    
    # VWAP
    tp = (df["High"] + df["Low"] + df["Close"]) / 3
    df["VWAP"] = (tp * df["Volume"]).cumsum() / df["Volume"].cumsum()
    
    # ATR (14) - Volatilite ve Dinamik Stop İçin
    high_low = df["High"] - df["Low"]
    high_close = np.abs(df["High"] - df["Close"].shift())
    low_close = np.abs(df["Low"] - df["Close"].shift())
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df["ATR"] = tr.rolling(window=14).mean()
    
    return df.dropna()

@st.cache_data(ttl=300)
def ust_zaman_ve_pivot_getir(sembol):
    df_gunluk = yf.download(sembol, period="1mo", interval="1d", progress=False)
    df_haftalik = yf.download(sembol, period="1y", interval="1wk", progress=False)
    if isinstance(df_gunluk.columns, pd.MultiIndex):
        df_gunluk.columns = df_gunluk.columns.get_level_values(0)
    if isinstance(df_haftalik.columns, pd.MultiIndex):
        df_haftalik.columns = df_haftalik.columns.get_level_values(0)
        
    # Önceki Günün Pivot Noktaları
    onceki_gun = df_gunluk.iloc[-2] if len(df_gunluk) >= 2 else df_gunluk.iloc[-1]
    H, L, C = float(onceki_gun["High"]), float(onceki_gun["Low"]), float(onceki_gun["Close"])
    P = (H + L + C) / 3
    S1 = (2 * P) - H
    S2 = P - (H - L)
    R1 = (2 * P) - L
    R2 = P + (H - L)
    
    # Haftalık EMA9 Trend Kontrolü
    df_haftalik["EMA9_W"] = df_haftalik["Close"].ewm(span=9, adjust=False).mean()
    haftalik_pozitif = float(df_haftalik["Close"].iloc[-1]) >= float(df_haftalik["EMA9_W"].iloc[-1])
    
    return {"P": P, "S1": S1, "S2": S2, "R1": R1, "R2": R2, "haftalik_pozitif": haftalik_pozitif}

df = veri_getir(ticker, periyot)
ek_veri = ust_zaman_ve_pivot_getir(ticker)

if df.empty:
    st.error("Veri çekilemedi. Lütfen hisse kodunu veya bağlantıyı kontrol edin.")
    st.stop()

# Anlık Değerler
son_fiyat = float(df["Close"].iloc[-1])
ema9 = float(df["EMA9"].iloc[-1])
ema21 = float(df["EMA21"].iloc[-1])
rsi = float(df["RSI"].iloc[-1])
vwap = float(df["VWAP"].iloc[-1])
atr = float(df["ATR"].iloc[-1])
P, S1, S2, R1, R2 = ek_veri["P"], ek_veri["S1"], ek_veri["S2"], ek_veri["R1"], ek_veri["R2"]

# --- PORTFÖY MATEMATİĞİ ---
pozisyon_degeri = mevcut_adet * son_fiyat
toplam_maliyet = mevcut_adet * ortalama_maliyet
net_kar_zarar = pozisyon_degeri - toplam_maliyet
kar_zarar_yuzde = ((son_fiyat - ortalama_maliyet) / ortalama_maliyet) * 100 if ortalama_maliyet > 0 else 0
mevcut_agirlik = (pozisyon_degeri / toplam_portfoy) * 100
basabas_icin_gereken = ((ortalama_maliyet - son_fiyat) / son_fiyat) * 100 if son_fiyat < ortalama_maliyet else 0

# Risk Limitine Göre Maksimum Ek Alım Bütçesi
hedef_max_tutar = toplam_portfoy * (max_agirlik_limiti / 100)
kullanilabilir_alim_butcesi = max(0.0, hedef_max_tutar - pozisyon_degeri)

# --- KARAR MOTORU VE SKORLAMA (0 - 100 PUAN) ---
skor = 0
sinyal_detaylari = []

# 1. EMA 9/21 Trend Skoru (25 Puan)
if ema9 > ema21 and son_fiyat > ema9:
    skor += 25
    sinyal_detaylari.append("✅ Kısa vadeli trend pozitif (Fiyat > EMA9 > EMA21).")
elif son_fiyat > ema9:
    skor += 15
    sinyal_detaylari.append("🟡 Fiyat EMA9'un üzerine çıktı, EMA21 kırılımı bekleniyor.")
else:
    sinyal_detaylari.append("🔴 Fiyat kısa vadeli ortalamaların (EMA 9/21) altında.")

# 2. VWAP Kurumsal Maliyet Skoru (25 Puan)
if son_fiyat >= vwap:
    skor += 25
    sinyal_detaylari.append(f"✅ Fiyat hacim ağırlıklı ortalamanın (VWAP: ₺{vwap:.2f}) üzerinde.")
else:
    sinyal_detaylari.append(f"🔴 Fiyat VWAP (₺{vwap:.2f}) altında, gün içi satıcılar baskın.")

# 3. RSI Momentum Skoru (25 Puan)
if 30 <= rsi <= 45:
    skor += 25
    sinyal_detaylari.append(f"✅ RSI ({rsi:.1f}) aşırı satım bölgesinden dönüş/tepki alanında.")
elif 45 < rsi <= 65:
    skor += 20
    sinyal_detaylari.append(f"✅ RSI ({rsi:.1f}) sağlıklı güçlenme bölgesinde.")
elif rsi < 30:
    skor += 15
    sinyal_detaylari.append(f"⚠️ RSI ({rsi:.1f}) aşırı satımda; sert düşüş var, dönüş mumu beklenmeli.")
else:
    sinyal_detaylari.append(f"⚠️ RSI ({rsi:.1f}) aşırı alım bölgesinde, kâr satışı gelebilir.")

# 4. Pivot Destek / Risk-Ödül Skoru (25 Puan)
if S1 <= son_fiyat <= P:
    skor += 25
    sinyal_detaylari.append(f"✅ Fiyat S1 Desteği (₺{S1:.2f}) ile Pivot (₺{P:.2f}) arasında, alım için uygun bantta.")
elif son_fiyat > P:
    skor += 20
    sinyal_detaylari.append(f"✅ Fiyat Pivot (₺{P:.2f}) üzerinde, R1 Direnci (₺{R1:.2f}) hedefleniyor.")
else:
    skor += 5
    sinyal_detaylari.append(f"🔴 Fiyat S1 Desteğinin (₺{S1:.2f}) altında, S2 (₺{S2:.2f}) test edilebilir.")

# --- NOKTA ATIŞI TALİMAT ÜRETİCİ ---
onerilen_giris = round(max(S1, son_fiyat - (0.5 * atr)), 2) if son_fiyat > S1 else round(S2, 2)
stop_fiyati = round(onerilen_giris - (atr_carpani * atr), 2)
hedef_1 = round(max(P, onerilen_giris + (1.5 * atr)), 2)
hedef_2 = round(max(R1, onerilen_giris + (3.0 * atr)), 2)

# Önerilen Lot Hesabı (Skora ve Risk Bütçesine Göre)
max_alinabilir_lot = int(kullanilabilir_alim_butcesi // onerilen_giris) if onerilen_giris > 0 else 0

if skor >= 70 and max_alinabilir_lot > 0:
    aksiyon_baslik = "🟢 TALİMAT: KADEMELİ ALIM (MALİYET DÜŞÜRME ONaYLI)"
    onerilen_lot = max_alinabilir_lot
    yeni_toplam_lot = mevcut_adet + onerilen_lot
    yeni_ort_maliyet = ((mevcut_adet * ortalama_maliyet) + (onerilen_lot * onerilen_giris)) / yeni_toplam_lot
    talimat_metni = (
        f"**1. EMİR:** `₺{onerilen_giris:.2f}` seviyesine **{onerilen_lot} Lot Alım Limit Emri** girin.\n\n"
        f"**2. MALİYET ETKİSİ:** Emir gerçekleştiğinde toplam lotunuz **{yeni_toplam_lot} Adet** olacak ve ortalama maliyetiniz **₺{ortalama_maliyet:.2f}** seviyesinden **₺{yeni_ort_maliyet:.2f}** seviyesine düşecektir.\n\n"
        f"**3. KORUMA & HEDEF:** Yeni alım için Kısa Vadeli Stop-Loss: `₺{stop_fiyati:.2f}` | İlk Kâr Al (Tepki) Hedefi: `₺{hedef_1:.2f}` | Ana Direnç: `₺{hedef_2:.2f}`."
    )
elif 45 <= skor < 70 and max_alinabilir_lot > 0:
    aksiyon_baslik = "🟡 TALİMAT: PİYASADAN ALMA — DESTEKTE LİMİT EMİRLE PUSU KUR"
    onerilen_lot = max(1, int(max_alinabilir_lot * 0.5)) # Bütçenin yarısıyla kademeli giriş
    destek_giris = round(S1, 2) if son_fiyat > S1 else round(S2, 2)
    yeni_toplam_lot = mevcut_adet + onerilen_lot
    yeni_ort_maliyet = ((mevcut_adet * ortalama_maliyet) + (onerilen_lot * destek_giris)) / yeni_toplam_lot
    talimat_metni = (
        f"**1. EMİR:** Anlık fiyattan (`₺{son_fiyat:.2f}`) alım yapmayın. Alt destek olan **`₺{destek_giris:.2f}`** seviyesine **{onerilen_lot} Lot Alım Limit Emri** bırakın (Risk bütçenizin %50'si).\n\n"
        f"**2. MALİYET ETKİSİ:** Fiyat desteğe iğne atıp emrinizi alırsa ortalamanız **₺{ortalama_maliyet:.2f}** -> **₺{yeni_ort_maliyet:.2f}** seviyesine çekilecektir.\n\n"
        f"**3. TREND ONAYI:** Eğer destek çalışmaz ve **`₺{stop_fiyati:.2f}`** altında 2 mum kapanışı gelirse ek alım emrini iptal edin."
    )
elif max_alinabilir_lot == 0:
    aksiyon_baslik = "🟠 TALİMAT: ALIM DURDURULDU (PORTFÖY RİSK LİMİTİ DOLU)"
    talimat_metni = (
        f"**1. RİSK UYARISI:** Mevcut pozisyon ağırlığınız (**%{mevcut_agirlik:.2f}**), belirlediğiniz **%{max_agirlik_limiti:.1f}** sınırına ulaştı veya aştı.\n\n"
        f"**2. STRATEJİ:** Yeni nakit bağlamayın. Fiyatın `₺{hedef_1:.2f}` (Pivot) ve `₺{hedef_2:.2f}` (R1) dirençlerine tepki vermesini bekleyin.\n\n"
        f"**3. SAVUNMA HATTI:** Ana pozisyon için kritik destek `₺{S1:.2f}` ve volatilite stop seviyesi `₺{stop_fiyati:.2f}` olarak izlenmelidir."
    )
else:
    aksiyon_baslik = "🔴 TALİMAT: BEKLE / NAKİTTE KAL (SATIŞ BASKISI SÜRÜYOR)"
    talimat_metni = (
        f"**1. EMİR:** Şu an yeni alım emri **GİRMEYİN**. İndikatörler (Skor: {skor}/100) düşüş momentumunun sürdüğünü gösteriyor.\n\n"
        f"**2. TETİK SEVİYESİ:** Sadece fiyat yeniden **VWAP (`₺{vwap:.2f}`)** ve **EMA9 (`₺{ema9:.2f}`)** üzerine yerleşirse alım penceresi açılacaktır.\n\n"
        f"**3. SAVUNMA HATTI:** Gün içi dip ve `₺{S1:.2f}` (S1) desteği kırılırsa `₺{S2:.2f}` (S2) seviyesine kadar geri çekilme riski mevcuttur."
    )

# --- EKRAN ÇIKTISI ---
st.title(f"🎯 {ticker} Nokta Atışı Karar ve Emir Paneli")

# Üst Özet Kartları
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Anlık Fiyat", f"₺{son_fiyat:.2f}", f"Ortalama: ₺{ortalama_maliyet:.2f}")
c2.metric("Pozisyon Değeri", f"₺{pozisyon_degeri:,.2f}", f"{kar_zarar_yuzde:.2f}% (₺{net_kar_zarar:,.0f})")
c3.metric("Portföy Ağırlığı", f"%{mevcut_agirlik:.2f}", f"Limit: %{max_agirlik_limiti:.1f}")
c4.metric("Başabaş İçin Gereken", f"+%{basabas_icin_gereken:.2f}", f"Hedef: ₺{ortalama_maliyet:.2f}")
c5.metric("Teknik Güven Skoru", f"{skor} / 100", "Haftalık: Pozitif" if ek_veri["haftalik_pozitif"] else "Haftalık: Negatif")

st.markdown("---")

# Nokta Atışı Talimat Kutusu
col_sol, col_sag = st.columns([3, 2])
with col_sol:
    st.subheader(aksiyon_baslik)
    st.info(talimat_metni)

with col_sag:
    st.subheader("📋 Teknik Kontrol Listesi")
    for detay in sinyal_detaylari:
        st.write(detay)
    st.caption(f"📐 **Güncel Pivot Seviyeleri:** S2: `₺{S2:.2f}` | S1: `₺{S1:.2f}` | **Pivot: `₺{P:.2f}`** | R1: `₺{R1:.2f}` | R2: `₺{R2:.2f}`")

# Grafik (Fiyat + EMA + VWAP + Maliyet ve Emir Çizgileri)
fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.7, 0.3])
fig.add_trace(go.Candlestick(x=df.index, open=df["Open"], high=df["High"], low=df["Low"], close=df["Close"], name="Fiyat"), row=1, col=1)
fig.add_trace(go.Scatter(x=df.index, y=df["EMA9"], line=dict(color="#00e676", width=1.5), name="EMA 9"), row=1, col=1)
fig.add_trace(go.Scatter(x=df.index, y=df["EMA21"], line=dict(color="#ff9100", width=1.5), name="EMA 21"), row=1, col=1)
fig.add_trace(go.Scatter(x=df.index, y=df["VWAP"], line=dict(color="#2979ff", width=2, dash="dot"), name="VWAP"), row=1, col=1)

# Destek ve Hedef Çizgileri
fig.add_hline(y=S1, line_dash="dash", line_color="green", annotation_text=f"S1 Destek (₺{S1:.2f})", row=1, col=1)
fig.add_hline(y=R1, line_dash="dash", line_color="red", annotation_text=f"R1 Direnç (₺{R1:.2f})", row=1, col=1)

# RSI Alt Grafiği
fig.add_trace(go.Scatter(x=df.index, y=df["RSI"], line=dict(color="#ab47bc", width=1.5), name="RSI (14)"), row=2, col=1)
fig.add_hline(y=30, line_dash="dot", line_color="green", row=2, col=1)
fig.add_hline(y=70, line_dash="dot", line_color="red", row=2, col=1)

fig.update_layout(height=600, template="plotly_dark", xaxis_rangeslider_visible=False, margin=dict(l=20, r=20, t=30, b=20))
st.plotly_chart(fig, use_container_width=True)
