#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations
import argparse, os, sys, textwrap, traceback
from datetime import datetime, timezone
from typing import List, Tuple

import pandas as pd
import yfinance as yf

# --- lokale utils
from utils.emailer import send_email

# =========================
# Helpers
# =========================
def is_weekend_utc() -> bool:
    # 5=Sa, 6=So
    return datetime.now(timezone.utc).weekday() >= 5

def ts_now(tz_name: str) -> str:
    try:
        from zoneinfo import ZoneInfo  # py3.9+
        tz = ZoneInfo(tz_name)
        return datetime.now(tz).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

def dl_history(symbol: str, interval: str, lookback_days: int = 10) -> pd.DataFrame:
    try:
        # yfinance begrenzt Intraday oft am WE → wir holen etwas Puffer
        df = yf.download(
            symbol, period=f"{max(lookback_days, 2)}d",
            interval=interval, progress=False, auto_adjust=True
        )
        if isinstance(df, pd.DataFrame) and not df.empty:
            df = df.rename(columns=str.title)  # Open/High/Low/Close/Volume
        return df
    except Exception:
        return pd.DataFrame()

def health_block(rows: List[str]) -> str:
    lis = "\n".join(f"<li>{row}</li>" for row in rows)
    return f"<h3>Health</h3><ul>{lis}</ul>"

def neutral_note(msg: str) -> str:
    return f"<p><b>Hinweis:</b> {msg}</p>"

# =========================
# Regime/Signal (Minimal)
# =========================
def regime_signal(df15: pd.DataFrame, df1d: pd.DataFrame) -> Tuple[str, List[str]]:
    """
    Sehr schlanke 'Wilder-like' Skizze:
    - EMA Trendfilter (H1/D1 approximiert über Close)
    - RSI-Check (Daily)
    """
    notes: List[str] = []
    bias = "NEUTRAL"

    try:
        # Daily RSI (14)
        if not df1d.empty and "Close" in df1d:
            rsi_period = 14
            chg = df1d["Close"].diff()
            up = chg.clip(lower=0).rolling(rsi_period).mean()
            dn = (-chg.clip(upper=0)).rolling(rsi_period).mean()
            rsi = 100 - 100 / (1 + (up / dn).replace(0, pd.NA))
            rsi_last = float(rsi.iloc[-1])
            notes.append(f"RSI(14,D1)={rsi_last:.1f}")
            if rsi_last > 55:
                bias = "UP"
            elif rsi_last < 45:
                bias = "DOWN"

        # Intraday EMA addiert Vertrauen, wenn vorhanden
        if not df15.empty and "Close" in df15:
            ema = df15["Close"].ewm(span=50, adjust=False).mean()
            if ema.iloc[-1] > df15["Close"].iloc[-1]:
                notes.append("M15 EMA50 über Preis → leicht bearish")
                if bias == "UP": bias = "NEUTRAL"
            else:
                notes.append("M15 EMA50 unter Preis → leicht bullish")
                if bias == "DOWN": bias = "NEUTRAL"
    except Exception as e:
        notes.append(f"Regime-Berechnung: {type(e).__name__}")

    return bias, notes

# =========================
# Chart (optional)
# =========================
def save_chart(df: pd.DataFrame, symbol: str, out_dir: str, tz_name: str) -> str | None:
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        if df.empty: 
            return None

        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{symbol.replace('=','_')}_M15.png")

        plt.figure(figsize=(10, 4))
        plt.plot(df.index, df["Close"], label="Close")
        plt.title(f"{symbol} – M15 Close ({ts_now(tz_name)})")
        plt.legend(); plt.tight_layout()
        plt.savefig(path); plt.close()
        return path
    except Exception:
        return None

# =========================
# Mail Body
# =========================
def build_mail(subject_sym: str, tz_name: str,
               bias: str, reasons: List[str],
               notes: List[str], charts: List[str]) -> Tuple[str, str, list]:
    title = f"KI Marktanalyse ({subject_sym}) – {ts_now(tz_name)}"
    body = [f"<h2>{subject_sym}</h2>",
            f"<p><b>Regime:</b> {bias}</p>",
            "<h3>Begründung</h3>",
            "<ul>" + "".join(f"<li>{r}</li>" for r in reasons) + "</ul>"]
    if notes:
        body.append(health_block(notes))
    if not charts:
        body.append(neutral_note("Keine Charts angehängt (keine/zu wenige Intraday-Daten)."))
    html = "\n".join(body)
    return title, html, charts

# =========================
# Main
# =========================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=str, default="EURUSD=X")
    ap.add_argument("--tz", type=str, default=os.getenv("TZ", "Europe/Berlin"))
    ap.add_argument("--email", action="store_true")
    args = ap.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    tz_name = args.tz

    # Wochenend-Strategie
    weekend = is_weekend_utc()
    weekend_note = ""
    intraday_interval = "15m"
    if weekend:
        # Variante: Intraday → Daily-Fallback, bleibt beim gleichen Symbol
        weekend_note = "Wochenende erkannt → Intraday neutralisiert, Daily genutzt."
        intraday_interval = None  # kein M15 am Wochenende

        # Alternativ (auskommentieren, falls lieber BTC für Funktionstest):
        # if symbols == ["EURUSD=X"]:
        #     symbols = ["BTC-USD"]
        #     weekend_note = "Wochenende → EURUSD=X inaktiv, BTC-USD zum Test."

    all_attachments: List[str] = []
    all_reasons: List[str] = []
    all_health: List[str] = ([weekend_note] if weekend_note else [])

    for sym in symbols:
        # Daten laden
        df15 = dl_history(sym, intraday_interval, 2) if intraday_interval else pd.DataFrame()
        df1d = dl_history(sym, "1d", 90)

        # Health sammeln
        if intraday_interval and (df15 is None or df15.empty):
            all_health.append("M15: keine/zu wenige OHLC-Daten (vermutlich Wochenende oder Rate-Limit).")
        else:
            all_health.append("M15: OK" if intraday_interval else "M15: übersprungen (Wochenende)")

        if df1d is None or df1d.empty:
            all_health.append("D1: keine/zu wenige OHLC-Daten.")
        else:
            all_health.append("D1: OK")

        # Regime/Signal
        bias, reasons = regime_signal(df15, df1d)
        all_reasons += [f"{sym}: {r}" for r in reasons]

        # Chart (nur wenn Intraday da ist)
        if intraday_interval and not df15.empty:
            path = save_chart(df15, sym, out_dir="reports/out", tz_name=tz_name)
            if path: all_attachments.append(path)

    # Mail bauen & schicken
    subject, body, attachments = build_mail(",".join(symbols), tz_name, bias, all_reasons, all_health, all_attachments)

    send_flag = bool(args.email)
    if send_flag:
        try:
            send_email(subject, body, attachments)
            print("[agent] Versand: OK")
        except Exception:
            print("[agent] Versand FEHLER:")
            traceback.print_exc()
            sys.exit(1)
    else:
        print(subject)
        print("=" * 80)
        print(body)
        print("\nAttachments:", attachments)

if __name__ == "__main__":
    main()
