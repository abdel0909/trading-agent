#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# --- .env robust laden ( immer relativ zu agent.py ) ---
from dotenv import load_dotenv
import os
ENV_PATH = os.path.join(os.path.dirname(__file__), ".env")
load_dotenv(dotenv_path=ENV_PATH)  # <-- erzwingt den Pfad
from __future__ import annotations
print(f"[env] using: {ENV_PATH}")
for k in ("EMAIL_TO", "SMTP_USER", "SMTP_HOST", "SMTP_PORT", "TZ"):
    v = os.getenv(k)
    print(f"[env] {k} = {v if k!='SMTP_PASS' else ('***' if v else None)}")

import os, argparse, traceback, textwrap
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


def _fmt_info(symbol: str, msg: str) -> dict:
    return {"symbol": symbol, "html": f"<h2>{symbol}</h2><p><b>Info:</b> {msg}</p>", "chart_path": None}

def _fmt_error(symbol: str, msg: str) -> dict:
    return {"symbol": symbol, "html": f"<h2>{symbol}</h2><p><b>Fehler:</b> {msg}</p>", "chart_path": None}

def _tz_safe(dt, tz: str):
    # yfinance-Index kann tz-naiv sein → als UTC interpretieren und in gewünschte TZ konvertieren
    if getattr(dt, "tzinfo", None) is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(ZoneInfo(tz))

def build_html(symbol: str, tz: str, last_close: float, last_dt, regime: dict, trade: dict) -> str:
    return f"""
    <h2>{symbol} – Multi-Timeframe Analyse</h2>
    <p><b>Zeit</b>: {last_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}</p>
    <p><b>Regime</b>: {regime['bias']}<br>
       <i>Begründung</i>: {'; '.join(regime.get('reasons', []))}</p>
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


def analyze_symbol(symbol: str, tz: str, cfg: dict, logger) -> dict:
    p = cfg["params"]; out_dir = cfg["out_dir"]

    # ---- 15m laden
    df15 = load_yf(symbol, interval="15m", period="60d")
    if df15 is None or df15.empty:
        return _fmt_error(symbol, "Keine 15m-Daten geladen (yfinance leer).")

    # ---- Indikatoren 15m
    df15 = add_indicators(
        df15,
        ema_fast=p["ema_fast"], ema_slow=p["ema_slow"],
        rsi_len=p["rsi_len"], adx_len=p["adx_len"], atr_len=p["atr_len"],
        psar_af=p["psar"]["af"], psar_max_af=p["psar"]["max_af"]
    ).dropna()
    if df15.empty:
        return _fmt_info(symbol, "Indikatoren auf M15 noch unvollständig (NaN) – später erneut versuchen.")

    # ---- H1/H4 aus 15m
    h1 = resample_ohlc(df15, "1H")
    h4 = resample_ohlc(df15, "4H")
    h1 = add_indicators(h1, ema_fast=p["ema_fast"], ema_slow=p["ema_slow"],
                        rsi_len=p["rsi_len"], adx_len=p["adx_len"], atr_len=p["atr_len"],
                        psar_af=p["psar"]["af"], psar_max_af=p["psar"]["max_af"]).dropna()
    h4 = add_indicators(h4, ema_fast=p["ema_fast"], ema_slow=p["ema_slow"],
                        rsi_len=p["rsi_len"], adx_len=p["adx_len"], atr_len=p["atr_len"],
                        psar_af=p["psar"]["af"], psar_max_af=p["psar"]["max_af"]).dropna()
    if h1.empty or h4.empty:
        return _fmt_info(symbol, "H1/H4-Indikatoren unvollständig – später erneut versuchen.")

    # ---- D1 separat
    d1 = load_yf(symbol, interval="1d", period="6mo")
    if d1 is None or d1.empty:
        return _fmt_error(symbol, "Keine D1-Daten geladen.")
    d1 = add_indicators(d1, ema_fast=p["ema_fast"], ema_slow=p["ema_slow"],
                        rsi_len=p["rsi_len"], adx_len=p["adx_len"], atr_len=p["atr_len"],
                        psar_af=p["psar"]["af"], psar_max_af=p["psar"]["max_af"]).dropna()
    if d1.empty:
        return _fmt_info(symbol, "D1-Indikatoren unvollständig – später erneut versuchen.")

    # ---- Regime + Signal
    strat = WilderStrategy(cfg)
    regime = regime_signal_safe(d1, h4, h1)
    trade  = strat.signal(df15, regime["bias"])

    # ---- Chart
    try:
        chart_path = plot_m15(df15, symbol, tz, out_dir=out_dir)
    except Exception as e:
        logger.warning("Charting-Fehler %s: %s", symbol, e)
        chart_path = None

    # ---- Report
    last_close = float(df15["Close"].iloc[-1])
    last_dt    = _tz_safe(df15.index[-1], tz)
    html = build_html(symbol, tz, last_close, last_dt, regime, trade)
    return {"symbol": symbol, "html": html, "chart_path": chart_path}


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=str, default="", help="Kommagetrennt; leer => configs/symbols.yaml")
    ap.add_argument("--tz", type=str, default="", help="override Zeitzone")
    ap.add_argument("--email", action="store_true", help="Bericht per E-Mail senden")
    ap.add_argument("--settings", type=str, default="configs/settings.yaml")
    ap.add_argument("--symbols_cfg", type=str, default="configs/symbols.yaml")
    return ap.parse_args()


def main():
    load_dotenv()
    logger = get_logger()

    args = parse_args()
    cfg = load_yaml(args.settings)
    tz  = args.tz or cfg.get("timezone") or os.environ.get("TZ", "Europe/Berlin")

    # Symbole
    if args.symbols:
        symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    else:
        sy_cfg = load_yaml(args.symbols_cfg)
        symbols = sy_cfg.get("symbols", ["EURUSD=X"])

    all_html, attachments = [], []
    for s in symbols:
        try:
            res = analyze_symbol(s, tz, cfg, logger)
            all_html.append(res["html"])
            if res["chart_path"]:
                attachments.append(res["chart_path"])
        except Exception:
            logger.error("Analyse-Fehler für %s\n%s", s, traceback.format_exc())
            all_html.append(f"<h2>{s}</h2><pre>{traceback.format_exc()}</pre>")

    subject = f"KI Marktanalyse ({', '.join(symbols)}) – {now_tz(tz).strftime('%Y-%m-%d %H:%M')}"
    body = "<hr>".join(all_html)

    send_flag = args.email or bool(cfg.get("report", {}).get("email", False))
    if send_flag:
        send_email(subject, body, attachments)
    else:
        print(subject)
        print("=" * 80)
        print(textwrap.fill(body, 120))
        print("\nCharts:", attachments)


if __name__ == "__main__":
    main()
