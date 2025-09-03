from __future__ import annotations
import pandas as pd
import yfinance as yf

def load_yf(symbol: str, interval: str, period: str) -> pd.DataFrame:
    df = yf.download(symbol, interval=interval, period=period, auto_adjust=False, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df = df.rename(columns=str.title)  # Open, High, Low, Close, Volume
    return df.dropna()

def resample_ohlc(df_15m: pd.DataFrame, rule: str) -> pd.DataFrame:
    agg = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}
    return df_15m.resample(rule, label="right", closed="right").agg(agg).dropna()
