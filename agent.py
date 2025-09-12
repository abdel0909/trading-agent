# -*- coding: utf-8 -*-
# EUR/USD KI Agent – SIGNAL + EVENT + VIX + Kurs-Levels + INLINE-PLOTS (D1/H4/H1/M15/M5)

import io, os, smtplib, ssl, traceback, datetime as dt
import numpy as np, pandas as pd, yfinance as yf

# Headless-Backend für GitHub Actions
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage

# =========== CONFIG ===========
PAIR = os.getenv("PAIR", "EURUSD=X")
TIMEFRAMES = [("1d","6mo"),("4h","60d"),("1h","30d"),("15m","10d"),("5m","5d")]
EMA_FAST, EMA_SLOW = 50, 200
RSI_LEN, ATR_LEN   = 14, 14
BREAKOUT_BARS      = 10
ATR_BUFFER         = 0.25
TPx, SLx           = 1.5, 1.0
MARKET_MOOD_OVERRIDE = None  # z.B. "Optimistisch"

# --- E-Mail aus ENV/Secrets ---
GMAIL_USER   = os.getenv("SMTP_USER") or ""
APP_PASSWORD = os.getenv("SMTP_PASS") or ""
TO_EMAILS    = [e.strip() for e in (os.getenv("EMAIL_TO") or "").split(",") if e.strip()]
SMTP_HOST    = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT    = int(os.getenv("SMTP_PORT", "587"))

# =========== HELPERS ===========
def utc_now():
    return dt.datetime.utcnow().replace(tzinfo=dt.timezone.utc)

def to_float(x):
    try: return float(x)
    except: return np.nan

def ta_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ema50"]  = df["Close"].ewm(span=EMA_FAST, adjust=False).mean()
    df["ema200"] = df["Close"].ewm(span=EMA_SLOW, adjust=False).mean()
    d = df["Close"].diff().to_numpy()
    gain = np.where(d > 0, d, 0.0).ravel()
    loss = np.where(d < 0, -d, 0.0).ravel()
    up   = pd.Series(gain, index=df.index).ewm(alpha=1/RSI_LEN, adjust=False).mean()
    down = pd.Series(loss, index=df.index).ewm(alpha=1/RSI_LEN, adjust=False).mean()
    rs = up / (down.replace(0, np.nan))
    df["rsi14"] = 100 - (100 / (1 + rs))
    hl = (df["High"] - df["Low"]).abs()
    hc = (df["High"] - df["Close"].shift()).abs()
    lc = (df["Low"]  - df["Close"].shift()).abs()
    tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
    df["atr14"] = tr.ewm(alpha=1/ATR_LEN, adjust=False).mean()
    df[f"hh_{BREAKOUT_BARS}"] = df["High"].shift(1).rolling(BREAKOUT_BARS).max()
    df[f"ll_{BREAKOUT_BARS}"] = df["Low"].shift(1).rolling(BREAKOUT_BARS).min()
    return df.dropna()

def detect_trend(price, e50, e200):
    price, e50, e200 = to_float(price), to_float(e50), to_float(e200)
    if np.isnan(price) or np.isnan(e50) or np.isnan(e200): return "FLAT"
    if price > e50 > e200: return "UP"
    if price < e50 < e200: return "DOWN"
    if price > e50 >= e200: return "UP"
    if price < e50 <= e200: return "DOWN"
    return "FLAT"

def format_mail_block(payload: dict) -> str:
    keys = [
        "TYPE","ZeitUTC","Marktstimmung","Seite","Zeitebenen","Einstieg","SL","TP","Confidence",
        "Kurs","Tag_Hoch","Tag_Tief","H1_Hoch","H1_Tief","HL_24h_Hoch","HL_24h_Tief","VIX",
        "Gründe.tech","Gründe.fund","Nächste_Schritte",
        "job_start_utc","analysis_done_utc","email_sent_utc"
    ]
    return "\n".join(f"{k}={payload.get(k,'')}" for k in keys if k in payload)

def mini_plot(df, title):
    fig = plt.figure(figsize=(5,2.2), dpi=140)
    plt.plot(df.index, df["Close"])
    plt.title(title); plt.tight_layout()
    buf = io.BytesIO(); fig.savefig(buf, format="png"); plt.close(fig)
    buf.seek(0); return buf.read()

