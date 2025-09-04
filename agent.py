#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
KI Trading-Agent (Multi-Timeframe) – EUR/USD (Standard)
- Datenquelle: yfinance (ohne Key). Optional: OANDA v20 (per ENV).
- Indikatoren: EMA(50/200), RSI(14), ADX/DMI(14), ATR(14), PSAR.
- Regime-Logik: D1+H4+H1 -> Bias; Entry/Exit auf M15.
- Output: Text-Report + M15-Chart (PNG); Versand per E-Mail.
- Takt: per cron / GitHub Actions alle 15 Minuten.

Benötigte ENV (siehe .env.example unten):
  EMAIL_TO, SMTP_USER, SMTP_PASS
  OPTIONAL: OANDA_ACCESS_TOKEN, OANDA_ACCOUNT_ID, OANDA_ENV=practice/live

Start:
  pip install -r requirements.txt
  python agent.py --symbols EURUSD=X --tz Europe/Berlin
"""

import os, sys, io, math, smtplib, ssl, traceback, textwrap, time
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.application import MIMEApplication
from zoneinfo import ZoneInfo

import pandas as pd
import numpy as np

# Daten: standard yfinance; optional oanda
import yfinance as yf

# TA & Charts
import pandas_ta as ta
import mplfinance as mpf
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt


# -----------------------
# Konfiguration & Utils
# -----------------------
DEF_SYMBOLS = ["EURUSD=X"]
OUT_DIR     = os.environ.get("OUT_DIR", "out")
os.makedirs(OUT_DIR, exist_ok=True)

TZ_DEFAULT  = os.environ.get("TZ", "Europe/Berlin")

EMAIL_TO    = os.environ.get("EMAIL_TO", "").strip()
SMTP_USER   = os.environ.get("SMTP_USER", "").strip()
SMTP_PASS   = os.environ.get("SMTP_PASS", "").strip()
SMTP_HOST   = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT   = int(os.environ.get("SMTP_PORT", "587"))

USE_OANDA   = bool(os.environ.get("OANDA_ACCESS_TOKEN"))

def now_tz(tz: str) -> datetime:
    return datetime.now(ZoneInfo(tz))

def pct(a, b):
    try:
        return (a/b - 1.0) * 100.0
    except Exception:
        return np.nan


# -----------------------
# Datenbeschaffung
# -----------------------
def load_yf(symbol: str, interval: str, period: str) -> pd.DataFrame:
    """
    interval: '15m','60m','1d' etc. period: '60d','6mo'
    """
    df = yf.download(symbol, interval=interval, period=period, auto_adjust=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        # yfinance kann Multi-Index liefern (Adj Close etc.) -> flatten
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns=str.title)  # Open, High, Low, Close, Volume
    return df.dropna()

def resample_ohlc(df_15m: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum"
    }
    out = df_15m.resample(rule, label="right", closed="right").agg(agg).dropna()
    return out


# -----------------------
# Indikatoren
# -----------------------
def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["EMA50"]  = ta.ema(df["Close"], length=50)
    df["EMA200"] = ta.ema(df["Close"], length=200)
    adx = ta.adx(df["High"], df["Low"], df["Close"], length=14)
    df["ADX"]  = adx["ADX_14"]
    df["+DI"]  = adx["DMP_14"]  # +DI
    df["-DI"]  = adx["DMN_14"]  # -DI
    df["RSI"]  = ta.rsi(df["Close"], length=14)
    atr        = ta.atr(df["High"], df["Low"], df["Close"], length=14)
    df["ATR"]  = atr
    psar       = ta.psar(df["High"], df["Low"], df["Close"], af=0.02, max_af=0.2)
    # Kombinierter PSAR: Long- und Short-Reihen zusammenführen
    psar_col = [c for c in psar.columns if c.startswith("PSAR")]
    df["PSAR"] = psar[psar_col[0]]
    for c in psar_col[1:]:
        df["PSAR"] = df["PSAR"].fillna(psar[c])
    return df

def ema_slope(series: pd.Series, lookback: int = 5) -> float:
    """Steigung in % pro Bar über 'lookback' Bars"""
    if len(series) < lookback + 1:
        return np.nan
    a, b = series.iloc[-1], series.iloc[-(lookback+1)]
    return pct(a, b) / lookback


# -----------------------
# Regime- & Signal-Logik
# -----------------------

def entry_exit_on_m15(m15: pd.DataFrame, bias: str) -> dict:
    """
    Regeln:
      LONG: Close>EMA50, RSI>50 (Kreuz), Pullback <= 0.25*ATR -> Entry @ Close
      SHORT: Close<EMA50, RSI<50 (Kreuz), Pullback <= 0.25*ATR -> Entry @ Close
      SL = 1.5*ATR, TP = 2*ATR, Early exit: PSAR-Flip / RSI50-Gegenkreuz (als Hinweis)
    """
    out = {"action": "WAIT", "note": "Kein Setup", "entry": None, "sl": None, "tp": None}
    if len(m15) < 20:
        out["note"] = "Zu wenige Bars"
        return out

    close = m15["Close"].iloc[-1]
    ema50 = m15["EMA50"].iloc[-1]
    rsi   = m15["RSI"].iloc[-1]
    atr   = m15["ATR"].iloc[-1]
    psar  = m15["PSAR"].iloc[-1]

    prev_rsi = m15["RSI"].iloc[-2]
    prev_close = m15["Close"].iloc[-2]

    # Pullback-Kriterium: Distanz zur EMA50 <= 0.25*ATR
    pullback_ok = abs(close - ema50) <= 0.25 * atr

    if bias == "UP":
        crossed_up = (prev_rsi <= 50) and (rsi > 50)
        if (close > ema50) and crossed_up and pullback_ok:
            entry = round(float(close), 5)
            sl    = round(float(entry - 1.5*atr), 5)
            tp    = round(float(entry + 2.0*atr), 5)
            out.update({"action":"BUY","note":"UP-Bias Entry (RSI>50, Pullback, >EMA50)","entry":entry,"sl":sl,"tp":tp})
            # Frühwarnhinweis
            if psar > close:
                out["note"] += " | Achtung: PSAR über Preis (möglicher Flip)."
            return out

    if bias == "DOWN":
        crossed_dn = (prev_rsi >= 50) and (rsi < 50)
        if (close < ema50) and crossed_dn and pullback_ok:
            entry = round(float(close), 5)
            sl    = round(float(entry + 1.5*atr), 5)
            tp    = round(float(entry - 2.0*atr), 5)
            out.update({"action":"SELL","note":"DOWN-Bias Entry (RSI<50, Pullback, <EMA50)","entry":entry,"sl":sl,"tp":tp})
            if psar < close:
                out["note"] += " | Achtung: PSAR unter Preis (möglicher Flip)."
            return out

    return out

# -----------------------
# Charting
# -----------------------
def plot_m15(m15: pd.DataFrame, symbol: str, tz: str) -> str:
    df = m15.copy()
    df = df.tz_localize(None)  # mpf mag naive Indexe

    apds = [
        mpf.make_addplot(df["EMA50"], width=1),
        mpf.make_addplot(df["EMA200"], width=1),
    ]
    # PSAR als Punkte
    apds.append(mpf.make_addplot(df["PSAR"], type='scatter', markersize=10))

    title = f"{symbol} M15 – {df.index[-1].strftime('%Y-%m-%d %H:%M')} ({tz})"
    save_path = os.path.join(OUT_DIR, f"{symbol.replace('=','_')}_M15.png")

    mpf.plot(
        df.tail(400),
        type='candle',
        style='yahoo',
        title=title,
        addplot=apds,
        volume=True,
        tight_layout=True,
        savefig=save_path
    )
    return save_path


# -----------------------
# E-Mail Versand
# -----------------------
def send_email(subject: str, html: str, attachments: list[str] | None = None):
    if not (EMAIL_TO and SMTP_USER and SMTP_PASS):
        print("Email nicht konfiguriert – Überspringe Versand.")
        return
    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"]   = EMAIL_TO
    msg["Subject"] = subject
    msg.attach(MIMEText(html, "html"))

    for path in attachments or []:
        with open(path, "rb") as f:
            part = MIMEApplication(f.read(), Name=os.path.basename(path))
        part["Content-Disposition"] = f'attachment; filename="{os.path.basename(path)}"'
        msg.attach(part)

    ctx = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls(context=ctx)
        server.login(SMTP_USER, SMTP_PASS)
        server.send_message(msg)
    print("E-Mail gesendet an", EMAIL_TO)


# -----------------------
# Pipeline pro Symbol
# -----------------------
def analyze_symbol(symbol: str, tz: str) -> dict:
    # 15m für 60d -> resample zu H1/H4
    df15 = load_yf(symbol, interval="15m", period="60d")
    df15 = add_indicators(df15)

    h1 = add_indicators(resample_ohlc(df15, "1H"))
    h4 = add_indicators(resample_ohlc(df15, "4H"))

    # D1 separat
    d1 = load_yf(symbol, interval="1d", period="6mo")
    d1 = add_indicators(d1)

    regime = regime_signal(d1, h4, h1)
    trade  = entry_exit_on_m15(df15, regime["bias"])
    chart  = plot_m15(df15, symbol, tz)

    last_close = df15["Close"].iloc[-1]
    last_time  = df15.index[-1].astimezone(ZoneInfo(tz))

    report_html = f"""
    <h2>{symbol} – Multi-Timeframe Analyse</h2>
    <p><b>Zeit</b>: {last_time.strftime('%Y-%m-%d %H:%M:%S %Z')}</p>
    <p><b>Regime</b>: {regime['bias']}<br>
       <i>Begründung</i>: {'; '.join(regime['reasons'])}</p>
    <p><b>Letzter Preis (M15)</b>: {last_close:.5f}</p>
    <h3>Handelsvorschlag (M15)</h3>
    <ul>
      <li><b>Aktion</b>: {trade['action']}</li>
      <li><b>Entry</b>: {trade['entry'] if trade['entry'] else '-'}</li>
      <li><b>SL</b>: {trade['sl'] if trade['sl'] else '-'}</li>
      <li><b>TP</b>: {trade['tp'] if trade['tp'] else '-'}</li>
      <li><b>Hinweis</b>: {trade['note']}</li>
    </ul>
    <p><small>SL/TP ATR-basiert (ATR14, M15). Früher Exit bei PSAR-Flip oder RSI-50 Gegensignal.</small></p>
    """

    return {
        "symbol": symbol,
        "bias": regime["bias"],
        "trade": trade,
        "chart_path": chart,
        "html": report_html
    }


# -----------------------
# CLI / Main
# -----------------------
import argparse
def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--symbols", type=str, default=",".join(DEF_SYMBOLS),
                   help="Kommagetrennt, z.B. EURUSD=X,GBPUSD=X,USDJPY=X")
    p.add_argument("--tz", type=str, default=TZ_DEFAULT)
    p.add_argument("--email", action="store_true", help="Bericht per E-Mail senden")
    return p.parse_args()

def main():
    args = parse_args()
    tz = args.tz
    syms = [s.strip() for s in args.symbols.split(",") if s.strip()]

    all_html = []
    attachments = []

    for s in syms:
        try:
            res = analyze_symbol(s, tz)
            all_html.append(res["html"])
            attachments.append(res["chart_path"])
        except Exception as e:
            tb = traceback.format_exc()
            all_html.append(f"<h2>{s}</h2><pre>{tb}</pre>")

    subject = f"KI Marktanalyse ({', '.join(syms)}) – {now_tz(tz).strftime('%Y-%m-%d %H:%M')}"
    body = "<hr>".join(all_html)

    if args.email:
        send_email(subject, body, attachments)
    else:
        # Lokale Ausgabe
        print(subject)
        print("="*80)
        print(textwrap.fill(body, 120))
        print("\nCharts gespeichert unter:", attachments)

if __name__ == "__main__":
    main()
