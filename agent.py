# agent.py
from __future__ import annotations

import argparse, os, io, ssl, time, traceback, datetime as dt
from typing import Dict, List, Tuple
import numpy as np
import pandas as pd
import yfinance as yf
import matplotlib.pyplot as plt
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text    import MIMEText
from email.mime.image   import MIMEImage


# =========================
# Konfiguration
# =========================
TIMEFRAMES: List[Tuple[str, str]] = [
    ("1d",  "6mo"),
    ("4h",  "60d"),
    ("1h",  "30d"),
    ("15m", "10d"),
    ("5m",  "5d"),
]

EMA_FAST, EMA_SLOW = 50, 200
RSI_LEN, ATR_LEN   = 14, 14

# =========================
# Utilities
# =========================
def utc_now() -> dt.datetime:
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)

def to_float(x):
    try:
        return float(x)
    except Exception:
        return np.nan

def safe_download(ticker: str, interval: str, period: str, retries: int = 3, pause: int = 5) -> pd.DataFrame:
    """
    YF Download mit Retry. Verhindert Abbruch bei Rate-Limit/Leerdaten.
    """
    for i in range(1, retries + 1):
        try:
            df = yf.download(ticker, interval=interval, period=period, progress=False)
            if isinstance(df, pd.DataFrame) and not df.empty:
                return df
        except Exception as e:
            print(f"[WARN] yfinance {interval} Versuch {i}/{retries}: {e}")
        print(f"[Retry] Keine Daten für {interval}. Warte {pause}s …")
        time.sleep(pause)
    return pd.DataFrame()

