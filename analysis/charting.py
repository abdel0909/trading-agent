from __future__ import annotations
import os
import mplfinance as mpf
import matplotlib
matplotlib.use("Agg")

def plot_m15(m15, symbol: str, tz: str, out_dir: str) -> str:
    os.makedirs(out_dir, exist_ok=True)
    df = m15.copy().tz_localize(None)

    apds = [
        mpf.make_addplot(df["EMA50"], width=1),
        mpf.make_addplot(df["EMA200"], width=1),
        mpf.make_addplot(df["PSAR"], type='scatter', markersize=10),
    ]

    title = f"{symbol} M15 – {df.index[-1].strftime('%Y-%m-%d %H:%M')} ({tz})"
    save_path = os.path.join(out_dir, f"{symbol.replace('=','_')}_M15.png")

    mpf.plot(
        df.tail(400),
        type='candle',
        style='yahoo',
        title=title,
        addplot=apds,
        volume=True,
        tight_layout=True,
        savefig=save_path
    )
    return save_path
