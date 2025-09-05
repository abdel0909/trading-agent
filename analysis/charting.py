# analysis/charting.py
from zoneinfo import ZoneInfo
import os
import matplotlib.pyplot as plt
import pandas as pd

def plot_m15(df: pd.DataFrame, symbol: str, tz: str, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    safe_symbol = symbol.replace("=", "_").replace("/", "_")
    out_path = os.path.join(out_dir, f"{safe_symbol}_M15.png")

    # Zeitpunkt für den Titel robust bestimmen
    ts_str = "n/a"
    try:
        if df is not None and len(df) > 0:
            last_dt = df.iloc[-1].name  # Index-Zeitstempel der letzten Zeile
            if getattr(last_dt, "tzinfo", None) is None:
                last_dt = pd.Timestamp(last_dt, tz="UTC")
            ts_str = last_dt.astimezone(ZoneInfo(tz)).strftime("%Y-%m-%d %H:%M")
    except Exception:
        ts_str = "n/a"

    title = f"{symbol} M15 – {ts_str} ({tz})"

    # Wenn keine Daten: Stub-PNG mit Hinweis erzeugen statt zu crashen
    if df is None or len(df) == 0:
        fig, ax = plt.subplots(figsize=(8, 4))
        ax.axis("off")
        ax.text(
            0.5, 0.6, title, ha="center", va="center", fontsize=12, wrap=True
        )
        ax.text(
            0.5, 0.4,
            "Keine M15-Daten verfügbar (Rate-Limit/Download leer).\n"
            "Bitte später erneut versuchen.",
            ha="center", va="center", fontsize=10, wrap=True
        )
        fig.savefig(out_path, dpi=140, bbox_inches="tight")
        plt.close(fig)
        return out_path

    # … dein bestehendes Plotten hier (candles/lines etc.) …
    # Falls du mpf verwendest, kannst du das hier weiter nutzen.
    # Minimal: einfache Close-Linie, damit es immer funktioniert.
    fig, ax = plt.subplots(figsize=(10, 5))
    df["Close"].plot(ax=ax)
    ax.set_title(title)
    ax.set_xlabel("Zeit")
    ax.set_ylabel("Preis")
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)
    return out_path
