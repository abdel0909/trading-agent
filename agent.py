#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import os, argparse, traceback, textwrap
from zoneinfo import ZoneInfo
from dotenv import load_dotenv
from datetime import datetime

from utils.helpers import load_yaml, now_tz
from utils.logger import get_logger
from utils.emailer import send_email

from analysis.data_loader import load_yf, resample_ohlc
from analysis.indicators import add_indicators
from analysis.charting import plot_m15
from analysis.regime import regime_signal as regime_signal_safe
from strategies.wilder import WilderStrategy


# --------------------------------------------------
# Versand-Helfer (immer senden, auch ohne Charts)
# --------------------------------------------------
def _send_report(subject: str, body_html: str, attachments: list) -> None:
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


# --------------------------------------------------
# Health-Check
# --------------------------------------------------
def _len(df): return 0 if df is None else len(df)

def health_status(d1, h4, h1, m15) -> str:
    return f"""
    <h3>Health</h3>
    <ul>
      <li>D1: {_len(d1)} Zeilen</li>
      <li>H4: {_len(h4)} Zeilen</li>
      <li>H1: {_len(h1)} Zeilen</li>
      <li>M15: {_len(m15)} Zeilen</li>
    </ul>
    """


# --------------------------------------------------
# Analyse
# --------------------------------------------------
def analyze_symbol(symbol: str, tz: str, cfg: dict, logger) -> dict:
    p = cfg["params"]; out_dir = cfg["out_dir"]

    try:
        # M15 laden
        df15 = load_yf(symbol, interval="15m", period="60d")
        df15 = add_indicators(df15, **p).dropna()

        # H1/H4
        h1 = resample_ohlc(df15, "1H"); h1 = add_indicators(h1, **p).dropna()
        h4 = resample_ohlc(df15, "4H"); h4 = add_indicators(h4, **p).dropna()

        # D1
        d1 = load_yf(symbol, interval="1d", period="6mo")
        d1 = add_indicators(d1, **p).dropna()

    except Exception as e:
        logger.error("Fehler beim Datenladen: %s", e)
        return {
            "symbol": symbol,
            "html": f"<h2>{symbol}</h2><p>Datenfehler: {e}</p>",
            "chart": None,
            "health": "Datenfehler"
        }

    # Health
    health_html = health_status(d1, h4, h1, df15)

    # Regime + Strategie
    regime = {"bias": "NEUTRAL", "reasons": ["Fallback"]}
    trade = {"action": "WAIT", "note": "Keine Daten"}

    try:
        regime = regime_signal_safe(d1, h4, h1) or regime
    except Exception as e:
        logger.warning("Regime neutralisiert: %s", e)

    try:
        strat = WilderStrategy(cfg)
        trade = strat.signal(df15, regime.get("bias", "NEUTRAL")) or trade
    except Exception as e:
        logger.warning("Strategie neutralisiert: %s", e)

    # Chart
    chart_path = None
    try:
        if _len(df15) > 0:
            chart_path = plot_m15(df15, symbol, tz, out_dir=out_dir)
    except Exception as e:
        logger.warning("Chart ausgelassen: %s", e)

    # Report HTML
    last_close = None if _len(df15) == 0 else float(df15["Close"].iloc[-1])
    last_dt = None if _len(df15) == 0 else df15.index[-1].astimezone(ZoneInfo(tz))

    html = f"""
    <h2>{symbol} – Analyse</h2>
    <p><b>Zeit</b>: {last_dt.strftime('%Y-%m-%d %H:%M:%S %Z') if last_dt else '—'}</p>
    <p><b>Regime</b>: {regime.get('bias')}</p>
    <p><i>Begründung</i>: {', '.join(regime.get('reasons', []))}</p>
    <p><b>Letzter Preis (M15)</b>: {last_close if last_close else '—'}</p>
    <h3>Handelsvorschlag</h3>
    <ul>
      <li>Aktion: {trade.get('action')}</li>
      <li>Entry: {trade.get('entry','-')}</li>
      <li>SL: {trade.get('sl','-')}</li>
      <li>TP: {trade.get('tp','-')}</li>
      <li>Hinweis: {trade.get('note','-')}</li>
    </ul>
    {health_html}
    """

    return {"symbol": symbol, "html": html, "chart": chart_path, "health": health_html}


# --------------------------------------------------
# CLI / main
# --------------------------------------------------
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
    tz = args.tz or os.getenv("TZ", "Europe/Berlin")
    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]

    all_html, attachments = [], []
    for s in symbols:
        try:
            res = analyze_symbol(s, tz, cfg, logger)
            all_html.append(res["html"])
            if res["chart"]:
                attachments.append(res["chart"])
        except Exception:
            all_html.append(f"<h2>{s}</h2><pre>{traceback.format_exc()}</pre>")

    subject = f"KI Marktanalyse ({', '.join(symbols)}) – {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}"
    body = "<hr>".join(all_html)

    # Immer senden!
    _send_report(subject, body, attachments)


if __name__ == "__main__":
    main()
