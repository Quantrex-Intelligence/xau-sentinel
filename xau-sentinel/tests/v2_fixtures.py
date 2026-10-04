"""Shared synthetic-market builders for the Analysis Engine V2 tests.

Built on the same zig-zag helpers the structure tests use, so the expected swings
and structure are already known. Every frame comes from make_candles(), so the
closed flag follows the same rule as production data.
"""
import pandas as pd

from tests.conftest import make_candles
from tests.test_structure import BEARISH_POINTS, BULLISH_POINTS, _ramp_path

UP_TAIL = [124, 120, 116, 113]  # confirms the final swing high 128 and keeps HL 112 intact
DOWN_TAIL = [76, 80, 84, 87]  # confirms the final swing low 72 and keeps LH 88 intact


def path_candles(points, steps, tf_minutes, tail=None):
    path = _ramp_path(points, steps)
    rows = [(v, v, v, v) for v in path + list(tail or [])]
    return make_candles(rows, tf_minutes=tf_minutes)


def trend_set(direction="up"):
    """M5/M15/H1/H4 frames that all show the same clean trend."""
    points, tail = (BULLISH_POINTS, UP_TAIL) if direction == "up" else (BEARISH_POINTS, DOWN_TAIL)
    return {
        "M5": path_candles(points, 24, 5, tail),
        "M15": path_candles(points, 12, 15, tail),
        "H1": path_candles(points, 14, 60, tail),
        "H4": path_candles(points, 10, 240, tail),
    }


def range_set():
    """Flat oscillation so no trend is established on any timeframe."""
    rows = []
    for i in range(2000):
        base = 100.0 + (0.4 if i % 2 else -0.4)
        rows.append((base, base + 0.3, base - 0.3, base + (0.1 if i % 3 else -0.1)))
    frame = make_candles(rows, tf_minutes=5)
    return {"M5": frame, "M15": make_candles(rows[::3], tf_minutes=15),
            "H1": make_candles(rows[::12], tf_minutes=60), "H4": make_candles(rows[::48], tf_minutes=240)}


def with_forming_bar(candles, tf="M5", close=None):
    """Append one still-forming bar with extreme values to `tf`. A correct engine
    must ignore it completely."""
    df = candles[tf]
    last = df.iloc[-1]
    price = float(close if close is not None else last["close"]) + 500.0
    row = df.iloc[[-1]].copy()
    row["open"] = row["high"] = row["low"] = row["close"] = price
    row["time"] = last["time"] + (last["close_time"] - last["time"])
    row["close_time"] = row["time"] + (last["close_time"] - last["time"])
    row["is_closed"] = False
    out = dict(candles)
    out[tf] = pd.concat([df, row], ignore_index=True)
    return out
