# test_regime.py
import pandas as pd
import numpy as np
from analysis.regime import regime_signal

# Dummy-Daten erzeugen (200 Stunden)
idx = pd.date_range("2024-01-01", periods=200, freq="H")

def make_df():
    df = pd.DataFrame(index=idx)
    df["Close"] = 1 + np.sin(np.linspace(0, 10, len(idx)))
    df["EMA_50"] = df["Close"].ewm(span=50, adjust=False).mean()
    df["ADX_14"] = 20 + 5*np.sin(np.linspace(0, 3, len(idx)))
    df["DMP_14"] = 25 + 5*np.sin(np.linspace(0, 2, len(idx)))
    df["DMN_14"] = 20 + 5*np.cos(np.linspace(0, 2, len(idx)))
    return df

d1, h4, h1 = make_df(), make_df(), make_df()
print(regime_signal(d1, h4, h1))
