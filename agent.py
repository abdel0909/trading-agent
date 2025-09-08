# agent.py
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import pandas as pd
import numpy as np

# --- optionale .env (lokal); in Actions kommen die Variablen über Secrets ---
try:
    from dotenv import load_dotenv
    # Projekt-Root (.env liegt hier typischerweise)
    BASE_DIR = Path(__file__).resolve().parent
    ENV_PATH = BASE_DIR / ".env"
    if ENV_PATH.exists():
        load_dotenv(dotenv_path=ENV_PATH)
        print(f"[env] using: {ENV_PATH}")
except Exception as e:
    print("[env] Hinweis:", repr(e))

# 3rd-party für Daten/Indikatoren/Charts
import yfinance as yf
import pandas_ta as ta
import mplfinance as mpf

# eigener Mailer
from utils.emailer import send_email


# ------------------------------------------------------------
# Konfiguration & Hilfen
# ------------------------------------------------------------
OUT_DIR = Path("reports/out")
OUT_DIR.mkdir(parents=True, exist_ok=True)


def mask(s: str | None) -> str:
    if not s:
        return "None"
    return s[:2] + "***" + s[-2:]


def now_ts(tz: str) -> str:
    """Zeitzonen-sicherer Zeitstempel für Betreff und Report."""
    try:
        # Python 3.9+: zoneinfo ohne Extra-Paket
        from zoneinfo import ZoneInfo  # type: ignore
        return pd.Timestamp.now(tz=ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        # Fallback: naive Zeit
        return pd.Timestamp.now().strftime("%Y-%m-%d %H:%M")


def is_weekend(symbol: str) -> bool:
    """FX ist am WE zu; bei Krypto (BTC-USD & Co.) nicht."""
    fx_like = symbol.upper().endswith("=X")
    if not fx_like:
        return False
    wd = pd.Timestamp.utcnow().weekday()  # 5=Sa, 6=So
    return wd in (5, 6)


# ------------------------------------------------------------
# Daten holen (robust)
# ------------------------------------------------------------
def download_series(symbol: str, interval: str, period: str) -> pd.DataFrame | None:
    """
    Holt Kursdaten über yfinance; gibt None zurück, wenn leer/Rate-Limit.
    """
    try:
        df = yf.download(symbol, interval=interval, period=period, auto_adjust=False, progress=False)
        if isinstance(df, pd.DataFrame) and not df.empty:
            # Normiere Spaltennamen (mpf erwartet genau diese)
            cols = {c.lower(): c for c in df.columns}
            # yfinance gibt meist: 'Open','High','Low','Close','Adj Close','Volume'
            df = df.rename(columns=str.title)
            return df
        return None
    except Exception as e:
        print(f"[data] download error {symbol} ({interval}/{period}):", repr(e))
        return None


def health_counts(dfs: Dict[str, pd.DataFrame | None]) -> Dict[str, int]:
    return {tf: (0 if (df is None or df.empty) else len(df)) for tf, df in dfs.items()}


# ------------------------------------------------------------
# Indikatoren (safe)
# ------------------------------------------------------------
def add_indicators(df: pd.DataFrame, tf_label: str) -> pd.DataFrame:
    """
    Fügt wenige, robuste Wilder/Trend-Indikatoren hinzu (ADX, EMA, RSI).
    Gibt bei zu kurzer Historie ein DataFrame mit NaNs zurück (kein None!).
    """
    if df is None or df.empty:
        # leeres DF mit erwarteten Spalten
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume",
                                     f"ADX_14_{tf_label}", f"EMA_50_{tf_label}", f"RSI_14_{tf_label}"])

    df = df.copy()

    # pandas-ta erwartet Series
    try:
        adx = ta.adx(df["High"], df["Low"], df["Close"], length=14)  # gibt mehrere Spalten zurück
        # Spalte 'ADX_14' finden (kann je nach Version leicht variieren)
        adx_col = [c for c in adx.columns if c.upper().startswith("ADX_14")]
        df[f"ADX_14_{tf_label}"] = adx[adx_col[0]] if adx_col else np.nan
    except Exception as e:
        print(f"[ta] ADX({tf_label}):", repr(e))
        df[f"ADX_14_{tf_label}"] = np.nan

    try:
        df[f"EMA_50_{tf_label}"] = ta.ema(df["Close"], length=50)
    except Exception as e:
        print(f"[ta] EMA50({tf_label})", repr(e))
        df[f"EMA_50_{tf_label}"] = np.nan

    try:
        df[f"RSI_14_{tf_label}"] = ta.rsi(df["Close"], length=14)
    except Exception as e:
        print(f"[ta] RSI14({tf_label})", repr(e))
        df[f"RSI_14_{tf_label}"] = np.nan

    return df


