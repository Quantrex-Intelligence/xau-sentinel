"""Label a signal as a win, loss, or timeout using only bars after it.

Entry is the signal bar's close. For a BUY the target is entry + k*ATR and the
stop is entry - k*ATR; SELL is mirrored. The first level touched decides the
outcome. If one bar touches both levels, the order inside it is unknown, so
it counts as a loss (conservative: never credit a win the data can't prove).
"""
from dataclasses import dataclass
from typing import Literal

import pandas as pd

Outcome = Literal["win", "loss", "timeout"]


@dataclass(frozen=True)
class Labeled:
    index: int
    direction: str
    outcome: Outcome


def label_signal(df: pd.DataFrame, index: int, direction: str, atr: float,
                 horizon: int = 48, k: float = 1.0) -> Labeled:
    """df needs high/low/close columns, oldest first. `index` is the signal bar."""
    entry = float(df["close"].iloc[index])
    move = k * atr
    if direction == "BUY":
        target, stop = entry + move, entry - move
    elif direction == "SELL":
        target, stop = entry - move, entry + move
    else:
        raise ValueError(f"direction must be BUY or SELL, got {direction!r}")

    last = min(index + horizon, len(df) - 1)
    for j in range(index + 1, last + 1):
        high = float(df["high"].iloc[j])
        low = float(df["low"].iloc[j])
        if direction == "BUY":
            hit_target, hit_stop = high >= target, low <= stop
        else:
            hit_target, hit_stop = low <= target, high >= stop
        if hit_target and hit_stop:
            return Labeled(index, direction, "loss")
        if hit_target:
            return Labeled(index, direction, "win")
        if hit_stop:
            return Labeled(index, direction, "loss")
    return Labeled(index, direction, "timeout")
