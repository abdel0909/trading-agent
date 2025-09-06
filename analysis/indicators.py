# analysis/indicators.py
from __future__ import annotations

from typing import Optional
import numpy as np
import pandas as pd
import pandas_ta as ta


def _pick_column(df: pd.DataFrame, *candidates: str) -> pd.Series:
    """Nimmt die erste passende Spalte – tolerant ggü. leicht anderen Namen."""
    if df is None or df.empty:
        return pd.Series(np.nan, index=pd.RangeIndex(0))
    # 1) exakter Treffer
    for c in candidates:
        if c in df.columns:
            return df[c]
    # 2) fuzzy: startswith / enthält
    upcols = {c.upper(): c for c in df.columns}
    for want in candidates:
        w = want.upper().replace("+", "P").replace("-", "M")
        for up, real in upcols.items():
            if w in up or up.startswith(w):
                return df[real]
    # 3) Fallback: erste Spalte
    return df[df.columns[0]]


def _normalize_adx(adx_df: pd.DataFrame) -> pd.DataFrame:
    """Bringt ADX/DMP/DMM auf ein einheitliches Schema."""
    out = pd.DataFrame(index=adx_df.index)

    # ADX
    out["ADX"] = _pick_column(
        adx_df, "ADX_14", "ADX14", "ADX"
    )

    # +DI (DMP)
    out["DMP"] = _pick_column(
        adx_df, "DMP_14", "DMP14", "DM+_14", "PLUS_DI_14", "PDI_14", "PDI"
    )

    # -DI (DMM)
    out["DMM"] = _pick_column(
        adx_df, "DMM_14", "DMM14", "DM-_14", "MINUS_DI_14", "MDI_14", "MDI"
    )

    return out


def add_indicators(
    df: pd.DataFrame,
    adx_len: int = 14,
    rsi_len: int = 14,
    ema_len: int = 50,
    psar: bool = False,
) -> pd.DataFrame:
    """
    Fügt (robust) Wilder-Indikatoren hinzu:
      - ADX/DMI  -> Spalten: ADX, DMP, DMM
      - RSI      -> Spalte:  RSI
      - EMA      -> Spalte:  EMA_{ema_len}
      - PSAR     -> optional Spalte: PSAR
    Fällt bei Datenproblemen auf NaN zurück (kein Traceback).
    """
    if df is None or df.empty:
        return df

    need = {"Close", "High", "Low"}
    if not need.issubset(df.columns):
        # Nichts kaputt machen, aber sauber zurückgeben
        return df.copy()

    df = df.copy()

    # --- ADX/DMI ---
    try:
        adx_raw = ta.adx(
            high=df["High"], low=df["Low"], close=df["Close"], length=adx_len
        )
        if adx_raw is not None and not adx_raw.empty:
            adx_norm = _normalize_adx(adx_raw)
            for c in ["ADX", "DMP", "DMM"]:
                df[c] = pd.to_numeric(adx_norm[c], errors="coerce")
        else:
            df[["ADX", "DMP", "DMM"]] = np.nan
    except Exception:
        df[["ADX", "DMP", "DMM"]] = np.nan

    # --- RSI ---
    try:
        df["RSI"] = pd.to_numeric(ta.rsi(df["Close"], length=rsi_len), errors="coerce")
    except Exception:
        df["RSI"] = np.nan

    # --- EMA ---
    ema_col = f"EMA_{ema_len}"
    try:
        df[ema_col] = pd.to_numeric(ta.ema(df["Close"], length=ema_len), errors="coerce")
    except Exception:
        df[ema_col] = np.nan

    # --- PSAR (optional) ---
    if psar:
        try:
            psar_df = ta.psar(high=df["High"], low=df["Low"], close=df["Close"])
            if psar_df is not None and not psar_df.empty:
                # nimm irgendeine „PSAR*“-Spalte (bull/bear Variants je nach Version)
                col = next((c for c in psar_df.columns if "PSAR" in c.upper()), psar_df.columns[-1])
                df["PSAR"] = pd.to_numeric(psar_df[col], errors="coerce")
            else:
                df["PSAR"] = np.nan
        except Exception:
            df["PSAR"] = np.nan

    return df