def regime_signal(d1: pd.DataFrame | None,
                  h4: pd.DataFrame | None,
                  h1: pd.DataFrame | None) -> Tuple[str, str]:
    """
    Minimaler, robuster Regime-Detektor:
    - UP, wenn EMA50 auf D1 & H4 steigend und ADX>18
    - DOWN, wenn EMA50 fallend und ADX>18
    - sonst NEUTRAL
    """
    def slope_last(series: pd.Series, n: int = 5) -> float:
        s = series.dropna().astype(float)
        if len(s) < n + 1:
            return 0.0
        return float(s.iloc[-1] - s.iloc[-1 - n])

    def last_adx(df: pd.DataFrame, col_prefix: str) -> float:
        cols = [c for c in df.columns if c.startswith(f"ADX_14_{col_prefix}")]
        if not cols:
            return 0.0
        return float(pd.to_numeric(df[cols[0]], errors="coerce").dropna().iloc[-1]) if not df.empty else 0.0

    # Defaults neutral
    if d1 is None or d1.empty or h4 is None or h4.empty:
        return "NEUTRAL", "Unvollständige Daten (D1/H4) – neutralisiert"

    s_d1 = slope_last(d1[[c for c in d1.columns if c.startswith("EMA_50_D1")][0]])
    s_h4 = slope_last(h4[[c for c in h4.columns if c.startswith("EMA_50_H4")][0]])
    adx_d1 = last_adx(d1, "D1")
    adx_h4 = last_adx(h4, "H4")

    strong = (adx_d1 > 18) and (adx_h4 > 18)
    if s_d1 > 0 and s_h4 > 0 and strong:
        return "UP", "EMA50 steigend (D1/H4) & ADX>18"
    if s_d1 < 0 and s_h4 < 0 and strong:
        return "DOWN", "EMA50 fallend (D1/H4) & ADX>18"
    return "NEUTRAL", "Kein klarer Trend (EMA/ADX)"


# ------------------------------------------------------------
# Chart
# ------------------------------------------------------------
def plot_m15(df_m15: pd.DataFrame, symbol: str, tz: str) -> Path | None:
    if df_m15 is None or df_m15.empty:
        return None
    try:
        last_ts = df_m15.index.tz_localize("UTC", level=None, nonexistent="shift_forward", ambiguous="NaT")
        # YF liefert meist tz-aware oder naive; robust umsetzen:
        try:
            from zoneinfo import ZoneInfo  # type: ignore
            last_local = last_ts.tz_convert(ZoneInfo(tz))
        except Exception:
            last_local = last_ts

        title = f"{symbol}  M15 – {str(last_local[-1])[:16]} ({tz})"
        out_path = OUT_DIR / f"{symbol.replace('=','_')}_M15.png"
        mpf.plot(
            df_m15,
            type="candle",
            style="charles",
            mav=(20, 50),
            volume=True,
            title=title,
            savefig=dict(fname=str(out_path), dpi=120, bbox_inches="tight"),
        )
        return out_path
    except Exception as e:
        print("[plot] Fehler beim Chart:", repr(e))
        return None


# ------------------------------------------------------------
# E-Mail HTML
# ------------------------------------------------------------
def build_html(symbol: str,
               tz: str,
               regime: str,
               reason: str,
               health: Dict[str, int],
               last_price: float | None) -> str:
    def b(v): return f"<b>{v}</b>"
    price_html = f"{last_price:.5f}" if last_price is not None else "—"
    health_rows = "".join(
        f"<tr><td>{tf}</td><td>{cnt}</td></tr>" for tf, cnt in health.items()
    )

    html = f"""
    <h2>{symbol} – Multi-Timeframe Analyse</h2>
    <p><b>Zeit:</b> {now_ts(tz)} ({tz})</p>

    <p><b>Regime:</b> {regime}<br>
    <b>Begründung:</b> {reason}</p>

    <p><b>Letzter Preis (M15):</b> {price_html}</p>

    <h3>Handelsvorschlag (Wilder, M15)</h3>
    <ul>
      <li><b>Aktion:</b> {"WAIT" if regime=="NEUTRAL" else ("BUY" if regime=="UP" else "SELL")}</li>
      <li><b>Entry:</b> None</li>
      <li><b>SL:</b> None</li>
      <li><b>TP:</b> None</li>
      <li><b>Hinweis:</b> Neutralisiert / Daten prüfen</li>
    </ul>

    <h3>Health</h3>
    <table border="1" cellpadding="4" cellspacing="0">
      <tr><th>TF</th><th>Zeilen</th></tr>
      {health_rows}
    </table>

    <p><small>SL/TP ATR-basiert (ATR14, M15). Früher Exit bei PSAR-Flip oder RSI-50 Gegensignal.</small></p>
    """
    # Weekend-/Fallback-Hinweise
    if is_weekend(symbol):
        html = "<p><i>Wochenende erkannt → FX inaktiv, auf Krypto (z. B. BTC-USD) umgeschaltet.</i></p>" + html
    return html


