#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os, argparse, traceback
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import List

from dotenv import load_dotenv

# Utils
from utils.helpers import load_yaml
from utils.logger import get_logger
from utils.emailer import send_email

# Analyse-Bausteine
from analysis.data_loader import load_yf, resample_ohlc
from analysis.indicators import add_indicators
from analysis.charting import plot_m15
from analysis.regime import regime_signal as regime_signal_safe
from strategies.wilder import WilderStrategy


# =========================
# Helpers
# =========================
def is_weekend_utc() -> bool:
    # 5=Sa, 6=So
    return datetime.now(timezone.utc).weekday() >= 5

def _len(df) -> int:
    return 0 if df is None else len(df)

def _headline_bias(biases: List[str]) -> str:
    up = any(b.upper() == "UP" for b in biases)
    dn = any(b.upper() == "DOWN" for b in biases)
    if dn: return "DOWN"
    if up: return "UP"
    return "NEUTRAL"

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

def _send_report(subject: str, body_html: str, attachments: list[str] | None) -> None:
    """Sende IMMER eine Mail; wirft bei Fehlern, damit der Run klar scheitert."""
    print("[agent] Versand vorbereiten …")
    print("[agent] EMAIL_TO  =", os.getenv("EMAIL_TO"))
    print("[agent] SMTP_USER =", os.getenv("SMTP_USER"))
    print("[agent] SMTP_HOST =", os.getenv("SMTP_HOST"))
    print("[agent] SMTP_PORT =", os.getenv("SMTP_PORT"))
    print("[agent] Attachments:", attachments or "[]")
    ok = send_email(subject, body_html, attachments or [])
    if not ok:
        raise RuntimeError("E-Mail-Versand meldete False")
    print("[agent] Versand: OK")


# =========================
# Analyse je Symbol
# =========================
def analyze_symbol(symbol: str, tz: str, cfg: dict, logger) -> dict:
    p = cfg["params"]; out_dir = cfg["out_dir"]

    # --- Daten laden (robust)
    try:
        # M15 aus YF
        df15 = load_yf(symbol, interval="15m", period="60d")
        df15 = add_indicators(
            df15,
            adx_len=p.get("adx_len",14),
            rsi_len=p.get("rsi_len",14),
            ema_len=p.get("ema_fast",50),
            psar=True
        ).dropna(how="any")

        # H1/H4 aus 15m
        h1 = resample_ohlc(df15, "1H")
        h4 = resample_ohlc(df15, "4H")
        h1 = add_indicators(h1,
                            adx_len=p.get("adx_len",14),
                            rsi_len=p.get("rsi_len",14),
                            ema_len=p.get("ema_fast",50),
                            psar=True).dropna(how="any")
        h4 = add_indicators(h4,
                            adx_len=p.get("adx_len",14),
                            rsi_len=p.get("rsi_len",14),
                            ema_len=p.get("ema_fast",50),
                            psar=True).dropna(how="any")

        # D1 separat
        d1 = load_yf(symbol, interval="1d", period="6mo")
        d1 = add_indicators(d1,
                            adx_len=p.get("adx_len",14),
                            rsi_len=p.get("rsi_len",14),
                            ema_len=p.get("ema_fast",50),
                            psar=True).dropna(how="any")
    except Exception as e:
        logger.error("Fehler beim Daten/Indikator-Laden: %s", e)
        df15 = h1 = h4 = d1 = None

    # --- Health
    health_html = _health_html(d1, h4, h1, df15)

    # --- Regime
    regime = {"bias": "NEUTRAL", "reasons": ["Fallback (Health prüfen)"]}
    try:
        if all(_len(x) > 0 for x in [d1, h4, h1]):
            regime = regime_signal_safe(d1, h4, h1) or regime
    except Exception as e:
        logger.warning("Regime neutralisiert: %s", e)
    bias = regime.get("bias", "NEUTRAL")

    # --- Strategie (Wilder)
    trade = {"action": "WAIT", "entry": None, "sl": None, "tp": None, "note": "Neutralisiert / Daten prüfen"}
    try:
        if _len(df15) > 0:
            strat = WilderStrategy(cfg)
            trade = strat.signal(df15, bias) or trade
    except Exception as e:
        logger.warning("Strategie neutralisiert: %s", e)

    # --- Chart (immer versuchen; plot_m15 erzeugt bei Bedarf Dummy)
    chart_path = None
    try:
        chart_path = plot_m15(df15, symbol, tz, out_dir=out_dir)
    except Exception as e:
        logger.warning("Chart-Erzeugung ausgelassen: %s", e)

    # --- Report-HTML
    if _len(df15) > 0:
        last_close = float(df15["Close"].iloc[-1])
        last_dt    = df15.index[-1].astimezone(ZoneInfo(tz))
        last_close_txt = f"{last_close:.5f}"
        last_dt_txt    = last_dt.strftime("%Y-%m-%d %H:%M:%S %Z")
    else:
        last_close_txt = "—"
        last_dt_txt    = "—"

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


# =========================
# CLI / main
# =========================
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

    # Ursprüngliche Symbole
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

    # --- WEEKEND SWITCH: am Wochenende auf BTC-USD (24/7) umschalten,
    #     wenn nur FX (=X) angefragt wurde
    weekend_note = ""
    if is_weekend_utc():
        fx_only = len(symbols) > 0 and all(s.endswith("=X") for s in symbols)
        if fx_only:
            symbols = ["BTC-USD"]
            weekend_note = "Wochenende erkannt → FX inaktiv, auf BTC-USD (15m) umgeschaltet."
        else:
            weekend_note = "Wochenende erkannt → Krypto bleibt aktiv (15m)."

    all_html: List[str] = []
    attachments: List[str] = []
    biases: List[str] = []

    for s in symbols:
        try:
            res = analyze_symbol(s, tz, cfg, logger)
            # Hinweis einmalig voranstellen
            html = (f"<p><small>{weekend_note}</small></p>\n" + res["html"]) if weekend_note else res["html"]
            all_html.append(html)
            if res.get("chart"):
                attachments.append(res["chart"])
            biases.append(res.get("bias","NEUTRAL"))
        except Exception:
            biases.append("ERR")
            all_html.append(f"<h2>{s}</h2><pre>{traceback.format_exc()}</pre>")

    headline = _headline_bias(biases)
    prefix   = "[WEEKEND]" if is_weekend_utc() else ""
    subject  = f"{prefix} KI Marktanalyse ({', '.join(symbols)}) – {headline} – {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    body     = "<hr>".join(all_html)

    # Immer senden
    _send_report(subject, body, attachments)


if __name__ == "__main__":
    main()
