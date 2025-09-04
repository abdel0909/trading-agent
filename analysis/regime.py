#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import argparse
import traceback
import textwrap
from zoneinfo import ZoneInfo
from dotenv import load_dotenv

from utils.helpers import load_yaml, now_tz
from utils.logger import get_logger
from utils.emailer import send_email

from analysis.data_loader import load_yf, resample_ohlc
from analysis.indicators import add_indicators
from analysis.charting import plot_m15
from analysis.regime import regime_signal as regime_signal_safe  # <- sichere Version nutzen
from strategies.wilder import WilderStrategy


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
    p = cfg["params"]; r = cfg["rules"]; out_dir = cfg["out_dir"]

    # ---- Daten laden (15m Basis) + Indikatoren
    df15 = load_yf(symbol, interval="15m", period="60d")
    df15 = add_indicators(
        df15,
        ema_fast=p["ema_fast"], ema_slow=p["ema_slow"],
        rsi_len=p["rsi_len"], adx_len=p["adx_len"], atr_len=p["atr_len"],
        psar_af=p["psar"]["af"], psar_max_af=p["psar"]["max_af"]
    ).dropna()

    # ---- H1/H4 aus 15m resamplen + Indikatoren
    h1 = resample_ohlc(df15, "1H")
    h4 = resample_ohlc(df15, "4H")
    h1 = add_indicators(h1, ema_fast=p["ema_fast"], ema_slow=p["ema_slow"],
                        rsi_len=p["rsi_len"], adx_len=p["adx_len"], atr_len=p["atr_len"],
                        psar_af=p["psar"]["af"], psar_max_af=p["psar"]["max_af"]).dropna()
    h4 = add_indicators(h4, ema_fast=p["ema_fast"], ema_slow=p["ema_slow"],
                        rsi_len=p["rsi_len"], adx_len=p["adx_len"], atr_len=p["atr_len"],
                        psar_af=p["psar"]["af"], psar_max_af=p["psar"]["max_af"]).dropna()

    # ---- D1 separat laden + Indikatoren
    d1 = load_yf(symbol, interval="1d", period="6mo")
    d1 = add_indicators(d1, ema_fast=p["ema_fast"], ema_slow=p["ema_slow"],
                        rsi_len=p["rsi_len"], adx_len=p["adx_len"], atr_len=p["atr_len"],
                        psar_af=p["psar"]["af"], psar_max_af=p["psar"]["max_af"]).dropna()

    # ---- Regime (sichere Version) + Signal (Wilder-Strategie)
    strat = WilderStrategy(cfg)
    regime = regime_signal_safe(d1, h4, h1)
    trade  = strat.signal(df15, regime["bias"])

    # ---- Chart
    chart  = plot_m15(df15, symbol, tz, out_dir=out_dir)

    last_close = float(df15["Close"].iloc[-1])
    last_dt    = df15.index[-1].astimezone(ZoneInfo(tz))
    html = build_html(symbol, tz, last_close, last_dt, regime, trade)
    return {"symbol": symbol, "html": html, "chart_path": chart}


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

    # Symbolliste
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
