import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime
import time
import requests

st.set_page_config(page_title="Crypto Trading System", layout="wide", page_icon="🚀")

if "paper" not in st.session_state:
    st.session_state.paper = {
        "balance": 1000.0,
        "positions": {},  # symbol -> {size, entry, side}
        "trades": [],
        "equity_history": [1000.0],
        "daily_pnl": 0.0,
        "total_pnl": 0.0,
    }

# Top liquid pairs (Kraken compatible)
DEFAULT_SYMBOLS = [
    "BTC/USDT", "ETH/USDT", "SOL/USDT", "XRP/USDT", "ADA/USDT",
    "DOGE/USDT", "AVAX/USDT", "LINK/USDT", "DOT/USDT", "MATIC/USDT"
]

st.sidebar.title("🚀 מערכת מסחר קריפטו")
mode = st.sidebar.radio("מצב", ["📊 Live Paper", "🧪 בקטסט היסטורי"])

exchange_id = st.sidebar.selectbox("בורסה", ["kraken", "okx", "bybit"], index=0)
symbols_input = st.sidebar.text_area("מטבעות (אחד בשורה)", "\n".join(DEFAULT_SYMBOLS), height=120)
symbols = [s.strip() for s in symbols_input.split("\n") if s.strip()]
timeframe = st.sidebar.selectbox("טיימפריים", ["5m", "15m", "1h", "4h"], index=1)
max_positions = st.sidebar.slider("מקסימום פוזיציות פתוחות", 1, 5, 2)
leverage = st.sidebar.slider("מינוף (Paper)", 1, 10, 1)
futures_mode = st.sidebar.checkbox("Futures (Paper)", False)

strategy = st.sidebar.selectbox("אסטרטגיה", ["מומנטום EMA", "RSI Mean Reversion", "Breakout"])

risk_pct = st.sidebar.slider("סיכון למסחר %", 0.5, 3.0, 1.0) / 100
sl_pct = st.sidebar.slider("סטופ לוס %", 0.5, 5.0, 2.0) / 100
tp_pct = st.sidebar.slider("טייק פרופיט %", 1.0, 10.0, 4.0) / 100
max_daily_loss = st.sidebar.slider("הפסד יומי מקסימלי %", 2.0, 10.0, 5.0) / 100

telegram_token = st.sidebar.text_input("Telegram Bot Token", type="password")
telegram_chat = st.sidebar.text_input("Telegram Chat ID")
send_telegram = st.sidebar.checkbox("שלח התראות Telegram", False)

auto_refresh = st.sidebar.checkbox("רענון אוטומטי", False)
if st.sidebar.button("🔄 רענן"):
    st.rerun()
if st.sidebar.button("🗑️ אפס חשבון"):
    st.session_state.paper = {
        "balance": 1000.0, "positions": {}, "trades": [],
        "equity_history": [1000.0], "daily_pnl": 0.0, "total_pnl": 0.0,
    }
    st.rerun()

def send_telegram_message(text):
    if not send_telegram or not telegram_token or not telegram_chat:
        return
    try:
        requests.post(f"https://api.telegram.org/bot{telegram_token}/sendMessage",
                      json={"chat_id": telegram_chat, "text": text}, timeout=5)
    except Exception:
        pass

@st.cache_data(ttl=30)
def fetch_ohlcv(exchange_id, symbol, timeframe, limit=200):
    try:
        ex = getattr(ccxt, exchange_id)({"enableRateLimit": True})
        ohlcv = ex.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
    except Exception:
        return pd.DataFrame()

def add_indicators(df):
    if df.empty or len(df) < 30:
        return df
    df = df.copy()
    df["ema9"] = df["close"].ewm(span=9, adjust=False).mean()
    df["ema21"] = df["close"].ewm(span=21, adjust=False).mean()
    delta = df["close"].diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))
    df["volume_sma"] = df["volume"].rolling(20).mean()
    return df

def get_signal(df, strategy_name):
    if len(df) < 60:
        return "HOLD"
    last = df.iloc[-1]
    prev = df.iloc[-2]
    if strategy_name == "מומנטום EMA":
        bull = prev["ema9"] <= prev["ema21"] and last["ema9"] > last["ema21"]
        bear = prev["ema9"] >= prev["ema21"] and last["ema9"] < last["ema21"]
        vol = last["volume"] > (last.get("volume_sma") or 0) * 1.1
        if bull and vol: return "BUY"
        if bear and vol: return "SELL"
    elif strategy_name == "RSI Mean Reversion":
        if last["rsi"] < 30: return "BUY"
        if last["rsi"] > 70: return "SELL"
    elif strategy_name == "Breakout":
        high_20 = df["high"].rolling(20).max().iloc[-2]
        low_20 = df["low"].rolling(20).min().iloc[-2]
        if last["close"] > high_20 and last["volume"] > last.get("volume_sma", 0) * 1.3:
            return "BUY"
        if last["close"] < low_20 and last["volume"] > last.get("volume_sma", 0) * 1.3:
            return "SELL"
    return "HOLD"

