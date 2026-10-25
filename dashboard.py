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
        "balance": 1000.0, "position": 0.0, "entry_price": 0.0,
        "side": None, "trades": [], "equity_history": [1000.0],
        "daily_pnl": 0.0, "total_pnl": 0.0,
    }

st.sidebar.title("🚀 מערכת מסחר קריפטו")
mode = st.sidebar.radio("מצב", ["📊 Live Paper", "🧪 בקטסט היסטורי"])

exchange_id = st.sidebar.selectbox("בורסה", ["bybit", "okx", "binance"], index=0)
symbol = st.sidebar.text_input("זוג", "BTC/USDT")
timeframe = st.sidebar.selectbox("טיימפריים", ["1m", "5m", "15m", "1h", "4h"], index=2)
leverage = st.sidebar.slider("מינוף (Paper)", 1, 20, 1)
futures_mode = st.sidebar.checkbox("Futures (Paper)", False)

strategy = st.sidebar.selectbox("אסטרטגיה", ["מומנטום EMA", "RSI Mean Reversion", "Breakout"])

risk_pct = st.sidebar.slider("סיכון למסחר %", 0.5, 5.0, 1.0) / 100
sl_pct = st.sidebar.slider("סטופ לוס %", 0.5, 5.0, 2.0) / 100
tp_pct = st.sidebar.slider("טייק פרופיט %", 1.0, 15.0, 6.0) / 100
max_daily_loss = st.sidebar.slider("הפסד יומי מקסימלי %", 2.0, 15.0, 5.0) / 100

telegram_token = st.sidebar.text_input("Telegram Bot Token", type="password")
telegram_chat = st.sidebar.text_input("Telegram Chat ID")
send_telegram = st.sidebar.checkbox("שלח התראות Telegram", False)

auto_refresh = st.sidebar.checkbox("רענון אוטומטי", False)
if st.sidebar.button("🔄 רענן"):
    st.rerun()
if st.sidebar.button("🗑️ אפס חשבון"):
    st.session_state.paper = {
        "balance": 1000.0, "position": 0.0, "entry_price": 0.0,
        "side": None, "trades": [], "equity_history": [1000.0],
        "daily_pnl": 0.0, "total_pnl": 0.0,
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

@st.cache_data(ttl=20)
def fetch_ohlcv(exchange_id, symbol, timeframe, limit=300):
    try:
        ex = getattr(ccxt, exchange_id)({"enableRateLimit": True})
        ohlcv = ex.fetch_ohlcv(symbol, timeframe, limit=limit)
        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        return df
    except Exception as e:
        st.error(f"שגיאה בטעינת נתונים: {e}")
        return pd.DataFrame()

def add_indicators(df):
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
        vol = last["volume"] > (last["volume_sma"] or 0) * 1.1
        if bull and vol: return "BUY"
        if bear and vol: return "SELL"
    elif strategy_name == "RSI Mean Reversion":
        if last["rsi"] < 30: return "BUY"
        if last["rsi"] > 70: return "SELL"
    elif strategy_name == "Breakout":
        high_20 = df["high"].rolling(20).max().iloc[-2]
        low_20 = df["low"].rolling(20).min().iloc[-2]
        if last["close"] > high_20 and last["volume"] > last["volume_sma"] * 1.3:
            return "BUY"
        if last["close"] < low_20 and last["volume"] > last["volume_sma"] * 1.3:
            return "SELL"
    return "HOLD"

st.title("🚀 מערכת מסחר קריפטו אגרסיבית")
st.caption("Paper Trading + בקטסט | לא ייעוץ פיננסי")

df = fetch_ohlcv(exchange_id, symbol, timeframe)
if df.empty:
    st.stop()

df = add_indicators(df)
current_price = float(df["close"].iloc[-1])
signal = get_signal(df, strategy)

if mode == "📊 Live Paper":
    paper = st.session_state.paper

    def open_position(side, size, price):
        if paper["position"] != 0:
            return
        paper["position"] = size if side == "long" else -size
        paper["side"] = side
        paper["entry_price"] = price
        cost = abs(size) * price / leverage
        paper["balance"] -= cost
        paper["trades"].append({
            "זמן": datetime.now().strftime("%H:%M:%S"),
            "פעולה": f"פתיחת {side.upper()}",
            "מחיר": round(price, 2),
            "כמות": round(abs(size), 6),
            "PnL": 0
        })
        send_telegram_message(f"פתיחת {side.upper()} {symbol} @ {price:.2f}")

    def close_position(price, reason):
        if paper["position"] == 0:
            return
        direction = 1 if paper["side"] == "long" else -1
        pnl = (price - paper["entry_price"]) * abs(paper["position"]) * direction * leverage
        paper["balance"] += abs(paper["position"]) * paper["entry_price"] / leverage + pnl
        paper["total_pnl"] += pnl
        paper["daily_pnl"] += pnl
        paper["trades"].append({
            "זמן": datetime.now().strftime("%H:%M:%S"),
            "פעולה": f"סגירה ({reason})",
            "מחיר": round(price, 2),
            "כמות": round(abs(paper["position"]), 6),
            "PnL": round(pnl, 2)
        })
        send_telegram_message(f"סגירה {reason} | PnL: {pnl:.2f}")
        paper["position"] = 0
        paper["side"] = None
        paper["entry_price"] = 0

    if paper["daily_pnl"] < -paper["balance"] * max_daily_loss:
        st.warning("הגעת להפסד יומי מקסימלי")
    else:
        if paper["position"] != 0:
            if paper["side"] == "long":
                if current_price <= paper["entry_price"] * (1 - sl_pct):
                    close_position(current_price, "סטופ לוס")
                elif current_price >= paper["entry_price"] * (1 + tp_pct):
                    close_position(current_price, "טייק פרופיט")
            else:
                if current_price >= paper["entry_price"] * (1 + sl_pct):
                    close_position(current_price, "סטופ לוס")
                elif current_price <= paper["entry_price"] * (1 - tp_pct):
                    close_position(current_price, "טייק פרופיט")

        if signal == "BUY" and paper["position"] == 0:
            size = (paper["balance"] * risk_pct) / (current_price * sl_pct) * leverage
            if size > 0:
                open_position("long", size, current_price)
        elif signal == "SELL" and paper["position"] == 0 and futures_mode:
            size = (paper["balance"] * risk_pct) / (current_price * sl_pct) * leverage
            if size > 0:
                open_position("short", size, current_price)
        elif signal == "SELL" and paper.get("side") == "long":
            close_position(current_price, "סיגנל")
        elif signal == "BUY" and paper.get("side") == "short":
            close_position(current_price, "סיגנל")

    unrealized = 0
    if paper["position"] != 0:
        direction = 1 if paper["side"] == "long" else -1
        unrealized = (current_price - paper["entry_price"]) * abs(paper["position"]) * direction * leverage
    current_equity = paper["balance"] + unrealized
    paper["equity_history"].append(current_equity)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("מחיר", f"${current_price:,.2f}")
    c2.metric("סיגנל", signal)
    c3.metric("יתרה", f"${paper['balance']:,.2f}")
    c4.metric("Equity", f"${current_equity:,.2f}", delta=f"{current_equity-1000:.1f}")
    pos = "אין" if paper["position"] == 0 else f"{paper['side'].upper()} {abs(paper['position']):.5f}"
    c5.metric("פוזיציה", pos)

    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.05, row_heights=[0.75, 0.25])
    fig.add_trace(go.Candlestick(x=df["timestamp"], open=df["open"], high=df["high"], low=df["low"], close=df["close"], name="מחיר"), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["timestamp"], y=df["ema9"], name="EMA9", line=dict(color="#ff9800")), row=1, col=1)
    fig.add_trace(go.Scatter(x=df["timestamp"], y=df["ema21"], name="EMA21", line=dict(color="#2196f3")), row=1, col=1)
    if paper["entry_price"] > 0:
        fig.add_hline(y=paper["entry_price"], line_dash="dot", line_color="lime")
    fig.add_trace(go.Bar(x=df["timestamp"], y=df["volume"], name="נפח", marker_color="#64b5f6"), row=2, col=1)
    fig.update_layout(height=650, template="plotly_dark", xaxis_rangeslider_visible=False)
    st.plotly_chart(fig, use_container_width=True)

    col_a, col_b = st.columns(2)
    with col_a:
        st.subheader("עקומת Equity")
        st.line_chart(pd.Series(paper["equity_history"]))
    with col_b:
        st.subheader("עסקאות")
        if paper["trades"]:
            st.dataframe(pd.DataFrame(paper["trades"][::-1]), use_container_width=True, height=350)
        else:
            st.info("מחכה לסיגנל...")

    if auto_refresh:
        time.sleep(30)
        st.rerun()

