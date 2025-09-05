# analysis/indicators.py
from __future__ import annotations
from typing import Optional
import pandas as pd
import numpy as np

def _col_like(df: pd.DataFrame, prefix: str) -> Optional[str]:
    """First column whose upper name starts with prefix (upper)."""
    up = prefix.upper()
    for c in df.columns:
        if str(c).upper().startswith(up):
            return c
    return None

def add_indicators(
    df: pd.DataFrame,
    ema_fast: int = 50,
    ema_slow: int = 200,
    rsi_len: int = 14,
    adx_len: int = 14,
    atr_len: int = 14,
    psar_af: float = 0.02,
    psar_max_af: float = 0.2,
) -> pd.DataFrame:
    """
    Fügt robuste TA-Spalten hinzu. Crasht nicht, wenn ein Indikator wegen
    Datenlänge/Version None liefert – dann kommen NaNs, und der Agent kann
    sauber mit 'NEUTRAL (Indikatoren unvollständig)' weiterlaufen.
    """
    import pandas_ta as ta

    out = df.copy()

    # Spalten normalisieren (Case)
    for k in ["Open", "High", "Low", "Close"]:
        if k not in out.columns and k.lower() in out.columns:
            out[k] = out[k.lower()]

    h = out.get("High")
    l = out.get("Low")
    c = out.get("Close")

    # EMA
    try:
        ema_f = ta.ema(c, length=ema_fast)
    except Exception:
        ema_f = None
    out["EMA50"] = ema_f if ema_f is not None else pd.Series(np.nan, index=out.index)

    try:
        ema_s = ta.ema(c, length=ema_slow)
    except Exception:
        ema_s = None
    out["EMA200"] = ema_s if ema_s is not None else pd.Series(np.nan, index=out.index)

    # RSI
    try:
        rsi = ta.rsi(c, length=rsi_len)
    except Exception:
        rsi = None
    out["RSI"] = rsi if rsi is not None else pd.Series(np.nan, index=out.index)

    # ADX (+DI / -DI)
    try:
        adx_df = ta.adx(h, l, c, length=adx_len)
    except Exception:
        adx_df = None
    if isinstance(adx_df, pd.DataFrame) and not adx_df.empty:
        adx_col = _col_like(adx_df, "ADX")
        dmp_col = _col_like(adx_df, "DMP") or _col_like(adx_df, "+DI")
        dmn_col = _col_like(adx_df, "DMN") or _col_like(adx_df, "-DI")
        out["ADX"] = adx_df[adx_col] if adx_col else pd.Series(np.nan, index=out.index)
        out["+DI"] = adx_df[dmp_col] if dmp_col else pd.Series(np.nan, index=out.index)
        out["-DI"] = adx_df[dmn_col] if dmn_col else pd.Series(np.nan, index=out.index)
    else:
        out["ADX"] = pd.Series(np.nan, index=out.index)
        out["+DI"] = pd.Series(np.nan, index=out.index)
        out["-DI"] = pd.Series(np.nan, index=out.index)

    # ATR
    try:
        atr = ta.atr(h, l, c, length=atr_len)
    except Exception:
        atr = None
    out["ATR"] = atr if atr is not None else pd.Series(np.nan, index=out.index)

    # PSAR (einige Versionen liefern PSARl/PSARs/PSAR)
    try:
        psar_df = ta.psar(h, l, c, af=psar_af, max_af=psar_max_af)
    except Exception:
        psar_df = None
    if isinstance(psar_df, pd.DataFrame) and not psar_df.empty:
        psar_col = _col_like(psar_df, "PSAR")
        out["PSAR"] = psar_df[psar_col] if psar_col else pd.Series(np.nan, index=out.index)
    elif psar_df is not None and not isinstance(psar_df, pd.DataFrame):
        # manche Versionen geben eine Series zurück
        out["PSAR"] = psar_df
    else:
        out["PSAR"] = pd.Series(np.nan, index=out.index)

    return out
