# Crypto Trading Dashboard

Paper trading + backtesting dashboard for crypto using Streamlit and CCXT.

## Features
- Live Paper Trading
- Historical Backtesting
- Strategies: EMA Momentum, RSI Mean Reversion, Breakout
- Risk management (SL, TP, daily loss limit)
- Optional Telegram alerts
- Futures / leverage mode (paper only)

## Run locally
```bash
pip install -r requirements.txt
streamlit run dashboard.py
```

## Deploy to Streamlit Cloud (get public link)
1. Go to https://share.streamlit.io
2. Sign in with GitHub
3. Select this repository
4. Main file: dashboard.py
5. Deploy

**Warning:** Educational tool only. Aggressive crypto trading is high risk. Most retail traders lose money. Not financial advice.
