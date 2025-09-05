# analysis/regime.py
from __future__ import annotations
from typing import Dict, Optional
import pandas as pd
from .indicators import ema_slope

def _last(df: pd.DataFrame, col: str) -> Optional[float]:
    """Letzten Wert sicher holen – None, wenn leer/NaN oder Spalte fehlt."""
    if df is None or len(df) == 0 or col not in df.columns:
        return None
    try:
        val = df[col].iloc[-1]
    except Exception:
        return None
    if val is None or pd.isna(val):
        return None
    try:
        return float(val)
    except Exception:
        return None

# >>> Alias: hält alte Aufrufe kompatibel (agent.py nutzt evtl. last(...))
def last(df: pd.DataFrame, col: str) -> Optional[float]:
    return _last(df, col)

def regime_signal(
    d1: pd.DataFrame,
    h4: pd.DataFrame,
    h1: pd.DataFrame,
    adx_min: float = 20,
    ema50_slope_lookback: int = 5
) -> Dict:
    """
    Multi-Timeframe Bias: UP / DOWN / NEUTRAL
      - H4: ADX>adx_min und +DI>-DI => bullisch (umgekehrt bärisch)
      - D1: Close vs EMA200
      - H1: Close vs EMA50 + EMA50-Steigung
    """

    # Werte sicher lesen
    d1_close, d1_ema200 = _last(d1, "Close"), _last(d1, "EMA200")
    h4_adx, h4_pdi, h4_ndi = _last(h4, "ADX"), _last(h4, "+DI"), _last(h4, "-DI")
    h1_close, h1_ema50 = _last(h1, "Close"), _last(h1, "EMA50")

    # Wenn irgendetwas fehlt -> NEUTRAL statt Crash
    if None in [d1_close, d1_ema200, h4_adx, h4_pdi, h4_ndi, h1_close, h1_ema50]:
        return {"bias": "NEUTRAL", "reasons": ["Indikatoren unvollständig (NaN/None)"]}

    # H4-Regeln
    h4_up   = (h4_adx > adx_min) and (h4_pdi > h4_ndi)
    h4_down = (h4_adx > adx_min) and (h4_ndi > h4_pdi)

    # D1-Regeln
    d1_up   = d1_close > d1_ema200
    d1_down = d1_close < d1_ema200

    # H1-Regeln inkl. EMA50-Slope
    slope = ema_slope(h1["EMA50"], lookback=ema50_slope_lookback)
    slope_ok_up = (slope is not None) and (not pd.isna(slope)) and (slope > 0)
    slope_ok_dn = (slope is not None) and (not pd.isna(slope)) and (slope < 0)
    h1_up   = (h1_close > h1_ema50) and slope_ok_up
    h1_down = (h1_close < h1_ema50) and slope_ok_dn

    # Entscheidung
    if h4_up and d1_up and h1_up:
        return {"bias": "UP",
                "reasons": ["H4 bullisch, D1 über EMA200, H1 über EMA50 mit Steigung > 0"]}

    if h4_down and d1_down and h1_down:
        return {"bias": "DOWN",
                "reasons": ["H4 bärisch, D1 unter EMA200, H1 unter EMA50 mit Steigung < 0"]}

    return {"bias": "NEUTRAL",
            "reasons": [f"Mischlage (H4_up={h4_up}, D1_up={d1_up}, H1_up={h1_up})"]}
    def ema_slope(series: pd.Series, length: int = 50) -> pd.Series:
    """
    Berechnet die Steigung einer EMA-Serie.
    Gibt den Unterschied zwischen aktuellem und vorherigem EMA zurück.
    """
    import pandas_ta as ta
    ema = ta.ema(series, length=length)
    if ema is None:
        return pd.Series(np.nan, index=series.index)
    return ema.diff()
    
