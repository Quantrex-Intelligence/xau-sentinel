"""1M layer: precision entry. Answers "Can the entry be refined more precisely?" -- optional, and
never the primary directional decision.

The caller (hierarchy.py) must never consult this layer's result to create or upgrade an
ENTRY_CANDIDATE unless 5M confirmation has already reached at least DEVELOPING on its own; a strong
1M pattern alone must never do that by itself. This module does not enforce that gating itself (it
has no view of the confirmation state) -- hierarchy.py does, deliberately, so the rule is visible in
exactly one place.

Reuses analysis.v2.events.structure_transitions for a specific, bar-tied M1 event (the same
primitive Entry Model V1's hardening stage used for 1M confirmation), instead of a vague "M1 is
bullish/bearish" state reading.
"""
from typing import Optional

import pandas as pd

from analysis.entry_model.common import ev, ev_dict, item
from analysis.v2.events import structure_transitions

PRECISION_STATES = ("NOT_APPLICABLE", "WAITING", "AVAILABLE")
TRANSITION_WINDOW = 120  # closed M1 bars replayed; needs len(M1) >= this + 10 (see structure_transitions)


def evaluate_precision(m1: Optional[pd.DataFrame], direction: str, not_before: Optional[pd.Timestamp]) -> dict:
    seq_bias = {"LONG": "bullish", "SHORT": "bearish"}.get(direction)
    if seq_bias is None or not_before is None:
        return {"precision_status": "NOT_APPLICABLE", "trigger": None,
                "checklist": [item("Precision trigger", "NOT_APPLICABLE", "1M",
                                   "no setup direction to refine yet", dependency="5M confirmation")]}
    if m1 is None or len(m1) - 11 < TRANSITION_WINDOW // 4:
        return {"precision_status": "WAITING", "trigger": None,
                "checklist": [item("Micro structure", "WAITING", "1M", "not enough M1 history")]}

    window = min(len(m1) - 11, TRANSITION_WINDOW)
    candidates = [e for e in structure_transitions(m1, "M1", window)
                  if e.kind in ("MSS", "BOS") and e.direction == seq_bias and pd.Timestamp(e.time) >= not_before]
    if not candidates:
        return {"precision_status": "WAITING", "trigger": None,
                "checklist": [item("Micro structure", "WAITING", "1M",
                                   "no closed M1 MSS/BOS in the setup direction yet")]}

    e = min(candidates, key=lambda x: pd.Timestamp(x.time))
    match = m1.index[m1["time"] == e.time]
    bar_index = int(match[0]) if len(match) else None
    trigger = {"time_utc": pd.Timestamp(e.time).isoformat(), "bar_index": bar_index, "direction": e.direction,
              "event_type": e.kind, "price": None if e.price is None else round(float(e.price), 2),
              "closed_bar": True, "detail": e.detail}
    checklist = [
        item("Micro structure", "PASS", "1M", f"M1 {e.kind} at {trigger['time_utc']}",
            ev("M1", e.time, e.kind, e.price, "analysis.v2.events", e.detail)),
        item("MSS", "PASS" if e.kind == "MSS" else "NOT_APPLICABLE", "1M", e.detail),
        item("Precision trigger", "PASS", "1M", "specific closed M1 bar in the setup direction"),
    ]
    return {"precision_status": "AVAILABLE", "trigger": trigger, "checklist": checklist}
