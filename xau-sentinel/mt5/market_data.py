"""Market data retrieval.

MODE=live  -> reads real candles/ticks from the connected MT5 terminal.
MODE=mock  -> generates deterministic synthetic data so the app is fully
              usable without MT5. Mock data is never presented as live data;
              callers get it back tagged with source="mock".
"""
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

import config
from mt5 import connection

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None

TIMEFRAMES = ["M5", "M15", "H1", "H4"]

_MT5_TIMEFRAME_ATTR = {
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
}

_TIMEFRAME_MINUTES = {"M5": 5, "M15": 15, "H1": 60, "H4": 240}


class MarketDataError(Exception):
    """Raised when live market data cannot be retrieved. Callers should show a
    disconnected state rather than let this propagate into a crash."""


def get_candles(timeframe: str, count: int = 300) -> pd.DataFrame:
    """Returns columns [time, open, high, low, close, volume], oldest first, time in UTC."""
    if timeframe not in _TIMEFRAME_MINUTES:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    if config.IS_MOCK:
        return _mock_candles(timeframe, count)

    if mt5 is None or not connection.is_connected():
        raise MarketDataError("MT5 not connected")

    mt5_tf = getattr(mt5, _MT5_TIMEFRAME_ATTR[timeframe])
    rates = mt5.copy_rates_from_pos(config.TRADING_SYMBOL, mt5_tf, 0, count)
    if rates is None or len(rates) == 0:
        raise MarketDataError(f"No candle data returned for {timeframe}")

    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
    df = df.rename(columns={"tick_volume": "volume"})
    return df[["time", "open", "high", "low", "close", "volume"]]


def get_price_info() -> dict:
    """Returns dict: price, bid, ask, spread, time (UTC datetime), source ("live"/"mock")."""
    if config.IS_MOCK:
        return _mock_price_info()

    if mt5 is None or not connection.is_connected():
        raise MarketDataError("MT5 not connected")

    tick = mt5.symbol_info_tick(config.TRADING_SYMBOL)
    if tick is None:
        raise MarketDataError("No tick data available")

    spread = round(tick.ask - tick.bid, 2)
    return {
        "price": tick.last if tick.last else tick.bid,
        "bid": tick.bid,
        "ask": tick.ask,
        "spread": spread,
        "time": datetime.fromtimestamp(tick.time, tz=timezone.utc),
        "source": "live",
    }


def get_all_candles(count: int = 300) -> dict:
    """Convenience helper: fetches all four timeframes at once."""
    return {tf: get_candles(tf, count) for tf in TIMEFRAMES}


# ---------------------------------------------------------------------------
# Mock data — deterministic per timeframe so the UI doesn't jitter randomly
# between reruns, but still varies enough to look like a real market.
# ---------------------------------------------------------------------------

_MOCK_BASE_PRICE = 3742.50


def _mock_seed(timeframe: str) -> int:
    return abs(hash((timeframe, "xau-sentinel-mock"))) % (2**32)


def _mock_candles(timeframe: str, count: int) -> pd.DataFrame:
    minutes = _TIMEFRAME_MINUTES[timeframe]
    rng = np.random.default_rng(_mock_seed(timeframe))

    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    aligned = now - timedelta(minutes=now.minute % minutes)
    times = [aligned - timedelta(minutes=minutes * i) for i in range(count)][::-1]

    steps = rng.normal(loc=0.0, scale=0.9, size=count)
    drift = np.sin(np.linspace(0, 6, count)) * 3.0
    closes = _MOCK_BASE_PRICE + np.cumsum(steps) * 0.4 + drift

    opens = np.roll(closes, 1)
    opens[0] = closes[0] - steps[0] * 0.4
    wick_up = rng.uniform(0.2, 1.5, size=count)
    wick_dn = rng.uniform(0.2, 1.5, size=count)
    highs = np.maximum(opens, closes) + wick_up
    lows = np.minimum(opens, closes) - wick_dn
    volumes = rng.integers(50, 500, size=count)

    df = pd.DataFrame({
        "time": pd.to_datetime(times, utc=True),
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })
    return df


def _mock_price_info() -> dict:
    m5 = _mock_candles("M5", 2)
    last = m5.iloc[-1]
    spread = 0.35
    close = float(last["close"])
    return {
        "price": round(close, 2),
        "bid": round(close - spread / 2, 2),
        "ask": round(close + spread / 2, 2),
        "spread": spread,
        "time": last["time"].to_pydatetime(),
        "source": "mock",
    }
