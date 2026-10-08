"""Replay real history through the EXISTING deterministic engine and collect
every signal it emits, bar by bar, with no lookahead.

At each M5 bar i, the engine sees only candles that were closed by the bar's
close time (the same closed-candle rule the live snapshot uses), then we record
what it reported. No signal logic lives here: this measures analysis/*.py as
it is. Labeling happens afterwards in backtest/outcome.py.

Signal definitions are frozen for the baseline (see docs/backtest/METHODOLOGY.md).
"""
from dataclasses import dataclass
from datetime import timedelta
from typing import Dict, List, Optional

import pandas as pd

from analysis.liquidity import detect_sweeps
from analysis.regime import classify_regime
from analysis.setup import detect_setup
from analysis.structure import analyze_structure, compute_atr, displacement_at
from analysis.zones import compute_zones
from mt5.market_data import _with_candle_state
from backtest.outcome import label_signal

WINDOW = 300
TF_MINUTES = {"M5": 5, "M15": 15, "H1": 60, "H4": 240}
WARMUP = 60
SIGNAL_TYPES = ("BOS", "MSS", "SWEEP", "DISPLACEMENT", "SETUP_VALID")


@dataclass(frozen=True)
class Signal:
    index: int
    time: pd.Timestamp
    signal_type: str
    direction: str  # BUY or SELL
    outcome: str  # win / loss / timeout
    session: str
    timeframe: str  # M5 or H1 (BOS and MSS are evaluated on both)
    regime: str  # analysis/regime.py label at signal time


def _closed_window(df: pd.DataFrame, tf: str, now: pd.Timestamp) -> pd.DataFrame:
    """The last WINDOW candles that were closed at `now`, with candle state attached."""
    closed_by = now - timedelta(minutes=TF_MINUTES[tf])
    sub = df[df["time"] <= closed_by].tail(WINDOW).reset_index(drop=True)
    return _with_candle_state(sub, tf, now.to_pydatetime())


def _session(t: pd.Timestamp) -> str:
    h = t.hour
    if 0 <= h < 7:
        return "ASIAN"
    if 7 <= h < 12:
        return "LONDON"
    if 12 <= h < 20:
        return "NY"
    return "OFF"


def replay(frames: Dict[str, pd.DataFrame], start: int = 0, end: Optional[int] = None,
           stride: int = 1, horizon: int = 48, k: float = 1.0) -> List[Signal]:
    """frames: {"M5","M15","H1","H4"} -> oldest-first DataFrames of raw bars."""
    m5 = frames["M5"].reset_index(drop=True)
    atr = compute_atr(m5)
    end = len(m5) if end is None else min(end, len(m5))
    signals: List[Signal] = []

    prev_bos: Dict[str, Optional[str]] = {}
    prev_mss: Dict[str, Optional[str]] = {}
    prev_setup_state: Optional[str] = None

    for i in range(max(start, WINDOW), end, stride):
        t = m5["time"].iloc[i]
        now = t + timedelta(minutes=TF_MINUTES["M5"])
        windows = {tf: _closed_window(frames[tf], tf, now) for tf in ("M5", "M15", "H1", "H4")}
        m5_closed = windows["M5"]

        found: List[tuple] = []  # (signal_type, direction, timeframe)

        for tf in ("M5", "H1"):
            res = analyze_structure(windows[tf])
            if prev_bos.get(tf) != res.last_bos and res.last_bos is not None:
                found.append(("BOS", "BUY" if res.last_bos == "bullish" else "SELL", tf))
            if prev_mss.get(tf) != res.last_mss and res.last_mss is not None:
                found.append(("MSS", "BUY" if res.last_mss == "bullish" else "SELL", tf))
            prev_bos[tf], prev_mss[tf] = res.last_bos, res.last_mss

        zones = compute_zones(m5_closed, windows["H1"], windows["H4"])
        for ev in detect_sweeps(m5_closed, zones):
            if pd.Timestamp(ev.time) == pd.Timestamp(t):
                found.append(("SWEEP", "BUY" if ev.kind == "sweep_low" else "SELL", "M5"))

        disp = displacement_at(m5_closed, len(m5_closed) - 1)
        if disp is not None:
            found.append(("DISPLACEMENT", "BUY" if disp == "bullish" else "SELL", "M5"))

        setup = detect_setup(windows, now=now.to_pydatetime())
        if setup.state == "VALID" and prev_setup_state != "VALID" and setup.direction in ("BUY", "SELL"):
            found.append(("SETUP_VALID", setup.direction, "M5"))
        prev_setup_state = setup.state

        bar_atr = float(atr.iloc[i]) if not pd.isna(atr.iloc[i]) else None
        if bar_atr is None or bar_atr <= 0 or not found:
            continue
        regime = classify_regime(windows["H1"], windows["M15"]).regime
        for signal_type, direction, tf in found:
            labeled = label_signal(m5, i, direction, bar_atr, horizon=horizon, k=k)
            signals.append(Signal(i, pd.Timestamp(t), signal_type, direction, labeled.outcome,
                                  _session(pd.Timestamp(t)), tf, regime))

    return signals