def send_mime_email(subject, text_block, images_dict):
    if not (GMAIL_USER and APP_PASSWORD and TO_EMAILS):
        raise RuntimeError("SMTP-Env unvollständig (SMTP_USER/SMTP_PASS/EMAIL_TO)")
    msg = MIMEMultipart("related")
    msg["From"] = f"Ki Agent <{GMAIL_USER}>"
    msg["To"] = ", ".join(TO_EMAILS)
    msg["Subject"] = subject
    alt = MIMEMultipart("alternative"); msg.attach(alt)
    alt.attach(MIMEText(text_block, "plain", "utf-8"))
    html = f"""
    <html><body>
      <pre style="font-family:Menlo,Consolas,monospace">{text_block}</pre>
      <hr>
      <img src="cid:h1"><br>
      <img src="cid:h4"><br>
      <img src="cid:d1"><br>
      <img src="cid:m15"><br>
      <img src="cid:m5">
    </body></html>
    """
    alt.attach(MIMEText(html, "html", "utf-8"))
    for cid, png in images_dict.items():
        img = MIMEImage(png, name=f"{cid}.png")
        img.add_header("Content-ID", f"<{cid}>")
        img.add_header("Content-Disposition", "inline", filename=f"{cid}.png")
        msg.attach(img)

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.ehlo(); s.starttls(context=ssl.create_default_context()); s.ehlo()
        s.login(GMAIL_USER, APP_PASSWORD)
        s.sendmail(GMAIL_USER, TO_EMAILS, msg.as_string())

