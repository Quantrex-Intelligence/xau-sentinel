"""V2 research dataset: V1 context/event features plus preregistered sequence
triggers and R-based outcomes. Research only; no production code changes.

Sequence triggers (state machine, one per sweep instance):
    LOW side  (sweep_low at bar j, most recent one):
        LOW_R1  reversal:     MSS bull within 12 bars of j          -> BUY
        LOW_R2  reversal:     MSS bull, then displacement bull (<=24 bars from j) -> BUY
        LOW_C1  continuation: BOS bear within 12 bars of j          -> SELL
        LOW_C2  continuation: displacement bear within 12 bars of j with no MSS bull since j -> SELL
    HIGH side (sweep_high): mirror image
        HIGH_R1 / HIGH_R2 -> SELL;  HIGH_C1 / HIGH_C2 -> BUY

Each sequence fires at most once per sweep. A new sweep on the same side
resets that side's state (most recent sweep only).
"""
from typing import Dict, List

import pandas as pd

from analysis.structure import compute_atr
from backtest.replay import WINDOW
from backtest.research.features import _row_features
from backtest.research.outcomes_r import r_outcome

SEQ_TYPES = ("LOW_R1", "LOW_R2", "LOW_C1", "LOW_C2", "HIGH_R1", "HIGH_R2", "HIGH_C1", "HIGH_C2")
TRIGGER_DIRECTION = {"LOW_R1": "BUY", "LOW_R2": "BUY", "LOW_C1": "SELL", "LOW_C2": "SELL",
                     "HIGH_R1": "SELL", "HIGH_R2": "SELL", "HIGH_C1": "BUY", "HIGH_C2": "BUY"}
SWEEP_WINDOW = 12
SEQ_WINDOW = 24


class _Side:
    def __init__(self):
        self.j = None
        self.mss_since = None
        self.used = set()

    def reset(self, j: int):
        self.j = j
        self.mss_since = None
        self.used = set()


def _step_triggers(i: int, row: dict, low: _Side, high: _Side) -> Dict[str, int]:
    trig = {name: 0 for name in SEQ_TYPES}
    if row["f_sweep_now"] == 1:
        low.reset(i)
    if row["f_sweep_now"] == -1:
        high.reset(i)

    # LOW side (opposing events are read with the sign conventions in V1).
    if low.j is not None:
        age = i - low.j
        if row["f_mss_M5"] == 1 and 1 <= age <= SWEEP_WINDOW and "LOW_R1" not in low.used:
            trig["LOW_R1"] = 1
            low.used.add("LOW_R1")
        if row["f_disp"] == 1 and low.mss_since is not None and 1 <= age <= SEQ_WINDOW and "LOW_R2" not in low.used:
            trig["LOW_R2"] = 1
            low.used.add("LOW_R2")
        if row["f_bos_M5"] == -1 and 1 <= age <= SWEEP_WINDOW and "LOW_C1" not in low.used:
            trig["LOW_C1"] = 1
            low.used.add("LOW_C1")
        if row["f_disp"] == -1 and 1 <= age <= SWEEP_WINDOW and low.mss_since is None and "LOW_C2" not in low.used:
            trig["LOW_C2"] = 1
            low.used.add("LOW_C2")
        if row["f_mss_M5"] == 1 and low.mss_since is None:
            low.mss_since = i

    # HIGH side (mirror).
    if high.j is not None:
        age = i - high.j
        if row["f_mss_M5"] == -1 and 1 <= age <= SWEEP_WINDOW and "HIGH_R1" not in high.used:
            trig["HIGH_R1"] = 1
            high.used.add("HIGH_R1")
        if row["f_disp"] == -1 and high.mss_since is not None and 1 <= age <= SEQ_WINDOW and "HIGH_R2" not in high.used:
            trig["HIGH_R2"] = 1
            high.used.add("HIGH_R2")
        if row["f_bos_M5"] == 1 and 1 <= age <= SWEEP_WINDOW and "HIGH_C1" not in high.used:
            trig["HIGH_C1"] = 1
            high.used.add("HIGH_C1")
        if row["f_disp"] == 1 and 1 <= age <= SWEEP_WINDOW and high.mss_since is None and "HIGH_C2" not in high.used:
            trig["HIGH_C2"] = 1
            high.used.add("HIGH_C2")
        if row["f_mss_M5"] == -1 and high.mss_since is None:
            high.mss_since = i
    return trig


def _outcome_row(m5: pd.DataFrame, atr_all: pd.Series, i: int) -> dict:
    out = {}
    atr = float(atr_all.iloc[i]) if not pd.isna(atr_all.iloc[i]) else None
    for d in ("BUY", "SELL"):
        o = r_outcome(m5, i, d, atr) if atr else None
        key = d.lower()
        if o is None:
            out[f"y_{key}_fwd_ret_48"] = float("nan")
            out[f"y_{key}_mfe_r"] = float("nan")
            out[f"y_{key}_mae_r"] = float("nan")
            for k in (1, 2, 3):
                out[f"y_{key}_exp_{k}r"] = float("nan")
                out[f"y_{key}_hit_{k}r"] = None
            out[f"y_{key}_stop_first"] = None
            continue
        out[f"y_{key}_fwd_ret_48"] = o.fwd_ret_48_atr
        out[f"y_{key}_mfe_r"] = o.mfe_r
        out[f"y_{key}_mae_r"] = o.mae_r
        out[f"y_{key}_stop_first"] = o.stop_first
        for k in (1, 2, 3):
            out[f"y_{key}_exp_{k}r"] = o.expectancy(k)
            out[f"y_{key}_hit_{k}r"] = o.outcome(k)
    return out


def build_rows_v2(frames: Dict[str, pd.DataFrame], start: int, end: int) -> List[dict]:
    from backtest.research.features import _row_features as v1_row

    m5 = frames["M5"].reset_index(drop=True)
    atr_all = compute_atr(m5)
    prev: dict = {}
    low, high = _Side(), _Side()
    rows: List[dict] = []
    for i in range(max(start, WINDOW), end):
        feat = v1_row(frames, i, m5, atr_all, prev)
        if feat is None:
            continue
        trig = _step_triggers(i, feat, low, high)
        for name in SEQ_TYPES:
            feat[f"trig_{name}"] = trig[name]
        feat.update(_outcome_row(m5, atr_all, i))
        rows.append(feat)
    return rows
