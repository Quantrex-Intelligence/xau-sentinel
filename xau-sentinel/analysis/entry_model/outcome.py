"""Outcome labeling for Entry Model V1 setup records -- the research stage that follows the
dataset foundation in dataset.py. Research only: no execution, no claim of edge.

build_setup_record() leaves every outcome field as None. This module fills them, for a setup that
already has a plan (entry, stop and a target -- i.e. its state was ENTRY_CONFIRMATION or
ENTRY_READY), by replaying the CLOSED bars that came after the record was made and checking which
of the plan's own stop or target was touched first. It changes nothing about the setup's own
facts (direction, checklist, entry/stop/target, confidence, ...): those are already fixed. It only
adds what happened afterwards.

A setup with no plan yet (entry is None -- every state up through RETRACEMENT_WAITING) has nothing
to label: there is no stop or target to measure against. Its outcome fields stay exactly as
build_setup_record() left them.

Not a backtest result. One labeled setup proves the pipeline runs, not that any condition here has
predictive value -- see docs/entry-model-v1-plan.md.
"""
from typing import Optional

import pandas as pd

TARGET_HIT, STOP_HIT, STILL_OPEN, NO_PLAN = "TARGET_HIT", "STOP_HIT", "STILL_OPEN", "NO_PLAN_TO_LABEL"


def label_outcome(setup_record: dict, path: Optional[pd.DataFrame], max_bars: Optional[int] = None) -> dict:
    """`path`: closed bars strictly after the setup's own record time (e.g. M5), oldest first, with
    time/high/low/close columns -- never the record's own as-of bar or anything before it, and never
    a forming bar (the caller passes closed-only data, the same convention as everywhere else in
    this package). Returns the outcome fields to merge into the record; never mutates `setup_record`.

    Both a stop touch and a target touch on the same bar resolve to the stop: this is the
    conservative reading (never assumes the more favorable fill is the one that happened first
    within a single candle)."""
    entry = setup_record.get("entry") or {}
    stop = setup_record.get("stop") or {}
    targets = setup_record.get("targets") or []
    entry_price = entry.get("price")
    stop_price = stop.get("price")
    target_price = targets[0]["price"] if targets else None
    direction = setup_record.get("direction")

    if entry_price is None or stop_price is None or direction not in ("LONG", "SHORT"):
        # No plan existed at record time (state before ENTRY_CONFIRMATION): nothing to label yet.
        return {"outcome_status": setup_record.get("outcome_status") or NO_PLAN}

    risk = abs(entry_price - stop_price)
    if risk <= 0 or path is None or len(path) == 0:
        return {"outcome_status": "PENDING"}  # a plan exists, but there is no price history to check yet

    rows = path if max_bars is None else path.iloc[:max_bars]
    t0 = pd.Timestamp(setup_record["record_time_utc"]) if setup_record.get("record_time_utc") else None

    mfe = mae = 0.0  # in price, favorable/adverse excursion from entry, tracked every bar regardless of outcome
    outcome_status = STILL_OPEN
    target_hit = stop_hit = False
    time_to_target = time_to_invalidation = None

    for _, bar in rows.iterrows():
        high, low = float(bar["high"]), float(bar["low"])
        favorable = (high - entry_price) if direction == "LONG" else (entry_price - low)
        adverse = (entry_price - low) if direction == "LONG" else (high - entry_price)
        mfe = max(mfe, favorable)
        mae = max(mae, adverse)

        stop_touched = (low <= stop_price) if direction == "LONG" else (high >= stop_price)
        target_touched = target_price is not None and (
            (high >= target_price) if direction == "LONG" else (low <= target_price))

        if stop_touched:
            outcome_status, stop_hit = STOP_HIT, True
            time_to_invalidation = None if t0 is None else str(pd.Timestamp(bar["time"]) - t0)
            break
        if target_touched:
            outcome_status, target_hit = TARGET_HIT, True
            time_to_target = None if t0 is None else str(pd.Timestamp(bar["time"]) - t0)
            break

    outcome_r = None
    if target_hit and target_price is not None:
        outcome_r = round(abs(target_price - entry_price) / risk, 2)
    elif stop_hit:
        outcome_r = -1.0

    return {
        "outcome_status": outcome_status,
        "mfe": round(mfe, 2), "mae": round(mae, 2),
        "maximum_favorable_r": round(mfe / risk, 2), "maximum_adverse_r": round(mae / risk, 2),
        "outcome_r": outcome_r,
        "time_to_target": time_to_target, "time_to_invalidation": time_to_invalidation,
        "target_hit": target_hit, "stop_hit": stop_hit,
        "expired": outcome_status == STILL_OPEN,
    }
