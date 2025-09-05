# analysis/charting.py
from __future__ import annotations
import os
from pathlib import Path
from zoneinfo import ZoneInfo
import matplotlib.pyplot as plt
import pandas as pd

def _ensure_dir(p: str | Path) -> None:
    Path(p).parent.mkdir(parents=True, exist_ok=True)

def _dummy_chart(path: str | Path, title: str, message: str) -> str:
    _ensure_dir(path)
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.axis("off")
    ax.text(0.5, 0.65, title, ha="center", va="center", fontsize=13, wrap=True)
    ax.text(0.5, 0.35, message, ha="center", va="center", fontsize=11, wrap=True)
    fig.tight_layout()
    fig.savefig(path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return str(path)

def plot_m15(df: pd.DataFrame, symbol: str, tz: str, out_dir: str) -> str:
    """Erzeugt immer ein PNG: echte Linie bei Daten, sonst Dummy-Hinweis."""
    safe_symbol = symbol.replace("=", "_").replace("/", "_")
    out_path = os.path.join(out_dir, f"{safe_symbol}_M15.png")
    Path(out_dir).mkdir(parents=True, exist_ok=True)

    # Titelzeitstempel robust ermitteln
    ts_str = "n/a"
    try:
        if df is not None and len(df) > 0:
            last_dt = df.index[-1]
            if getattr(last_dt, "tzinfo", None) is None:
                last_dt = pd.Timestamp(last_dt, tz="UTC")
            ts_str = last_dt.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        ts_str = "n/a"

    title = f"{symbol} – M15 ({ts_str} {tz})"

    # Kein DataFrame / leer → Dummy-PNG
    if df is None or len(df) == 0 or "Close" not in df.columns or df["Close"].dropna().empty:
        return _dummy_chart(out_path, title, "Keine M15-Daten verfügbar (Rate-Limit / leerer Download).")

    # Echte einfache Linie (robust, ohne mplfinance-Abhängigkeit)
    fig, ax = plt.subplots(figsize=(10, 5))
    df["Close"].plot(ax=ax)
    ax.set_title(title)
    ax.set_xlabel("Zeit")
    ax.set_ylabel("Preis")
    fig.tight_layout()
    fig.savefig(out_path, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return out_path
