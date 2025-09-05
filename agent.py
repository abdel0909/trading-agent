#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os, argparse, traceback
from datetime import datetime
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

from utils.helpers import load_yaml, now_tz
from utils.logger import get_logger
from utils.emailer import send_email

from analysis.data_loader import load_yf, resample_ohlc
from analysis.indicators import add_indicators
from analysis.charting import plot_m15
from analysis.regime import regime_signal as regime_signal_safe
from strategies.wilder import WilderStrategy

# ------------------------ Versand-Helper (immer senden) ------------------------
def _send_report(subject: str, body_html: str, attachments: list[str] | None) -> None:
    print("[agent] Versand vorbereiten …")
    print("[agent] EMAIL_TO  =", os.getenv("EMAIL_TO"))
    print("[agent] SMTP_USER =", os.getenv("SMTP_USER"))
    print("[agent] SMTP_HOST =", os.getenv("SMTP_HOST"))
    print("[agent] SMTP_PORT =", os.getenv("SMTP_PORT"))
    print("[agent] Attachments:", attachments or "[]")
    ok = False
    try:
        ok = send_email(subject, body_html, attachments or [])
    except Exception as e:
        print("[agent] send_email Exception:", repr(e))
        ok = False
    print("[agent] Versand:", "OK" if ok else "FEHLGESCHLAGEN")

# ------------------------------ Health / Utils --------------------------------
def _len(df): return 0 if df is None else len(df)

def _health_html(d1, h4, h1, m15) -> str:
    return f"""
    <h3>Health</h3>
    <ul>
      <li>D1:  {_len(d1)} Zeilen</li>
      <li>H4:  {_len(h4)} Zeilen</li>
      <li>H1:  {_len(h1)} Zeilen</li>
      <li>M15: {_len(m15)} Zeilen</li>
    </ul>
    """

def _headline_bias(biases: list[str]) -> str:
    """Gesamt-Bias für Betreff: DOWN > UP > NEUTRAL."""
    upper = [b.upper() for b in biases]
    if any(b == "DOWN" for b in upper): return "DOWN"
    if any(b == "UP"   for b in upper): return "UP"
    return "NEUTRAL"

# --------------------------------- Analyse ------------------------------------
def analyze_symbol(symbol: str, tz: str, cfg: dict, logger) -> dict:
    p = cfg["params"]; out_dir = cfg["out_dir"]

    # Daten + Indikatoren robust laden
    try:
        df15 = load_yf(symbol, interval="15m", period="60d")
        df15 = add_indicators(df15, **p).dropna(how="any")

        h1 = resample_ohlc(df15, "1H"); h1 = add_indicators(h1, **p).dropna(how="any")
        h4 = resample_ohlc(df15, "4H"); h4 = add_indicators(h4, **p).dropna(how="any")

        d1 = load_yf(symbol, interval="1d", period="6mo")
        d1 = add_indicators(d1, **p).dropna(how="any")
    except Exception as e:
        logger.error("Fehler beim Daten/Indikator-Laden: %s", e)
        df15 = h1 = h4 = d1 = None

    # Health-HTML
    health_html = _health_html(d1, h4, h1, df15)

    # Regime (safe) + Strategie
    regime = {"bias": "NEUTRAL", "reasons": ["Fallback (Health prüfen)"]}
    try:
        if all(_len(x) > 0 for x in [d1, h4, h1]):  # sinnvolle Mindestbedingung
            regime = regime_signal_safe(d1, h4, h1) or regime
    except Exception as e:
        logger.warning("Regime neutralisiert: %s", e)
    bias = regime.get("bias", "NEUTRAL")

    trade = {"action": "WAIT", "entry": None, "sl": None, "tp": None, "note": "Neutralisiert / Daten prüfen"}
    try:
        if _len(df15) > 0:
            strat = WilderStrategy(cfg)
            trade = strat.signal(df15, bias) or trade
    except Exception as e:
        logger.warning("Strategie neutralisiert: %s", e)

    # Chart (immer erzeugen – bei leeren Daten Dummy-PNG)
    chart_path = None
    try:
        chart_path = plot_m15(df15, symbol, tz, out_dir=out_dir)
    except Exception as e:
        logger.warning("Chart-Erzeugung fehlgeschlagen: %s", e)

    # HTML-Report
    last_close = None if _len(df15) == 0 else float(df15["Close"].iloc[-1])
    last_dt    = None if _len(df15) == 0 else df15.index[-1].astimezone(ZoneInfo(tz))
    last_close_txt = f"{last_close:.5f}" if last_close is not None else "—"
    last_dt_txt    = last_dt.strftime("%Y-%m-%d %H:%M:%S %Z") if last_dt else "—"

    html = f"""
    <h2>{symbol} – Multi-Timeframe Analyse</h2>
    <p><b>Zeit</b>: {last_dt_txt}</p>
    <p><b>Regime</b>: {bias}<br>
       <i>Begründung</i>: {', '.join(regime.get('reasons', []))}</p>
    <p><b>Letzter Preis (M15)</b>: {last_close_txt}</p>

    <h3>Handelsvorschlag (Wilder, M15)</h3>
    <ul>
      <li><b>Aktion</b>: {trade.get('action','-')}</li>
      <li><b>Entry</b>: {trade.get('entry','-')}</li>
      <li><b>SL</b>: {trade.get('sl','-')}</li>
      <li><b>TP</b>: {trade.get('tp','-')}</li>
      <li><b>Hinweis</b>: {trade.get('note','-')}</li>
    </ul>
    <p><small>SL/TP ATR-basiert (ATR14, M15). Früher Exit bei PSAR-Flip oder RSI-50 Gegensignal.</small></p>

    {health_html}
    """

    return {
        "symbol": symbol,
        "html": html,
        "chart": chart_path,
        "bias": bias,
    }

# ---------------------------------- CLI/main ----------------------------------
def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=str, default="EURUSD=X")
    ap.add_argument("--tz", type=str, default="Europe/Berlin")
    ap.add_argument("--email", action="store_true")
    ap.add_argument("--settings", type=str, default="configs/settings.yaml")
    return ap.parse_args()

def main():
    load_dotenv()
    logger = get_logger()
    args = parse_args()

    cfg = load_yaml(args.settings)
    tz  = args.tz or os.getenv("TZ", "Europe/Berlin")
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

    all_html, attachments, biases = [], [], []

    for s in symbols:
        try:
            res = analyze_symbol(s, tz, cfg, logger)
            all_html.append(res["html"])
            if res.get("chart"): attachments.append(res["chart"])
            biases.append(res.get("bias","NEUTRAL"))
        except Exception:
            biases.append("ERR")
            all_html.append(f"<h2>{s}</h2><pre>{traceback.format_exc()}</pre>")

    headline = _headline_bias(biases)
    subject  = f"KI Marktanalyse ({', '.join(symbols)}) – {headline} – {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    body     = "<hr>".join(all_html)

    # Immer senden (failsafe)
    _send_report(subject, body, attachments)

if __name__ == "__main__":
    main()