# =========== CORE ===========
def analyze_once(pair: str = PAIR):
    job_start = utc_now()
    tf_data = {}
    for interval, period in TIMEFRAMES:
        df = yf.download(pair, interval=interval, period=period, progress=False)
        if df.empty: raise RuntimeError(f"Keine Daten für {interval}.")
        df = df.rename(columns=lambda c: c.title())
        tf_data[interval] = ta_indicators(df)
    snap = {k: v.iloc[-1] for k,v in tf_data.items()}

    close, atr_h1, ema50_h1 = to_float(snap["1h"]["Close"]), to_float(snap["1h"]["atr14"]), to_float(snap["1h"]["ema50"])
    day_high = to_float(tf_data["1d"]["High"].iloc[-1])
    day_low  = to_float(tf_data["1d"]["Low"].iloc[-1])
    h1_high  = to_float(tf_data["1h"]["High"].iloc[-1])
    h1_low   = to_float(tf_data["1h"]["Low"].iloc[-1])
    n_last   = min(24, len(tf_data["1h"]))
    hl_24h_high = to_float(tf_data["1h"]["High"].tail(n_last).max())
    hl_24h_low  = to_float(tf_data["1h"]["Low"].tail(n_last).min())

    trend_W1="FLAT"
    trend_D1 = detect_trend(snap["1d"]["Close"],  snap["1d"]["ema50"],  snap["1d"]["ema200"])
    trend_H4 = detect_trend(snap["4h"]["Close"],  snap["4h"]["ema50"],  snap["4h"]["ema200"])
    trend_H1 = detect_trend(snap["1h"]["Close"],  snap["1h"]["ema50"],  snap["1h"]["ema200"])
    trend_M15= detect_trend(snap["15m"]["Close"], snap["15m"]["ema50"], snap["15m"]["ema200"])
    trends_str = f"Trend(W1)={trend_W1} | Trend(D1)={trend_D1} | Trend(H4)={trend_H4} | Trend(M15)={trend_M15}"

    # VIX
    vix = yf.download("^VIX", period="7d", interval="1d", progress=False)
    vix_close = float(vix["Close"].iloc[-1]) if not vix.empty else np.nan
    if vix_close < 15:    vix_mood = "Optimistisch"
    elif vix_close > 25:  vix_mood = "Angst"
    else:                 vix_mood = "Neutral"
    if MARKET_MOOD_OVERRIDE: vix_mood = MARKET_MOOD_OVERRIDE

    # Breakout-Levels
    hh = to_float(snap["1h"][f"hh_{BREAKOUT_BARS}"])
    ll = to_float(snap["1h"][f"ll_{BREAKOUT_BARS}"])
    buy_entry  = hh + ATR_BUFFER*atr_h1
    sell_entry = ll - ATR_BUFFER*atr_h1
    sl_buy,tp_buy   = buy_entry  - SLx*atr_h1, buy_entry  + TPx*atr_h1
    sl_sell,tp_sell = sell_entry + SLx*atr_h1, sell_entry - TPx*atr_h1

    # SIGNAL
    side, reasons = "NONE", []
    if trend_D1=="DOWN" and trend_H4=="DOWN" and trend_H1 in ["DOWN","FLAT"] and close <= sell_entry:
        side="SELL"; reasons.append("D1/H4 abwärts; H1 < 10-Tief.")
    elif trend_D1=="UP" and trend_H4=="UP" and trend_H1 in ["UP","FLAT"] and close >= buy_entry:
        side="BUY";  reasons.append("D1/H4 aufwärts; H1 > 10-Hoch.")
    else:
        reasons.append("Kein sauberer Breakout.")

    # EVENT (Reversal)
    event=None
    rsi_prev, rsi_now = tf_data["1h"]["rsi14"].iloc[-2], tf_data["1h"]["rsi14"].iloc[-1]
    if event is None and trend_D1=="DOWN" and trend_H4=="DOWN":
        if (rsi_prev<30<=rsi_now) and (close>=ema50_h1 or close>=buy_entry):
            event={"TYPE":"EVENT","Marktstimmung":f"{vix_mood} (VIX={vix_close:.2f})","Seite":"NONE","Zeitebenen":trends_str,
                   "Einstieg":f"{buy_entry:.5f}","SL":f"{sl_buy:.5f}","TP":f"{tp_buy:.5f}","Confidence":"65",
                   "Gründe.tech":"RSI<30→≥30 & Close ≥ EMA50/10-High; D1/H4 bärisch.","Gründe.fund":"Hoch-Impact prüfen.","Nächste_Schritte":"H1 über Entry; M15/M5-Breakout."}
    if event is None and trend_D1=="UP" and trend_H4=="UP":
        if (rsi_prev>70>=rsi_now) and (close<=ema50_h1 or close<=sell_entry):
            event={"TYPE":"EVENT","Marktstimmung":f"{vix_mood} (VIX={vix_close:.2f})","Seite":"NONE","Zeitebenen":trends_str,
                   "Einstieg":f"{sell_entry:.5f}","SL":f"{sl_sell:.5f}","TP":f"{tp_sell:.5f}","Confidence":"65",
                   "Gründe.tech":"RSI>70→≤70 & Close ≤ EMA50/10-Low; D1/H4 bullisch.","Gründe.fund":"Hoch-Impact prüfen.","Nächste_Schritte":"H1 unter Entry; M15/M5-Breakout."}

    analysis_done = utc_now()

    payload = event if event else {
        "TYPE":"SIGNAL","Marktstimmung":f"{vix_mood} (VIX={vix_close:.2f})","Seite":side,"Zeitebenen":trends_str,
        "Einstieg":f"{(buy_entry if side=='BUY' else sell_entry) if side!='NONE' else close:.5f}",
        "SL":f"{(sl_buy if side=='BUY' else sl_sell) if side!='NONE' else np.nan:.5f}",
        "TP":f"{(tp_buy if side=='BUY' else tp_sell) if side!='NONE' else np.nan:.5f}",
        "Confidence":"72" if side!="NONE" else "40","Gründe.tech":"; ".join(reasons),
        "Gründe.fund":"Hoch-Impact nicht gefiltert.","Nächste_Schritte":"M15/M5-Bestätigung."
    }
    payload.update({
        "Kurs":f"{close:.5f}","Tag_Hoch":f"{day_high:.5f}","Tag_Tief":f"{day_low:.5f}",
        "H1_Hoch":f"{h1_high:.5f}","H1_Tief":f"{h1_low:.5f}",
        "HL_24h_Hoch":f"{hl_24h_high:.5f}","HL_24h_Tief":f"{hl_24h_low:.5f}","VIX":f"{vix_close:.2f}"
    })
    payload["job_start_utc"]=job_start.strftime("%Y-%m-%d %H:%M:%S")
    payload["analysis_done_utc"]=analysis_done.strftime("%Y-%m-%d %H:%M:%S")
    payload["ZeitUTC"]=utc_now().strftime("%Y-%m-%d %H:%M:%S")
    payload["email_sent_utc"]=utc_now().strftime("%Y-%m-%d %H:%M:%S")

    subject=f"EUR/USD {payload['TYPE']}: {payload['Seite']} ({payload['Confidence']}%) – {payload['Marktstimmung']} | Px={payload['Kurs']} | DHi={payload['Tag_Hoch']} / DLo={payload['Tag_Tief']} | {payload['ZeitUTC']}"
    text_block=format_mail_block(payload)

    imgs={
        "h1":mini_plot(tf_data["1h"].tail(300),"EURUSD 1h – Close"),
        "h4":mini_plot(tf_data["4h"].tail(400),"EURUSD 4h – Close"),
        "d1":mini_plot(tf_data["1d"].tail(260),"EURUSD 1d – Close"),
        "m15":mini_plot(tf_data["15m"].tail(300),"EURUSD 15m – Close"),
        "m5":mini_plot(tf_data["5m"].tail(300),"EURUSD 5m – Close"),
    }

    send_mime_email(subject,text_block,imgs)
    return payload

# =========== RUN ===========
if __name__=="__main__":
    try:
        out=analyze_once(PAIR)
        print(format_mail_block(out))
    except Exception as e:
        print("Fehler:",e); traceback.print_exc()
        # trotzdem eine kurze Fehler-Mail senden, damit du Bescheid weißt:
        try:
            send_mime_email(f"[ERROR] EURUSD Agent – {utc_now():%Y-%m-%d %H:%M:%S} UTC",
                            f"Fehler:\n{e!r}", {})
        except Exception:
            pass
