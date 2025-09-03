from __future__ import annotations
from typing import Dict
import pandas as pd
from analysis.indicators import add_indicators
from analysis.regime import regime_signal
from analysis.signals import entry_exit_on_m15

class WilderStrategy:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.p   = cfg["params"]
        self.r   = cfg["rules"]

    def add_indics(self, df: pd.DataFrame) -> pd.DataFrame:
        return add_indicators(
            df,
            ema_fast=self.p["ema_fast"], ema_slow=self.p["ema_slow"],
            rsi_len=self.p["rsi_len"], adx_len=self.p["adx_len"],
            atr_len=self.p["atr_len"], psar_af=self.p["psar"]["af"], psar_max_af=self.p["psar"]["max_af"]
        )

    def regime(self, d1: pd.DataFrame, h4: pd.DataFrame, h1: pd.DataFrame) -> Dict:
        return regime_signal(d1, h4, h1,
                             adx_min=self.r["adx_min"],
                             ema50_slope_lookback=self.r["ema50_slope_lookback"])

    def signal(self, m15: pd.DataFrame, bias: str) -> Dict:
        return entry_exit_on_m15(m15, bias,
                                 pullback_atr_frac=self.r["pullback_atr_frac"],
                                 sl_atr_mult=self.r["sl_atr_mult"],
                                 tp_atr_mult=self.r["tp_atr_mult"])
