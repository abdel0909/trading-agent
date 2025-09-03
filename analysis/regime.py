from __future__ import annotations
from typing import Dict
from .indicators import ema_slope
import pandas as pd

def regime_signal(d1: pd.DataFrame, h4: pd.DataFrame, h1: pd.DataFrame,
                  adx_min=20, ema50_slope_lookback=5) -> Dict:
    def last(d, col): return d[col].iloc[-1]

    h4_up   = (last(h4, "ADX") > adx_min) and (last(h4, "+DI") > last(h4, "-DI"))
    h4_down = (last(h4, "ADX") > adx_min) and (last(h4, "-DI") > last(h4, "+DI"))

    d1_up   = last(d1, "Close") > last(d1, "EMA200")
    d1_down = last(d1, "Close") < last(d1, "EMA200")

    slope = ema_slope(h1["EMA50"], lookback=ema50_slope_lookback)
    h1_up   = (last(h1, "Close") > last(h1, "EMA50")) and (slope > 0)
    h1_down = (last(h1, "Close") < last(h1, "EMA50")) and (slope < 0)

    reasons = []
    bias = "NEUTRAL"
    if h4_up and d1_up and h1_up:
        bias = "UP"; reasons.append("H4 ADX/+DI bullisch, D1 über EMA200, H1 über EMA50 mit positiver Steigung")
    elif h4_down and d1_down and h1_down:
        bias = "DOWN"; reasons.append("H4 ADX/-DI bärisch, D1 unter EMA200, H1 unter EMA50 mit negativer Steigung")
    else:
        reasons.append(f"Mischlage (H4_up={h4_up}, D1_up={d1_up}, H1_up={h1_up})")

    return {"bias": bias, "reasons": reasons}