def ta_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Minimal-TA: EMA(50/200), RSI(14), ATR(14). Alles nur mit pandas/numpy.
    """
    df = df.copy()
    # Sicherstellen, dass Spalten groß geschrieben sind (YF kann variieren)
    df.columns = [c.title() for c in df.columns]

    close = df["Close"]

    # EMA
    df["ema50"]  = close.ewm(span=EMA_FAST, adjust=False).mean()
    df["ema200"] = close.ewm(span=EMA_SLOW, adjust=False).mean()

    # RSI
    d = close.diff().to_numpy()
    gain = np.where(d > 0, d, 0.0).ravel()
    loss = np.where(d < 0, -d, 0.0).ravel()
    up   = pd.Series(gain, index=df.index).ewm(alpha=1/RSI_LEN, adjust=False).mean()
    down = pd.Series(loss, index=df.index).ewm(alpha=1/RSI_LEN, adjust=False).mean()
    rs = up / (down.replace(0, np.nan))
    df["rsi14"] = 100 - (100 / (1 + rs))

    # ATR
    hl = (df["High"] - df["Low"]).abs()
    hc = (df["High"] - close.shift()).abs()
    lc = (df["Low"]  - close.shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df["atr14"] = tr.ewm(alpha=1/ATR_LEN, adjust=False).mean()

    return df

def detect_trend(price, e50, e200) -> str:
    price, e50, e200 = to_float(price), to_float(e50), to_float(e200)
    if np.isnan(price) or np.isnan(e50) or np.isnan(e200): return "FLAT"
    if price > e50 > e200:  return "UP"
    if price < e50 < e200:  return "DOWN"
    if price > e50 >= e200: return "UP"
    if price < e50 <= e200: return "DOWN"
    return "FLAT"

def mini_plot(df: pd.DataFrame, title: str) -> bytes:
    fig = plt.figure(figsize=(5, 2.2), dpi=140)
    plt.plot(df.index, df["Close"])
    plt.title(title)
    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png")
    plt.close(fig)
    buf.seek(0)
    return buf.read()

def send_email(subject: str, text_block: str, inline_images: Dict[str, bytes]) -> bool:
    """
    Versand über Secrets: SMTP_USER, SMTP_PASS, EMAIL_TO, SMTP_HOST, SMTP_PORT
    (Host/Port defaulten auf Gmail).
    """
    user = os.getenv("SMTP_USER")
    pw   = os.getenv("SMTP_PASS")
    to   = os.getenv("EMAIL_TO")
    host = os.getenv("SMTP_HOST", "smtp.gmail.com")
    port = int(os.getenv("SMTP_PORT", "587"))

    print("[mailer] EMAIL_TO   =", "***" if to else "None")
    print("[mailer] SMTP_USER  =", "***" if user else "None")
    print("[mailer] SMTP_PASS? =", "JA" if pw else "NEIN")
    print("[mailer] HOST/PORT  =", host, port)

    if not (user and pw and to):
        print("[mailer] Abbruch: SMTP-Env unvollständig.")
        return False

    msg = MIMEMultipart("related")
    msg["From"] = user
    msg["To"] = to
    msg["Subject"] = subject

    alt = MIMEMultipart("alternative")
    msg.attach(alt)
    alt.attach(MIMEText(text_block, "plain", "utf-8"))

    html = ["<html><body><pre style='font-family:Menlo,Consolas,monospace'>",
            text_block, "</pre><hr>"]
    for cid in inline_images.keys():
        html.append(f'<img src="cid:{cid}"><br>')
    html.append("</body></html>")
    alt.attach(MIMEText("".join(html), "html", "utf-8"))

    for cid, png in inline_images.items():
        img = MIMEImage(png, name=f"{cid}.png")
        img.add_header("Content-ID", f"<{cid}>")
        img.add_header("Content-Disposition", "inline", filename=f"{cid}.png")
        msg.attach(img)

    try:
        with smtplib.SMTP(host, port, timeout=30) as s:
            s.ehlo()
            s.starttls(context=ssl.create_default_context())
            s.login(user, pw)
            s.sendmail(user, [to], msg.as_string())
        print("[mailer] Mail erfolgreich gesendet.")
        return True
    except Exception as e:
        print("[mailer] Fehler:", repr(e))
        return False

def format_block(d: Dict[str, str]) -> str:
    lines = []
    for k, v in d.items():
        lines.append(f"{k}={v}")
    return "\n".join(lines)


# =========================
# Analyse
# =========================
def analyze_symbol(symbol: str) -> Dict[str, str]:
    job_start = utc_now()

    # Daten je TF sammeln (mit Retry)
    frames: Dict[str, pd.DataFrame] = {}
    for interval, period in TIMEFRAMES:
        df = safe_download(symbol, interval, period, retries=3, pause=5)
        if df.empty:
            print(f"[FEHLER] Endgültig keine Daten für {interval}. Überspringe …")
            continue
        frames[interval] = ta_indicators(df)

    if not frames:
        # Nichts geladen – neutraler Fallback, aber E-Mail verschicken
        payload = {
            "TYPE": "NEUTRAL",
            "Hinweis": "Keine TF-Daten (Rate-Limit/Fehler).",
            "ZeitUTC": utc_now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        return payload

    # Snapshots (nur vorhandene TFs berücksichtigen)
    last = {k: v.iloc[-1] for k, v in frames.items()}

    # Trends
    trend_D1 = detect_trend(*(to_float(last["1d"][c]) for c in ("Close", "ema50", "ema200"))) if "1d" in last else "FLAT"
    trend_H4 = detect_trend(*(to_float(last["4h"][c]) for c in ("Close", "ema50", "ema200"))) if "4h" in last else "FLAT"
    trend_H1 = detect_trend(*(to_float(last["1h"][c]) for c in ("Close", "ema50", "ema200"))) if "1h" in last else "FLAT"
    trend_M15= detect_trend(*(to_float(last["15m"][c]) for c in ("Close", "ema50", "ema200"))) if "15m" in last else "FLAT"

    trends_str = f"D1={trend_D1} | H4={trend_H4} | H1={trend_H1} | M15={trend_M15}"

    # Preisinfos (best effort)
    close = to_float(last.get("1h", last[list(last.keys())[0]])["Close"])
    d1 = frames.get("1d")
    day_high = to_float(d1["High"].iloc[-1]) if d1 is not None else np.nan
    day_low  = to_float(d1["Low"].iloc[-1])  if d1 is not None else np.nan

    payload = {
        "TYPE": "ANALYSE",
        "Symbol": symbol,
        "Zeitebenen": trends_str,
        "Kurs": f"{close:.5f}" if not np.isnan(close) else "nan",
        "Tag_Hoch": f"{day_high:.5f}" if not np.isnan(day_high) else "nan",
        "Tag_Tief": f"{day_low:.5f}" if not np.isnan(day_low) else "nan",
        "ZeitUTC": utc_now().strftime("%Y-%m-%d %H:%M:%S"),
        "Hinweis": "Einzelne TF evtl. übersprungen (Rate-Limit)."
    }

    return payload, frames


def build_plots(symbol: str, frames: Dict[str, pd.DataFrame]) -> Dict[str, bytes]:
    imgs: Dict[str, bytes] = {}
    for key, title in [("1h", "1h"), ("4h", "4h"), ("1d", "1d"), ("15m", "15m"), ("5m", "5m")]:
        if key in frames and not frames[key].empty:
            imgs[key] = mini_plot(frames[key].tail(300), f"{symbol} {title} – Close")
    return imgs


# =========================
# Main
# =========================
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="EURUSD=X", help="Kommagetrennt, z. B. EURUSD=X,GBPUSD=X")
    ap.add_argument("--tz", default="Europe/Berlin")
    ap.add_argument("--email", action="store_true", help="E-Mail senden")
    args = ap.parse_args()

    symbols = [s.strip() for s in args.symbols.split(",") if s.strip()]
    all_ok = True

    for sym in symbols:
        print(f"[run] Starte Analyse für {sym}")
        try:
            result = analyze_symbol(sym)
            if isinstance(result, dict):
                # nur Payload (kein Frame verfügbar)
                payload = result
                imgs = {}
            else:
                payload, frames = result
                imgs = build_plots(sym, frames)

            subject = f"{sym} – Analyse {payload.get('TYPE','')}: {payload.get('Zeitebenen','')} | {payload.get('ZeitUTC','')}"
            body = format_block(payload)

            if args.email:
                ok = send_email(subject, body, imgs)
                all_ok &= ok
            else:
                print(body)

        except Exception as e:
            all_ok = False
            print(f"[ERROR] {sym}: {e}")
            traceback.print_exc()

    if not all_ok:
        # Nicht hart fehlschlagen – Actions soll trotzdem „grün“ sein.
        print("[DONE] mit Warnungen.")
    else:
        print("[DONE] OK.")

if __name__ == "__main__":
    main()
