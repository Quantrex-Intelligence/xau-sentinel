"""Outcome-dataset foundation for Entry Model V1 research.

Builds one deterministic record per qualifying setup. A setup begins at its liquidity sweep, so
NO_SETUP, HTF_ALIGNED and INSUFFICIENT_DATA (no sweep yet) produce no record. LIQUIDITY_SWEPT through
ENTRY_READY, and the terminal EXPIRED and INVALIDATED states, all produce one, because each is a real,
already-observed fact about that sweep.

This module reshapes `evaluate()`'s own output. It recomputes nothing and reads no further-ahead data
than `evaluate()` itself used, so the record represents what the engine actually observed, never a
later interpretation of it.

No outcome is ever fabricated. Every outcome field starts as None. `outcome_status` is the one
exception: it is a dataset-bookkeeping label ("PENDING", or the deterministic terminal state the
engine itself reached), never a trading result.

`setup_id` is stable for a given direction and sweep time, so re-evaluating the same sweep at a later
as-of time yields the same id. `dedupe_setup_records` keeps the most recent record per id, so a run
that evaluates many as-of times does not read as many distinct setups.
"""
from typing import Dict, List, Optional

OUTCOME_FIELDS = (
    "mfe", "mae", "maximum_favorable_r", "maximum_adverse_r", "outcome_r",
    "time_to_target", "time_to_invalidation", "target_hit", "stop_hit", "expired",
)

_TERMINAL_STATUS = {"EXPIRED": "EXPIRED_BEFORE_ENTRY", "INVALIDATED": "INVALIDATED_BEFORE_ENTRY"}


def _empty_outcome() -> dict:
    out = {k: None for k in OUTCOME_FIELDS}
    out["outcome_status"] = "PENDING"
    return out


def build_setup_record(result: dict, *, now, regime: Optional[dict], session: Optional[str],
                       opposing_liquidity: Optional[dict]) -> Optional[dict]:
    """`result` is `evaluate()`'s own return value (after its direction/state/liquidity are set).
    `regime`, `session` and `opposing_liquidity` are passed in because they are computed once per
    evaluation and shared across call sites; nothing here derives a new fact from raw candles."""
    liquidity = result.get("liquidity")
    if liquidity is None or result.get("direction") is None:
        return None  # no sweep yet: there is no setup to record

    sweep = liquidity["sweep"]
    direction = result["direction"]
    setup_id = f"{direction}:{sweep['time']}"
    seq = result.get("sequence") or {}
    steps = {s["name"]: s for s in seq.get("steps", [])}
    fvg = result.get("fvg")
    m1c = result.get("m1_confirmation")

    outcome = _empty_outcome()
    outcome["outcome_status"] = _TERMINAL_STATUS.get(result["state"], "PENDING")

    return {
        "setup_id": setup_id,
        "symbol": "XAUUSD",
        "direction": direction,
        "state_at_record": result["state"],
        "generated_at_utc": None if now is None else str(now),
        "record_time_utc": result.get("as_of"),

        # Setup identity: every event time, bar-tied, in the order it was actually observed.
        "setup_time_utc": sweep["time"],
        "sweep_time_utc": sweep["time"],
        "mss_time_utc": steps.get("STRUCTURE_SHIFT", {}).get("time"),
        "displacement_time_utc": steps.get("DISPLACEMENT", {}).get("time"),
        "fvg_time_utc": None if fvg is None else fvg.get("formed_at"),
        "retracement_time_utc": None if fvg is None else fvg.get("retested_at"),
        "confirm_5m_time_utc": result.get("timeframes", {}).get("5m", {}).get("confirmed_at"),
        "confirm_1m_time_utc": None if m1c is None else m1c.get("time_utc"),
        "event_ordering": {
            "mss_vs_displacement": seq.get("ordering"),
            "chronology_ok": seq.get("chronology_ok"),
            "sweep_is_displacement_bar": seq.get("sweep_is_displacement_bar"),
            "sweep_is_mss_bar": seq.get("sweep_is_mss_bar"),
        },

        # Multi-timeframe context, unchanged from what evaluate() itself determined.
        "timeframes": result.get("timeframes"),

        # Confluence: each item is the same structured object the model already returned.
        "confluence": {
            "liquidity": liquidity,
            "supply_demand_sr": result.get("key_area"),
            "key_level": result.get("level_confluence"),
            "fvg": fvg,
            "ote": result.get("ote"),
            "premium_discount": result.get("timeframes", {}).get("1h", {}).get("premium_discount"),
        },

        # Trade plan: a manual-review proposal, not an order.
        "entry": result.get("entry"),
        "stop": result.get("stop"),
        "targets": result.get("targets"),
        "rr": result.get("rr"),
        "invalidation": result.get("invalidation"),

        # Market conditions at the time of the record.
        "market_conditions": {
            "regime": regime, "session": session,
            "relevant_key_area": result.get("key_area"),
            "opposing_liquidity": opposing_liquidity,
        },

        "contradictions": result.get("contradictions", []),
        "setup_confidence": result.get("setup_confidence"),

        # Provenance: the same checklist the model returned. Every item already carries its
        # timeframe, timestamp, evidence and the deterministic reason it passed or waited.
        "evidence_log": result.get("checklist", []),

        # Outcome fields: always empty here. A separate, later process fills them by replaying
        # price action after `setup_time_utc` against this record's entry/stop/targets. This
        # function never reads that far ahead.
        **outcome,
    }


def dedupe_setup_records(records: List[dict]) -> List[dict]:
    """Keeps the most recently generated record per `setup_id`, in first-seen order. Re-evaluating the
    same sweep at many as-of times must not read as more than one setup."""
    best: Dict[str, dict] = {}
    order: List[str] = []
    for r in records:
        sid = r["setup_id"]
        if sid not in best:
            order.append(sid)
        prev = best.get(sid)
        if prev is None or (r.get("generated_at_utc") or "") >= (prev.get("generated_at_utc") or ""):
            best[sid] = r
    return [best[sid] for sid in order]
