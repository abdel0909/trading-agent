# analysis/regime.py
from __future__ import annotations
from typing import Dict, Optional
import pandas as pd
from .indicators import ema_slope

def _last(df: pd.DataFrame, col: str) -> Optional[float]:
    """
    Sicher den letzten Wert holen.
    Rückgabe: float oder None (falls df/col fehlt oder NaN).
    """
    if df is None or len(df) == 0 or col not in df.columns:
        return None
    try:
        val = df[col].iloc[-1]
    except Exception:
        return None
    # NaN/None abfangen
    if val is None or (isinstance(val, float) and pd.isna(val)) or pd.isna(val):
        return None
    try:
        return float(val)
    except Exception:
        return None

def _all_ok(*vals) -> bool:
    """True, wenn alle Werte vorhanden (nicht None/NaN)."""
    for v in vals:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return False
    return True

def regime_signal(
    d1: pd.DataFrame,
    h4: pd.DataFrame,
    h1: pd.DataFrame,
    adx_min: float = 20,
    ema50_slope_lookback: int = 5
) -> Dict:
    """
    Multi-Timeframe-Regime:
      - H4: ADX>adx_min & +DI>-DI => bullisch, umgekehrt bärisch
      - D1: Close vs EMA200
      - H1: Close vs EMA50 UND EMA50-Slope passend
    Rückgabe: {"bias": "UP|DOWN|NEUTRAL", "reasons": [..]}
    """

    # 1) Pflichtwerte sicherstellen (sanft – lieber NEUTRAL als crashen)
    need = {
        "d1": (d1, ["Close", "EMA200"]),
        "h4": (h4, ["ADX", "+DI", "-DI"]),
        "h1": (h1, ["Close", "EMA50"]),
    }
    for name, (df, cols) in need.items():
        if df is None or len(df) == 0:
            return {"bias": "NEUTRAL", "reasons": [f"{name} leer (keine Daten)"]}
        for c in cols:
            if _last(df, c) is None:
                return {"bias": "NEUTRAL", "reasons": [f"Indikator fehlt/NaN: {name}.{c}"]}

    # 2) Werte lesen
    h4_adx = _last(h4, "ADX")
    h4_pdi = _last(h4, "+DI")
    h4_ndi = _last(h4, "-DI")

    d1_close  = _last(d1, "Close")
    d1_ema200 = _last(d1, "EMA200")

    h1_close  = _last(h1, "Close")
    h1_ema50  = _last(h1, "EMA50")

    if not _all_ok(h4_adx, h4_pdi, h4_ndi, d1_close, d1_ema200, h1_close, h1_ema50):
        return {"bias": "NEUTRAL", "reasons": ["Indikatoren unvollständig (NaN)"]}

    # 3) Einzelregeln
    # H4-Trendstärke & Richtung
    h4_up   = (h4_adx > adx_min) and (h4_pdi > h4_ndi)
    h4_down = (h4_adx > adx_min) and (h4_ndi > h4_pdi)

    # D1-Lage relativ zur EMA200
    d1_up   = d1_close > d1_ema200
    d1_down = d1_close < d1_ema200

    # H1-Lage + Steigung EMA50
    slope = ema_slope(h1["EMA50"], lookback=ema50_slope_lookback)
    slope_up_ok = (slope is not None) and (not pd.isna(slope)) and (slope > 0)
    slope_dn_ok = (slope is not None) and (not pd.isna(slope)) and (slope < 0)

    h1_up   = (h1_close > h1_ema50) and slope_up_ok
    h1_down = (h1_close < h1_ema50) and slope_dn_ok

    # 4) Entscheidung
    if h4_up and d1_up and h1_up:
        return {
            "bias": "UP",
            "reasons": ["H4 ADX/+DI bullisch, D1 über EMA200, H1 über EMA50 mit positiver Steigung"]
        }

    if h4_down and d1_down and h1_down:
        return {
            "bias": "DOWN",
            "reasons": ["H4 ADX/-DI bärisch, D1 unter EMA200, H1 unter EMA50 mit negativer Steigung"]
        }

    return {
        "bias": "NEUTRAL",
        "reasons": [f"Mischlage (H4_up={h4_up}, D1_up={d1_up}, H1_up={h1_up})"]
    }
