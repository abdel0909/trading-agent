# --- NEU/ERSATZ in agent.py -------------------------------------------------
from __future__ import annotations
import time
from typing import Iterable

REQUIRED_COLS = ["Close", "EMA_50", "ADX_14", "DMP_14", "DMN_14"]

def _have_cols(df: pd.DataFrame, cols: Iterable[str]) -> list[str]:
    """Gibt eine Liste fehlender Spalten zurück (leer = alles ok)."""
    return [c for c in cols if c not in df.columns]

def _safe_add_indicators(df: pd.DataFrame, p: dict) -> pd.DataFrame:
    """
    Ruft add_indicators(...) auf und sorgt dafür, dass fehlende Spalten
    wenigstens existieren (mit NaN), damit Downstream-Code stabil bleibt.
    """
    out = add_indicators(
        df.copy(),
        ema_fast=p["ema_fast"], ema_slow=p["ema_slow"],
        rsi_len=p["rsi_len"], adx_len=p["adx_len"], atr_len=p["atr_len"],
        psar_af=p["psar"]["af"], psar_max_af=p["psar"]["max_af"]
    )
    # Spalten ggf. anlegen
    for c in REQUIRED_COLS:
        if c not in out.columns:
            out[c] = pd.NA
    return out

def _load_yf_with_retry(symbol: str, interval: str, period: str, tries: int = 3, wait: float = 3.0) -> pd.DataFrame:
    """
    Wrapper um load_yf() mit kleinen Retries, falls YF drosselt (RateLimit).
    """
    last_exc = None
    for i in range(tries):
        try:
            return load_yf(symbol, interval=interval, period=period)
        except Exception as e:
            last_exc = e
            time.sleep(wait)
    # letzter Versuch – Exception hochreichen
    raise last_exc

def analyze_symbol(symbol: str, tz: str, cfg: dict, logger) -> dict:
    """
    Vollständige Analyse inkl. robusten Checks:
    - Daten via YF mit Retries laden
    - Indikatoren hinzufügen (fehlende Spalten werden als NaN ergänzt)
    - Vor Regime/Strategie prüfen, ob Pflichtspalten vorhanden + nicht-leer
    - Wenn etwas fehlt => 'NEUTRAL' + Begründung statt Crash
    """
    p = cfg["params"]
    out_dir = cfg["out_dir"]
    reasons = []

    # 15m Daten holen
    try:
        df15 = _load_yf_with_retry(symbol, interval="15m", period="60d")
    except Exception as e:
        # Kein Abbruch – wir schicken einen sauberen Report
        reasons.append(f"Download 15m fehlgeschlagen: {type(e).__name__}: {e}")
        df15 = pd.DataFrame(columns=["Close"])
    # Indikatoren M15
    df15 = _safe_add_indicators(df15, p).dropna(how="all")

    # H1/H4 aus 15m resamplen (auch wenn df15 dünn ist)
    h1 = resample_ohlc(df15, "1H")
    h4 = resample_ohlc(df15, "4H")
    h1 = _safe_add_indicators(h1, p).dropna(how="all")
    h4 = _safe_add_indicators(h4, p).dropna(how="all")

    # D1 separat (robust + Retries)
    try:
        d1 = _load_yf_with_retry(symbol, interval="1d", period="6mo")
    except Exception as e:
        reasons.append(f"Download D1 fehlgeschlagen: {type(e).__name__}: {e}")
        d1 = pd.DataFrame(columns=["Close"])
    d1 = _safe_add_indicators(d1, p).dropna(how="all")

    # Pflichtspalten-Check (nur ob vorhanden + nicht komplett leer)
    def _missing_or_all_nan(df: pd.DataFrame, label: str) -> list[str]:
        miss = _have_cols(df, REQUIRED_COLS)
        probs = []
        if miss:
            probs += [f"{label}: fehlt {', '.join(miss)}"]
        else:
            # sind sie komplett leer?
            empty = [c for c in REQUIRED_COLS if df[c].dropna().empty]
            if empty:
                probs += [f"{label}: leer {', '.join(empty)}"]
        return probs

    reasons += _missing_or_all_nan(d1, "D1")
    reasons += _missing_or_all_nan(h4, "H4")
    reasons += _missing_or_all_nan(h1, "H1")

    # Falls irgendwas Grundlegendes fehlt → neutraler Regime-Ausgang
    if reasons:
        regime = {"bias": "NEUTRAL", "reasons": reasons}
        trade = {"action": "WAIT", "entry": None, "sl": None, "tp": None,
                 "note": "Indikatoren/Daten unvollständig – später erneut versuchen."}
        # Chart nur zeichnen, wenn wir M15 wenigstens mit Close haben
        chart_path = plot_m15(df15, symbol, tz, out_dir=out_dir) if not df15.empty else None

        last_close = float(df15["Close"].dropna().iloc[-1]) if "Close" in df15.columns and not df15["Close"].dropna().empty else float("nan")
        last_dt    = (df15.index[-1].astimezone(ZoneInfo(tz)) if not df15.empty else now_tz(tz))
        html = build_html(symbol, tz, last_close, last_dt, regime, trade)
        return {"symbol": symbol, "html": html, "chart_path": chart_path}

    # Regime (sichere Version) + Strategie
    regime = regime_signal_safe(d1, h4, h1)

    strat = WilderStrategy(cfg)
    trade = strat.signal(df15, regime["bias"])

    # Chart
    chart_path = plot_m15(df15, symbol, tz, out_dir=out_dir)

    last_close = float(df15["Close"].iloc[-1]) if "Close" in df15.columns and not df15["Close"].empty else float("nan")
    last_dt    = df15.index[-1].astimezone(ZoneInfo(tz)) if not df15.empty else now_tz(tz)
    html = build_html(symbol, tz, last_close, last_dt, regime, trade)
    return {"symbol": symbol, "html": html, "chart_path": chart_path}
# --- ENDE NEU ---------------------------------------------------------------
