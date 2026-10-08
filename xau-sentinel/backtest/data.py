"""Fetch real MT5 history for offline evaluation and cache it to CSV.

Used only by the backtest harness. Timestamps go through mt5/timeutil.py,
the same broker-time -> UTC boundary the live path uses, so a backtest sees
candles exactly as the engine would have seen them live.
"""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

import config
from mt5 import timeutil

CACHE_DIR = Path(__file__).parent / "data"
TIMEFRAME_ATTR = {"M5": "TIMEFRAME_M5", "M15": "TIMEFRAME_M15", "H1": "TIMEFRAME_H1", "H4": "TIMEFRAME_H4"}


def _cache_path(timeframe: str, months: int) -> Path:
    return CACHE_DIR / f"{config.TRADING_SYMBOL}_{timeframe}_{months}m.csv"


def load_history(timeframe: str, months: int = 6, refresh: bool = False) -> pd.DataFrame:
    """Oldest-first DataFrame with columns time, open, high, low, close, volume (UTC)."""
    path = _cache_path(timeframe, months)
    if path.exists() and not refresh:
        df = pd.read_csv(path, parse_dates=["time"])
        df["time"] = pd.to_datetime(df["time"], utc=True)
        return df

    import MetaTrader5 as mt5

    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    try:
        end = datetime.now(timezone.utc)
        start = end - timedelta(days=30 * months)
        rates = mt5.copy_rates_range(
            config.TRADING_SYMBOL, getattr(mt5, TIMEFRAME_ATTR[timeframe]), start, end
        )
    finally:
        mt5.shutdown()
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No {timeframe} history returned for {config.TRADING_SYMBOL}")

    df = pd.DataFrame(rates)
    df["time"] = timeutil.series_to_utc(df["time"])
    df = df.rename(columns={"tick_volume": "volume"})[["time", "open", "high", "low", "close", "volume"]]
    df = df.sort_values("time").reset_index(drop=True)

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False)
    return df