else:
    st.subheader("🧪 בקטסט היסטורי")
    lookback = st.slider("מספר נרות", 100, 1000, 400)
    bt_df = fetch_ohlcv(exchange_id, symbol, timeframe, limit=lookback)
    if not bt_df.empty:
        bt_df = add_indicators(bt_df)
        balance = 1000.0
        position = 0.0
        entry = 0.0
        side = None
        equity = [1000.0]
        trades = []
        for i in range(60, len(bt_df)):
            price = bt_df.iloc[i]["close"]
            sig = get_signal(bt_df.iloc[:i+1], strategy)
            if position != 0:
                if side == "long":
                    if price <= entry*(1-sl_pct) or price >= entry*(1+tp_pct) or sig == "SELL":
                        pnl = (price - entry) * abs(position) * leverage
                        balance += abs(position)*entry/leverage + pnl
                        trades.append({"PnL": round(pnl,2)})
                        position = 0
                else:
                    if price >= entry*(1+sl_pct) or price <= entry*(1-tp_pct) or sig == "BUY":
                        pnl = (entry - price) * abs(position) * leverage
                        balance += abs(position)*entry/leverage + pnl
                        trades.append({"PnL": round(pnl,2)})
                        position = 0
            if position == 0 and sig == "BUY":
                size = (balance * risk_pct) / (price * sl_pct) * leverage
                if size > 0:
                    position = size
                    entry = price
                    side = "long"
                    balance -= size * price / leverage
            elif position == 0 and sig == "SELL" and futures_mode:
                size = (balance * risk_pct) / (price * sl_pct) * leverage
                if size > 0:
                    position = -size
                    entry = price
                    side = "short"
                    balance -= size * price / leverage
            unreal = 0
            if position != 0:
                direction = 1 if side == "long" else -1
                unreal = (price - entry) * abs(position) * direction * leverage
            equity.append(balance + unreal)

        final_eq = equity[-1]
        total_return = (final_eq / 1000 - 1) * 100
        wins = len([t for t in trades if t["PnL"] > 0])
        winrate = (wins / len(trades) * 100) if trades else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("תשואה", f"{total_return:.1f}%")
        c2.metric("Equity", f"${final_eq:,.0f}")
        c3.metric("עסקאות", len(trades))
        c4.metric("Win Rate", f"{winrate:.1f}%")
        st.line_chart(pd.Series(equity))
        if trades:
            st.dataframe(pd.DataFrame(trades))

st.sidebar.caption("כלי חינוכי בלבד. מסחר אגרסיבי מסוכן מאוד.")