# ------------------------------------------------------------
# Hauptlogik pro Symbol
# ------------------------------------------------------------
def analyze_symbol(symbol: str, tz: str, logger_prefix: str = "[agent]") -> Tuple[str, List[Path]]:
    print(f"{logger_prefix} Starte Analyse für {symbol} …")

    # 1) Daten holen: D1/H4/H1/M15
    d1 = download_series(symbol, "1d", "6mo")
    h4 = download_series(symbol, "60m", "60d")  # YF hat kein 4h – wir nehmen 1h und glätten über Indikatoren
    h1 = download_series(symbol, "60m", "14d")
    m15 = download_series(symbol, "15m", "5d")

    dfs = {"D1": d1, "H4": h4, "H1": h1, "M15": m15}
    hc = health_counts(dfs)
    print(f"{logger_prefix} Health:", hc)

    # 2) Indikatoren
    d1i = add_indicators(d1, "D1")
    h4i = add_indicators(h4, "H4")
    h1i = add_indicators(h1, "H1")
    m15i = add_indicators(m15, "M15")

    # 3) Regime
    regime, reason = regime_signal(d1i, h4i, h1i)

    # 4) Chart (optional)
    chart_path = plot_m15(m15, symbol, tz)
    attachments: List[Path] = []
    if chart_path and chart_path.exists():
        attachments.append(chart_path)

    # 5) Letzter Preis (M15)
    last_price = None
    if m15 is not None and not m15.empty:
        try:
            last_price = float(m15["Close"].iloc[-1])
        except Exception:
            last_price = None

    # 6) HTML
    html = build_html(symbol, tz, regime, reason, hc, last_price)

    return html, attachments


# ------------------------------------------------------------
# main
# ------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Trading Agent (Multi-Timeframe, Wilder-Regeln)")
    parser.add_argument("--symbols", type=str, default="EURUSD=X", help="Kommagetrennte Symbole, z. B. EURUSD=X,BTC-USD")
    parser.add_argument("--tz", type=str, default=os.getenv("TZ", "Europe/Berlin"), help="IANA Zeitzone")
    parser.add_argument("--email", action="store_true", help="Mail mit Report senden")
    args = parser.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    tz = args.tz or "Europe/Berlin"

    # Mail-Konfiguration (nur zum Loggen, der Mailversand checkt selbst auf Vollständigkeit)
    print("[emailer] Konfiguration geladen (env):")
    print("  EMAIL_TO  =", mask(os.getenv("EMAIL_TO")))
    print("  SMTP_USER =", mask(os.getenv("SMTP_USER")))
    print("  SMTP_PASS?", "JA" if os.getenv("SMTP_PASS") else "NEIN")
    print("  SMTP_HOST =", os.getenv("SMTP_HOST", "smtp.gmail.com"))
    print("  SMTP_PORT =", os.getenv("SMTP_PORT", "587"))

    for s in symbols:
        # Weekend-Handling für FX: auf BTC-USD ausweichen
        sym = s
        if is_weekend(s):
            print(f"[agent] Wochenende → FX pausiert. Weiche für Mail/Chart auf BTC-USD aus.")
            sym = "BTC-USD"

        try:
            html, attachments = analyze_symbol(sym, tz)
        except Exception as e:
            # Harte, aber saubere Fallback-Mail
            subject = f"KI Marktanalyse ({sym}) – {now_ts(tz)}"
            tb = f"<pre>{pd.Timestamp.now()}: {repr(e)}</pre>"
            html = f"<h3>{sym}</h3><p><b>Fehler in der Analyse:</b></p>{tb}"
            attachments = []

        subject = f"KI Marktanalyse ({sym}) – {now_ts(tz)}"

        if args.email:
            try:
                ok = send_email(subject, html, [str(p) for p in attachments])
                print("[agent] Versand:", "OK" if ok else "NOK")
            except Exception as e:
                print("[agent] Versand fehlgeschlagen – Report nur in Konsole ausgegeben.")
                print(repr(e))
                print(subject)
                print("=" * 80)
                print(html)
        else:
            print(subject)
            print("=" * 80)
            print(html)


if __name__ == "__main__":
    main()
