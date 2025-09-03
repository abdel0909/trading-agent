from __future__ import annotations
import numpy as np
import pandas as pd

def entry_exit_on_m15(m15: pd.DataFrame, bias: str,
                      pullback_atr_frac=0.25, sl_atr_mult=1.5, tp_atr_mult=2.0) -> dict:
    out = {"action": "WAIT", "note": "Kein Setup", "entry": None, "sl": None, "tp": None}
    if len(m15) < 20:
        out["note"] = "Zu wenige Bars"
        return out

    close = float(m15["Close"].iloc[-1])
    ema50 = float(m15["EMA50"].iloc[-1])
    rsi   = float(m15["RSI"].iloc[-1])
    atr   = float(m15["ATR"].iloc[-1])
    psar  = float(m15["PSAR"].iloc[-1])
    prev_rsi = float(m15["RSI"].iloc[-2])

    pullback_ok = abs(close - ema50) <= pullback_atr_frac * atr

    if bias == "UP":
        crossed_up = (prev_rsi <= 50) and (rsi > 50)
        if (close > ema50) and crossed_up and pullback_ok:
            entry = round(close, 5)
            sl    = round(entry - sl_atr_mult * atr, 5)
            tp    = round(entry + tp_atr_mult * atr, 5)
            note  = "UP-Bias Entry (RSI>50, Pullback, >EMA50)"
            if psar > close: note += " | Achtung: PSAR über Preis (möglicher Flip)."
            return {"action":"BUY","note":note,"entry":entry,"sl":sl,"tp":tp}

    if bias == "DOWN":
        crossed_dn = (prev_rsi >= 50) and (rsi < 50)
        if (close < ema50) and crossed_dn and pullback_ok:
            entry = round(close, 5)
            sl    = round(entry + sl_atr_mult * atr, 5)
            tp    = round(entry - tp_atr_mult * atr, 5)
            note  = "DOWN-Bias Entry (RSI<50, Pullback, <EMA50)"
            if psar < close: note += " | Achtung: PSAR unter Preis (möglicher Flip)."
            return {"action":"SELL","note":note,"entry":entry,"sl":sl,"tp":tp}

    return out
