#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

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


# -------- Health-Check ---------------------------------------------------------
REQ_COLS = ["Open", "High", "Low", "Close"]
REQ_INDS = ["EMA_50", "EMA_200", "RSI_14", "ADX_14", "DMP_14", "DMN_14", "ATR_14", "PSAR"]

def _ok_df(df, need_cols=REQ_COLS):
    return df is not None and len(df) > 0 and all(c in df.columns for c in need_cols)

def _have_inds(df, names=REQ_INDS):
    if df is None or len(df) == 0: return False
    return any(n in df.columns for n in names)  # nicht alle zwingend – aber mind. etwas

def health_report(d1, h4, h1, m15) -> dict:
    rep = {
        "D1":   {"rows": 0, "have_ohlc": False, "have_inds": False},
        "H4":   {"rows": 0, "have_ohlc": False, "have_inds": False},
        "H1":   {"rows": 0, "have_ohlc": False, "have_inds": False},
        "M15":  {"rows": 0, "have_ohlc": False, "have_inds": False},
        "ok":   False,
        "note": ""
    }
    for name, df in (("D1", d1), ("H4", h4), ("H1", h1), ("M15", m15)):
        rep[name]["rows"] = 0 if df is None else int(len(df))
        rep[name]["have_ohlc"] = _ok_df(df)
        rep[name]["have_inds"] = _have_inds(df)

    # Minimalanforderung für Strategie/Regime
    rep["ok"] = rep["D1"]["have_inds"] and rep["H4"]["have_inds"] and rep["H1"]["have_inds"] and rep["M15"]["have_ohlc"]

    # Hinweis-Text
    msgs = []
    for tf in ("D1", "H4", "H1", "M15"):
        if not rep[tf]["have_ohlc"]:
            msgs.append(f"{tf}: keine/zu wenige OHLC-Daten")
        elif not rep[tf]["have_inds"]:
            msgs.append(f"{tf}: Indikatoren fehlen (werden beim nächsten Lauf neu berechnet)")
    rep["note"] = "; ".join(msgs) if msgs else "Alles bereit."
    return rep


def build_html(symbol: str, tz: str, last_close: float|None, last_dt, regime: dict, trade: dict, health: dict) -> str:
    def yesno(x): return "✅" if x else "—"
    last_line = f"<p><b>Letzter Preis (M15)</b>: {last_close:.5f}</p>" if last_close is not None else "<p><b>Letzter Preis (M15)</b>: —</p>"
    health_tbl = f"""
      <h3>Health</h3>
      <table border="1" cellpadding="4" cellspacing="0">
        <tr><th>TF</th><th>Zeilen</th><th>OHLC</th><th>Indikatoren</th></tr>
        <tr><td>D1</td><td>{health['D1']['rows']}</td><td>{yesno(health['D1']['have_ohlc'])}</td><td>{yesno(health['D1']['have_inds'])}</td></tr>
        <tr><td>H4</td><td>{health['H4']['rows']}</td><td>{yesno(health['H4']['have_ohlc'])}</td><td>{yesno(health['H4']['have_inds'])}</td></tr>
        <tr><td>H1</td><td>{health['H1']['rows']}</td><td>{yesno(health['H1']['have_ohlc'])}</td><td>{yesno(health['H1']['have_inds'])}</td></tr>
        <tr><td>M15</td><td>{health['M15']['rows']}</td><td>{yesno(health['M15']['have_ohlc'])}</td><td>{yesno(health['M15']['have_inds'])}</td></tr>
      </table>
      <p><i>Hinweis:</i> {health['note']}</p>
    """

    body = f"""
    <h2>{symbol} – Multi-Timeframe Analyse</h2>
    <p><b>Zeit</b>: {last_dt.strftime('%Y-%m-%d %H:%M:%S %Z') if last_dt else '—'}</p>
    <p><b>Regime</b>: {regime.get('bias','NEUTRAL')}<br>
       <i>Begründung</i>: {'; '.join(regime.get('reasons', [])) or '—'}</p>
    {last_line}
    <h3>Handelsvorschlag (M15)</h3>
    <ul>
      <li><b>Aktion</b>: {trade.get('action','—')}</li>
      <li><b>Entry</b>: {trade.get('entry','-')}</li>
      <li><b>SL</b>: {trade.get('sl','-')}</li>
      <li><b>TP</b>: {trade.get('tp','-')}</li>
      <li><b>Hinweis</b>: {trade.get('note','—')}</li>
    </ul>
    <p><small>SL/TP ATR-basiert (ATR14, M15). Früher Exit bei PSAR-Flip oder RSI-50 Gegensignal.</small></p>
    {health_tbl}
    """
    return body


