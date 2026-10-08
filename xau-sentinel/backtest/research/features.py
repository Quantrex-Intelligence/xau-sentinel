"""Research-only feature dataset: one row per M5 bar.

Every f_* column is computed from information available at the bar's close
(closed candles only, the same rule the live engine uses). Every y_* column is
an outcome and looks AHEAD by definition; discovery code must never use a y_*
column as a feature. tests/test_research_features.py checks that f_* columns
do not change when future bars are removed.

Features reuse the existing analysis functions unchanged. Sessions use the
configured UTC windows (config.py), which corrects the hour-6 labelling flaw
in the benchmark; this is recorded in the research report.
"""
from datetime import timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

import config
from analysis.liquidity import detect_sweeps
from analysis.regime import classify_regime
from analysis.structure import analyze_structure, compute_atr, displacement_at
from analysis.zones import compute_zones
from backtest.outcome import label_signal
from backtest.replay import WINDOW, TF_MINUTES, _closed_window

TFS = ("M5", "M15", "H1", "H4")
RECENT_BARS = 12  # "within the last hour" on M5 for sequence features
HORIZONS = (12, 48)


def configured_session(t: pd.Timestamp) -> str:
    h = t.hour
    if config.ASIAN_SESSION_START_UTC <= h < config.ASIAN_SESSION_END_UTC:
        return "ASIAN"
    if config.LONDON_SESSION_START_UTC <= h < config.LONDON_SESSION_END_UTC:
        return "LONDON"
    if config.NY_SESSION_START_UTC <= h < config.NY_SESSION_END_UTC:
        return "NY"
    return "OFF"


def _dist_atr(level: Optional[float], close: float, atr: float) -> float:
    if level is None or atr <= 0 or np.isnan(level):
        return np.nan
    return (level - close) / atr


def _direction_value(value: Optional[str]) -> int:
    return {"bullish": 1, "bearish": -1}.get(value, 0)


def _row_features(frames: Dict[str, pd.DataFrame], i: int, m5_all: pd.DataFrame, atr_all: pd.Series,
                  prev: dict) -> Optional[dict]:
    t = m5_all["time"].iloc[i]
    now = t + timedelta(minutes=TF_MINUTES["M5"])
    windows = {tf: _closed_window(frames[tf], tf, now) for tf in TFS}
    m5 = windows["M5"]
    if len(m5) < WINDOW // 2 or pd.isna(atr_all.iloc[i]) or atr_all.iloc[i] <= 0:
        return None

    atr = float(atr_all.iloc[i])
    close = float(m5["close"].iloc[-1])
    struct = {tf: analyze_structure(windows[tf]) for tf in TFS}
    zones = compute_zones(m5, windows["H1"], windows["H4"])

    sweeps_recent = detect_sweeps(m5, zones, lookback_bars=RECENT_BARS)
    sweep_low_recent = any(e.kind == "sweep_low" for e in sweeps_recent)
    sweep_high_recent = any(e.kind == "sweep_high" for e in sweeps_recent)
    sweeps_now = [e for e in sweeps_recent if pd.Timestamp(e.time) == pd.Timestamp(t)]
    sweep_now = 1 if any(e.kind == "sweep_low" for e in sweeps_now) else (
        -1 if any(e.kind == "sweep_high" for e in sweeps_now) else 0)

    disp = displacement_at(m5, len(m5) - 1)
    regime = classify_regime(windows["H1"], windows["M15"]).regime

    bos = {tf: struct[tf].last_bos for tf in ("M5", "H1")}
    mss = {tf: struct[tf].last_mss for tf in ("M5", "H1")}
    bos_event = {tf: int(bos[tf] is not None and bos[tf] != prev.get(("bos", tf))) * _direction_value(bos[tf])
                 for tf in ("M5", "H1")}
    mss_event = {tf: int(mss[tf] is not None and mss[tf] != prev.get(("mss", tf))) * _direction_value(mss[tf])
                 for tf in ("M5", "H1")}
    for tf in ("M5", "H1"):
        prev[("bos", tf)], prev[("mss", tf)] = bos[tf], mss[tf]

    key_levels = {
        "pdh": zones.get("Previous Day High"),
        "pdl": zones.get("Previous Day Low"),
        "h1_sh": zones.get("H1 Swing High"),
        "h1_sl": zones.get("H1 Swing Low"),
        "h4_sh": zones.get("H4 Swing High"),
        "h4_sl": zones.get("H4 Swing Low"),
        "vwap": zones.get("VWAP"),
    }
    dists = {f"f_dist_{k}_atr": _dist_atr(v, close, atr) for k, v in key_levels.items()}
    nearest = min((abs(v) for v in dists.values() if not np.isnan(v)), default=np.nan)

    row = {
        "f_time": t,
        "f_index": i,
        "f_close": close,
        "f_atr": atr,
        "f_session": configured_session(pd.Timestamp(t)),
        "f_regime": regime,
        "f_struct_M5": struct["M5"].state,
        "f_struct_M15": struct["M15"].state,
        "f_struct_H1": struct["H1"].state,
        "f_struct_H4": struct["H4"].state,
        "f_h1_dir": _direction_value("bullish" if struct["H1"].state == "BULLISH" else
                                     "bearish" if struct["H1"].state == "BEARISH" else None),
        "f_h4_dir": _direction_value("bullish" if struct["H4"].state == "BULLISH" else
                                     "bearish" if struct["H4"].state == "BEARISH" else None),
        "f_bos_M5": bos_event["M5"],
        "f_bos_H1": bos_event["H1"],
        "f_mss_M5": mss_event["M5"],
        "f_mss_H1": mss_event["H1"],
        "f_mss_state_M5": _direction_value(mss["M5"]),
        "f_sweep_now": sweep_now,
        "f_sweep_low_recent": int(sweep_low_recent),
        "f_sweep_high_recent": int(sweep_high_recent),
        "f_disp": _direction_value(disp),
        "f_nearest_key_atr": nearest,
    }
    row.update(dists)
    return row


