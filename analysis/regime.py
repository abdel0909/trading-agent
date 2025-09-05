# analysis/regime.py
from __future__ import annotations

from typing import Dict, List, Optional, Tuple
import pandas as pd
import numpy as np


# ------------------------------------------------------------
# Hilfen
# ------------------------------------------------------------
def _last(df: pd.DataFrame, col: str, label: Optional[str] = None):
    """
    Sicheres Last: gibt den letzten Wert einer Spalte zurück
    (oder None, falls Spalte fehlt / leer / NaN).
    """
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return None
    if col not in df.columns:
        return None
    v = df[col].iloc[-1]
    if pd.isna(v):
        return None
    return v


def _has_cols(df: pd.DataFrame, cols: List[str]) -> bool:
    if df is None or not isinstance(df, pd.DataFrame) or df.empty:
        return False
    return all(c in df.columns for c in cols)


def _nan_or_none(*vals) -> bool:
    for v in vals:
        if v is None:
            return True
        if isinstance(v, (float, int)) and pd.isna(v):
            return True
    return False


# ------------------------------------------------------------
# Kern: Regime-Ermittlung
# ------------------------------------------------------------
def regime_signal(d1: pd.DataFrame, h4: pd.DataFrame, h1: pd.DataFrame) -> Dict[str, object]:
    """
    Liefert Markt-Bias (UP/DOWN/NEUTRAL) + Gründe (Liste).
    Erwartete Spalten (wenn vorhanden):
      - Close, EMA200 auf D1
      - ADX, +DI, -DI auf H4
      - EMA50 auf H1 (zur groben Steigung)
    Funktion ist robust: Fehlen Spalten/Werte -> NEUTRAL mit Begründung.
    """
    reasons: List[str] = []

    # --- D1: Trendfilter via EMA200
    need_d1 = ["Close", "EMA200"]
    if not _has_cols(d1, need_d1):
        return {"bias": "NEUTRAL", "reasons": ["D1: benötigte Spalten fehlen (Close/EMA200)."]}

    d1_close = _last(d1, "Close")
    d1_ema200 = _last(d1, "EMA200")

    if _nan_or_none(d1_close, d1_ema200):
        return {"bias": "NEUTRAL", "reasons": ["D1: Close/EMA200 nicht verfügbar (NaN/None)."]}

    d1_up = d1_close > d1_ema200
    d1_dn = d1_close < d1_ema200
    reasons.append(f"D1 {'über' if d1_up else 'unter' if d1_dn else 'nahe'} EMA200")

    # --- H4: Momentum via ADX & DMI
    # Erlaube unterschiedliche Spaltennamen (manche Libs nennen sie ADX_14, DMP_14/DMN_14).
    adx_col = next((c for c in ["ADX", "ADX_14", "ADX14"] if c in h4.columns), None)
    pdi_col = next((c for c in ["+DI", "DMP_14", "PLUS_DI", "PDI"] if c in h4.columns), None)
    ndi_col = next((c for c in ["-DI", "DMN_14", "MINUS_DI", "NDI"] if c in h4.columns), None)

    if not all([adx_col, pdi_col, ndi_col]):
        return {"bias": "NEUTRAL", "reasons": ["H4: ADX/+DI/-DI Spalten fehlen."]}

    h4_adx = _last(h4, adx_col)
    h4_pdi = _last(h4, pdi_col)
    h4_ndi = _last(h4, ndi_col)

    if _nan_or_none(h4_adx, h4_pdi, h4_ndi):
        return {"bias": "NEUTRAL", "reasons": ["H4: ADX/DMI nicht verfügbar (NaN/None)."]}

    # Richtungs-Signal auf H4:
    h4_up = (h4_pdi > h4_ndi) and (h4_adx is not None)
    h4_dn = (h4_ndi > h4_pdi) and (h4_adx is not None)
    reasons.append(f"H4 DMI: {'bullisch' if h4_up else 'bärisch' if h4_dn else 'uneindeutig'} (ADX={h4_adx:.1f})")

    # --- H1: EMA50 Steigung (grobe Tendenz)
    if "EMA50" not in h1.columns:
        return {"bias": "NEUTRAL", "reasons": ["H1: EMA50 fehlt."]}

    # Regressions-Steigung auf die letzten N Punkte der EMA50
    lookback = min(50, len(h1))
    if lookback < 5:
        return {"bias": "NEUTRAL", "reasons": ["H1: zu wenig Daten für EMA50-Steigung."]}

    ema50 = h1["EMA50"].tail(lookback).to_numpy(dtype=float)
    if np.isnan(ema50).all():
        return {"bias": "NEUTRAL", "reasons": ["H1: EMA50 komplett NaN."]}

    x = np.arange(len(ema50), dtype=float)
    # robust gegen NaNs
    mask = ~np.isnan(ema50)
    if mask.sum() < 3:
        return {"bias": "NEUTRAL", "reasons": ["H1: zu wenige gültige EMA50-Werte."]}

    slope = np.polyfit(x[mask], ema50[mask], 1)[0]
    h1_up = slope > 0
    h1_dn = slope < 0
    reasons.append(f"H1 EMA50-Slope: {'steigend' if h1_up else 'fallend' if h1_dn else 'flach'}")

    # --- Entscheidung (Kombination)
    if d1_up and h4_up and h1_up:
        return {"bias": "UP", "reasons": reasons}

    if (not d1_up) and h4_dn and h1_dn:
        return {"bias": "DOWN", "reasons": reasons}

    return {"bias": "NEUTRAL", "reasons": reasons}


# ------------------------------------------------------------
# Safe-Wrapper: bricht nicht hart, sondern liefert NEUTRAL
# ------------------------------------------------------------
def regime_signal_safe(d1: pd.DataFrame, h4: pd.DataFrame, h1: pd.DataFrame) -> Dict[str, object]:
    """
    Sichere Version: fängt alle Fehler intern ab und liefert NEUTRAL + Grund.
    (WICHTIG: Diese Funktion darf KEINEN Einrückungs-/Leer-Body haben!)
    """
    try:
        return regime_signal(d1, h4, h1)
    except Exception as e:
        return {"bias": "NEUTRAL", "reasons": [f"Regime-Fehler: {e}"]}
