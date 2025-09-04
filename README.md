# trading-agent
# Trading Agent (Multi-Timeframe, Wilder-Regeln)

- D1/H4/H1 Regime-Filter (ADX/DMI, EMA, RSI)
- Entry/Exit auf M15 mit ATR-SL/TP
- Chart (PNG) + optional E-Mail Report
- Läuft lokal & in GitHub Actions (*/15)

## Setup
```bash
pip install -r requirements.txt
cp .env.example .env  # Werte setzen
pip install python-dotenv
python agent.py --email