def _outcome_columns(m5: pd.DataFrame, atr_all: pd.Series, i: int) -> dict:
    """Outcomes use bars AFTER i only."""
    out = {}
    close = float(m5["close"].iloc[i])
    atr = float(atr_all.iloc[i]) if not pd.isna(atr_all.iloc[i]) else np.nan
    for h in HORIZONS:
        j = i + h
        if j < len(m5) and atr > 0:
            out[f"y_fwd_ret_{h}_atr"] = (float(m5["close"].iloc[j]) - close) / atr
        else:
            out[f"y_fwd_ret_{h}_atr"] = np.nan
    end = min(i + 48, len(m5) - 1)
    if end > i and atr > 0:
        fut = m5.iloc[i + 1: end + 1]
        out["y_mfe_up_atr"] = (float(fut["high"].max()) - close) / atr
        out["y_mae_up_atr"] = (close - float(fut["low"].min())) / atr
        out["y_mfe_down_atr"] = (close - float(fut["low"].min())) / atr
        out["y_mae_down_atr"] = (float(fut["high"].max()) - close) / atr
    else:
        for k in ("y_mfe_up_atr", "y_mae_up_atr", "y_mfe_down_atr", "y_mae_down_atr"):
            out[k] = np.nan
    if atr > 0 and i + 48 < len(m5):
        out["y_label_buy_pm1"] = label_signal(m5, i, "BUY", atr, horizon=48).outcome
        out["y_label_sell_pm1"] = label_signal(m5, i, "SELL", atr, horizon=48).outcome
    else:
        out["y_label_buy_pm1"] = None
        out["y_label_sell_pm1"] = None
    return out


def build_rows(frames: Dict[str, pd.DataFrame], start: int, end: int) -> List[dict]:
    m5 = frames["M5"].reset_index(drop=True)
    atr_all = compute_atr(m5)
    prev: dict = {}
    rows: List[dict] = []
    for i in range(max(start, WINDOW), end):
        feat = _row_features(frames, i, m5, atr_all, prev)
        if feat is None:
            continue
        feat.update(_outcome_columns(m5, atr_all, i))
        rows.append(feat)
    return rows
