from __future__ import annotations
import numpy as np
import pandas as pd
import pandas_ta as ta

def add_indicators(df: pd.DataFrame, ema_fast=50, ema_slow=200, rsi_len=14, adx_len=14, atr_len=14,
                   psar_af=0.02, psar_max_af=0.2) -> pd.DataFrame:
    d = df.copy()
    d["EMA50"]  = ta.ema(d["Close"], length=ema_fast)
    d["EMA200"] = ta.ema(d["Close"], length=ema_slow)
    adx = ta.adx(d["High"], d["Low"], d["Close"], length=adx_len)
    d["ADX"] = adx[f"ADX_{adx_len}"]
    d["+DI"] = adx[f"DMP_{adx_len}"]
    d["-DI"] = adx[f"DMN_{adx_len}"]
    d["RSI"] = ta.rsi(d["Close"], length=rsi_len)
    d["ATR"] = ta.atr(d["High"], d["Low"], d["Close"], length=atr_len)

    psar = ta.psar(d["High"], d["Low"], d["Close"], af=psar_af, max_af=psar_max_af)
    psar_cols = [c for c in psar.columns if c.startswith("PSAR")]
    d["PSAR"] = psar[psar_cols[0]]
    for c in psar_cols[1:]:
        d["PSAR"] = d["PSAR"].fillna(psar[c])
    return d

def ema_slope(series: pd.Series, lookback: int = 5) -> float:
    if len(series) < lookback + 1:
        return np.nan
    a, b = series.iloc[-1], series.iloc[-(lookback+1)]
    try:
        return ((a / b) - 1.0) * 100.0 / lookback
    except Exception:
        return np.nan