def analyze_symbol(symbol: str, tz: str, cfg: dict, logger) -> dict:
    p = cfg["params"]; out_dir = cfg["out_dir"]

    # --- Daten laden
    df15 = load_yf(symbol, interval="15m", period="60d")
    h1 = resample_ohlc(df15, "1H") if df15 is not None else None
    h4 = resample_ohlc(df15, "4H") if df15 is not None else None
    d1 = load_yf(symbol, interval="1d", period="6mo")

    # --- Indikatoren berechnen (robust)
    def _add(df):
        if df is None or len(df) == 0: return df
        return add_indicators(
            df,
            ema_fast=p["ema_fast"], ema_slow=p["ema_slow"],
            rsi_len=p["rsi_len"], adx_len=p["adx_len"], atr_len=p["atr_len"],
            psar_af=p["psar"]["af"], psar_max_af=p["psar"]["max_af"]
        ).dropna(how="any")

    df15 = _add(df15)
    h1   = _add(h1)
    h4   = _add(h4)
    d1   = _add(d1)

    # --- Health prüfen
    health = health_report(d1, h4, h1, df15)

    # --- Regime + Strategie oder neutrale Fallbacks
    if health["ok"]:
        try:
            regime = regime_signal_safe(d1, h4, h1)
        except Exception as e:
            logger.error("Regime-Berechnung fehlgeschlagen: %s", e)
            regime = {"bias": "NEUTRAL", "reasons": ["Regime-Fehler – neutralisiert"]}
        try:
            strat = WilderStrategy(cfg)
            trade = strat.signal(df15, regime["bias"])
        except Exception as e:
            logger.error("Strategie-Berechnung fehlgeschlagen: %s", e)
            trade = {"action": "WAIT", "entry": None, "sl": None, "tp": None, "note": "Strategie-Fehler – neutralisiert"}
    else:
        regime = {"bias": "NEUTRAL", "reasons": ["Unvollständige Daten/Indikatoren – neutralisiert"]}
        trade  = {"action": "WAIT", "entry": None, "sl": None, "tp": None, "note": "Warten bis alle Timeframes & Indikatoren ok sind"}

    # --- Chart nur wenn M15 Daten hat
    chart_path = None
    try:
        if _ok_df(df15) and len(df15) > 0:
            chart_path = plot_m15(df15, symbol, tz, out_dir=out_dir)
    except Exception as e:
        logger.warning("Chart konnte nicht erzeugt werden: %s", e)

    last_close = float(df15["Close"].iloc[-1]) if _ok_df(df15) else None
    last_dt    = df15.index[-1].astimezone(ZoneInfo(tz)) if _ok_df(df15) else None
    html = build_html(symbol, tz, last_close, last_dt, regime, trade, health)
    return {"symbol": symbol, "html": html, "chart_path": chart_path}


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=str, default="", help="Kommagetrennt; leer => configs/symbols.yaml")
    ap.add_argument("--tz", type=str, default="", help="override Zeitzone")
    ap.add_argument("--email", action="store_true", help="Bericht per E-Mail senden")
    ap.add_argument("--settings", type=str, default="configs/settings.yaml")
    ap.add_argument("--symbols_cfg", type=str, default="configs/symbols.yaml")
    # CLI-Override (optional) – falls du ohne .env debuggen willst:
    ap.add_argument("--email_to", type=str, default=os.getenv("EMAIL_TO"))
    ap.add_argument("--smtp_user", type=str, default=os.getenv("SMTP_USER"))
    ap.add_argument("--smtp_pass", type=str, default=os.getenv("SMTP_PASS"))
    ap.add_argument("--smtp_host", type=str, default=os.getenv("SMTP_HOST", "smtp.gmail.com"))
    ap.add_argument("--smtp_port", type=int, default=int(os.getenv("SMTP_PORT", "587")))
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

    # Mail-Config (Secrets oder CLI-Override)
    os.environ["EMAIL_TO"]  = args.email_to or os.getenv("EMAIL_TO", "")
    os.environ["SMTP_USER"] = args.smtp_user or os.getenv("SMTP_USER", "")
    os.environ["SMTP_PASS"] = args.smtp_pass or os.getenv("SMTP_PASS", "")
    os.environ["SMTP_HOST"] = args.smtp_host or os.getenv("SMTP_HOST", "smtp.gmail.com")
    os.environ["SMTP_PORT"] = str(args.smtp_port or os.getenv("SMTP_PORT", "587"))

    all_html, attachments = [], []
    for s in symbols:
        try:
            res = analyze_symbol(s, tz, cfg, logger)
            all_html.append(res["html"])
            if res["chart_path"]:
                attachments.append(res["chart_path"])
        except Exception:
            # Letzter Rettungsanker: nie einen Traceback als Absturz schicken,
            # sondern sauber als <pre> im Report anzeigen:
            logger.error("Analyse-Fehler für %s\n%s", s, traceback.format_exc())
            all_html.append(
                f"<h2>{s}</h2>"
                f"<p><b>Hinweis:</b> Analyse neutralisiert. Details:</p>"
                f"<pre>{traceback.format_exc()}</pre>"
            )

    subject = f"KI Marktanalyse ({', '.join(symbols)}) – {now_tz(tz).strftime('%Y-%m-%d %H:%M')}"
    body = "<hr>".join(all_html)

    send_flag = args.email or bool(cfg.get("report", {}).get("email", False))
    if send_flag:
        try:
            send_email(subject, body, attachments)
        except Exception as e:
            logger.error("[mailer] Versand fehlgeschlagen: %s", e)
            # Fallback: immer in Konsole ausgeben
            print(subject)
            print("=" * 80)
            print(textwrap.fill(body, 120))
            print("\nCharts:", attachments)
    else:
        print(subject)
        print("=" * 80)
        print(textwrap.fill(body, 120))
        print("\nCharts:", attachments)


if __name__ == "__main__":
    main()
