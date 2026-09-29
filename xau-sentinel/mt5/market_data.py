"""Market data retrieval.

MODE=live  -> reads real candles/ticks from the connected MT5 terminal.
MODE=mock  -> generates deterministic synthetic data so the app is fully
              usable without MT5. Mock data is never presented as live data;
              callers get it back tagged with source="mock".
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

import config
from mt5 import connection, timeutil
from stable_seed import stable_seed

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


def _no_data_error(what: str) -> MarketDataError:
    """VAL-028: connection.connect() reports success once the terminal is up,
    even when the configured symbol isn't available from this broker (that's
    recorded separately as symbol_ready()/last_error()). Without this, the
    only visible symptom was a generic "no candle data" error; now the real
    cause reaches the user whenever it's known."""
    if not connection.symbol_ready() and connection.last_error():
        return MarketDataError(f"{what}: {connection.last_error()}")
    return MarketDataError(what)


def _with_candle_state(df: pd.DataFrame, timeframe: str, now: Optional[datetime] = None) -> pd.DataFrame:
    """Adds close_time (this candle's open `time` + the timeframe's own
    duration) and is_closed (close_time <= the authoritative current
    time, boundary inclusive) columns. A candle's state is always derived
    from its own timestamp against `now` -- never assumed from row
    position or count (see docs/validation/ISSUE_LOG.md VAL-006).
    Structural analysis must filter to is_closed candles (see
    analysis.structure.closed_only()); "current price" reads (entry
    planning, live display, charting) may use the full, unfiltered set."""
    now = now or datetime.now(timezone.utc)
    minutes = _TIMEFRAME_MINUTES[timeframe]
    df = df.copy()
    df["close_time"] = df["time"] + pd.Timedelta(minutes=minutes)
    df["is_closed"] = df["close_time"] <= now
    return df


def get_candles(timeframe: str, count: int = 300) -> pd.DataFrame:
    """Returns columns [time, open, high, low, close, volume, close_time,
    is_closed], oldest first, all times in UTC."""
    if timeframe not in _TIMEFRAME_MINUTES:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    if config.IS_MOCK:
        return _mock_candles(timeframe, count)

    if mt5 is None or not connection.is_connected():
        raise MarketDataError("MT5 not connected")

    mt5_tf = getattr(mt5, _MT5_TIMEFRAME_ATTR[timeframe])
    rates = mt5.copy_rates_from_pos(config.TRADING_SYMBOL, mt5_tf, 0, count)
    if rates is None or len(rates) == 0:
        raise _no_data_error(f"No candle data returned for {timeframe}")

    df = pd.DataFrame(rates)
    df["time"] = timeutil.series_to_utc(df["time"])
    df = df.rename(columns={"tick_volume": "volume"})
    df = _with_candle_state(df, timeframe)
    return df[["time", "open", "high", "low", "close", "volume", "close_time", "is_closed"]]


def get_price_info() -> dict:
    """Returns dict: price, bid, ask, spread, time (UTC datetime), source ("live"/"mock")."""
    if config.IS_MOCK:
        return _mock_price_info()

    if mt5 is None or not connection.is_connected():
        raise MarketDataError("MT5 not connected")

    tick = mt5.symbol_info_tick(config.TRADING_SYMBOL)
    if tick is None:
        raise _no_data_error("No tick data available")

    spread = round(tick.ask - tick.bid, 2)
    return {
        "price": tick.last if tick.last else tick.bid,
        "bid": tick.bid,
        "ask": tick.ask,
        "spread": spread,
        "time": timeutil.to_utc(tick.time),
        "source": "live",
    }


def get_all_candles(count: int = 300) -> dict:
    """Convenience helper: fetches all four timeframes at once."""
    return {tf: get_candles(tf, count) for tf in TIMEFRAMES}


def is_stale(price_info: dict, now: datetime = None) -> bool:
    """True if the last known tick is older than config.DATA_STALE_SECONDS.
    Mock mode is exempt: its candle timestamps are bar-aligned (floored to
    the timeframe boundary), so they can legitimately sit a few minutes
    behind "now" with no real feed having stopped — there's nothing to go
    stale. This only ever fires for a live feed that has actually stopped
    updating."""
    if config.IS_MOCK:
        return False
    if not price_info or price_info.get("time") is None:
        return False
    now = now or datetime.now(timezone.utc)
    age = (now - price_info["time"]).total_seconds()
    return age > config.DATA_STALE_SECONDS


# ---------------------------------------------------------------------------
# Mock data — deterministic per timeframe so the UI doesn't jitter randomly
# between reruns, but still varies enough to look like a real market.
# ---------------------------------------------------------------------------

_MOCK_BASE_PRICE = 3742.50


def _mock_seed(timeframe: str) -> int:
    return stable_seed(timeframe, "xau-sentinel-mock")


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
    # Same `now` already used for bar alignment above -- the mock series
    # stays a fully deterministic function of that one timestamp. The last
    # row's close_time is always aligned-bar-start + one full duration,
    # strictly after `now`, so it is always (correctly) forming.
    return _with_candle_state(df, timeframe, now=now)


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