st.title("🚀 מערכת מסחר קריפטו - רב מטבעות")
st.caption("Paper Trading | לא ייעוץ פיננסי")

if mode == "📊 Live Paper":
    paper = st.session_state.paper
    signals = {}
    prices = {}

    # Scan all symbols
    for sym in symbols[:8]:  # limit to avoid rate limits
        df = fetch_ohlcv(exchange_id, sym, timeframe)
        if df.empty:
            continue
        df = add_indicators(df)
        if len(df) < 60:
            continue
        prices[sym] = float(df["close"].iloc[-1])
        signals[sym] = get_signal(df, strategy)

    # Manage existing positions
    for sym, pos in list(paper["positions"].items()):
        price = prices.get(sym)
        if not price:
            continue
        entry = pos["entry"]
        side = pos["side"]
        size = pos["size"]
        if side == "long":
            if price <= entry * (1 - sl_pct) or price >= entry * (1 + tp_pct):
                reason = "SL" if price <= entry * (1 - sl_pct) else "TP"
                pnl = (price - entry) * size * leverage
                paper["balance"] += size * entry / leverage + pnl
                paper["total_pnl"] += pnl
                paper["daily_pnl"] += pnl
                paper["trades"].append({
                    "זמן": datetime.now().strftime("%H:%M:%S"),
                    "מטבע": sym, "פעולה": f"סגירה {reason}",
                    "מחיר": round(price, 4), "PnL": round(pnl, 2)
                })
                send_telegram_message(f"סגירה {sym} {reason} PnL:{pnl:.2f}")
                del paper["positions"][sym]

    # Open new positions
    if len(paper["positions"]) < max_positions and paper["daily_pnl"] > -paper["balance"] * max_daily_loss:
        for sym, sig in signals.items():
            if len(paper["positions"]) >= max_positions:
                break
            if sym in paper["positions"]:
                continue
            price = prices.get(sym)
            if not price:
                continue
            if sig == "BUY":
                size = (paper["balance"] * risk_pct) / (price * sl_pct) * leverage
                if size > 0:
                    cost = size * price / leverage
                    if cost < paper["balance"] * 0.9:
                        paper["balance"] -= cost
                        paper["positions"][sym] = {"size": size, "entry": price, "side": "long"}
                        paper["trades"].append({
                            "זמן": datetime.now().strftime("%H:%M:%S"),
                            "מטבע": sym, "פעולה": "פתיחת LONG",
                            "מחיר": round(price, 4), "PnL": 0
                        })
                        send_telegram_message(f"פתיחת LONG {sym} @ {price:.2f}")

    # Equity
    unrealized = 0
    for sym, pos in paper["positions"].items():
        price = prices.get(sym, pos["entry"])
        unrealized += (price - pos["entry"]) * pos["size"] * leverage
    current_equity = paper["balance"] + unrealized
    paper["equity_history"].append(current_equity)
    if len(paper["equity_history"]) > 200:
        paper["equity_history"] = paper["equity_history"][-200:]

    # Metrics
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("יתרה", f"${paper['balance']:,.2f}")
    c2.metric("Equity", f"${current_equity:,.2f}", delta=f"{current_equity-1000:.1f}")
    c3.metric("פוזיציות פתוחות", len(paper["positions"]))
    c4.metric("סה\"כ עסקאות", len(paper["trades"]))

    # Signals table
    st.subheader("סיגנלים נוכחיים")
    if signals:
        sig_df = pd.DataFrame([
            {"מטבע": s, "מחיר": f"${prices.get(s,0):,.2f}", "סיגנל": signals[s]}
            for s in signals
        ])
        st.dataframe(sig_df, use_container_width=True, hide_index=True)
    else:
        st.info("לא נמצאו נתונים. נסה שוב בעוד כמה שניות.")

    # Open positions
    if paper["positions"]:
        st.subheader("פוזיציות פתוחות")
        pos_rows = []
        for sym, pos in paper["positions"].items():
            price = prices.get(sym, pos["entry"])
            pnl = (price - pos["entry"]) * pos["size"] * leverage
            pos_rows.append({
                "מטבע": sym, "צד": pos["side"].upper(),
                "כניסה": round(pos["entry"], 4),
                "נוכחי": round(price, 4),
                "PnL": round(pnl, 2)
            })
        st.dataframe(pd.DataFrame(pos_rows), use_container_width=True, hide_index=True)

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("עקומת Equity")
        st.line_chart(pd.Series(paper["equity_history"]))
    with col_b:
        st.subheader("עסקאות אחרונות")
        if paper["trades"]:
            st.dataframe(pd.DataFrame(paper["trades"][::-1]).head(15), use_container_width=True, hide_index=True)
        else:
            st.info("מחכה לסיגנלים...")

    if auto_refresh:
        time.sleep(40)
        st.rerun()

else:
    st.info("בקטסט רב מטבעות יוסף בגרסה הבאה. כרגע השתמש במצב Live Paper.")

st.sidebar.caption("סורק כמה מטבעות במקביל. Paper בלבד.")
