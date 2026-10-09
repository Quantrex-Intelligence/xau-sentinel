"""Eligibility, candidate identity, and the compact evidence snapshot sent to the LLM Setup Judge.

Every field in the snapshot comes straight from analysis.entry_model.hierarchy.evaluate()'s own
return dict or api.analysis_v2.build_payload()'s own response -- nothing here recomputes a market
fact, a bias, or a setup state, and nothing is ever filled in with a guess when a field is missing
(it is simply omitted or left None, exactly as the deterministic engines already left it).
"""
import hashlib
import json
from datetime import datetime
from typing import Optional

# Deliberately duplicated, not imported, from research/entry_model_v2_oos/spec.py::QUALIFYING_STATES
# -- that package's own docstring says it is "never imported by the production app," and this judge
# is production code. Keep in sync by hand if the Entry Model state machine ever changes; the two are
# independent lists serving independent purposes (research sampling vs. a live shadow-mode judge).
ELIGIBLE_STATES = ("ENTRY_CONFIRMATION_DEVELOPING", "ENTRY_CONFIRMED", "PRECISION_AVAILABLE", "ENTRY_READY")


def is_eligible(entry_model_result: dict) -> bool:
    return entry_model_result.get("state") in ELIGIBLE_STATES


def working_direction(entry_model_result: dict) -> Optional[str]:
    """The setup's underlying (ungated) direction -- setup_15m.setup_direction, not the exposed/
    gated top-level `direction` (which stays None until 5M confirmation reaches CONFIRMED; see
    hierarchy.py's own exposed_direction comment, and
    research/entry_model_v2_oos/pipeline.py::_working_direction for the identical reasoning applied
    to the same problem in a different, research-only context)."""
    setup = entry_model_result.get("setup_15m") or {}
    direction = setup.get("setup_direction")
    return direction if direction in ("LONG", "SHORT") else None


def _earliest_anchor_timestamp(entry_model_result: dict) -> Optional[str]:
    """The earliest timestamp among the 15M FVG's formed_at and every supporting-evidence item
    (setup_15m + confirmation_5m). These are all historical facts tied to bars already in the past
    -- for the SAME real-world setup, they are established once (as early as
    ENTRY_CONFIRMATION_DEVELOPING) and do not change on later polls, which is exactly what makes
    this a stable identity anchor across the whole state progression (see candidate_key's own
    docstring for why this must be preferred over the entry candidate's stop price)."""
    setup = entry_model_result.get("setup_15m") or {}
    confirmation = entry_model_result.get("confirmation_5m") or {}
    timestamps = [
        e["timestamp"] for e in (setup.get("supporting_evidence") or []) + (confirmation.get("supporting_evidence") or [])
        if e.get("timestamp")
    ]
    fvg = setup.get("fvg")
    if fvg and fvg.get("formed_at"):
        timestamps.append(fvg["formed_at"])
    return min(timestamps) if timestamps else None


def candidate_key(entry_model_result: dict) -> Optional[str]:
    """(working_direction, anchor) encoded as one string. `anchor` prefers the earliest known
    evidence timestamp (FVG formed_at, or the earliest supporting-evidence item) over the entry
    candidate's own stop price, and falls back to the stop price only when neither evidence exists
    at all.

    This order matters for identity continuity: the entry candidate (and its stop price) is only
    built once confirmation reaches CONFIRMED, while the SAME real-world setup is already visible,
    with its own FVG/evidence already fixed, as early as ENTRY_CONFIRMATION_DEVELOPING. Preferring
    the stop price would make the key change the moment a candidate is built -- confirmed directly:
    the same setup's key was "LONG:fvg:<t>" while developing and "LONG:stop:<price>" once confirmed,
    two different keys for one real-world setup, which broke reassessment tracking (store.py could
    never find the earlier row). Preferring the earliest evidence timestamp instead keeps the same
    key for the setup's entire life, since that evidence doesn't change between polls unless the
    setup itself is genuinely a new one.

    Returns None only if the direction itself hasn't resolved (should not happen for an eligible
    state, since reaching ENTRY_CONFIRMATION_DEVELOPING already requires setup_15m to have resolved
    a direction)."""
    direction = working_direction(entry_model_result)
    if direction is None:
        return None

    anchor = _earliest_anchor_timestamp(entry_model_result)
    if anchor:
        return f"{direction}:evidence:{anchor}"

    candidate = entry_model_result.get("entry_candidate")
    if candidate and candidate.get("stop"):
        return f"{direction}:stop:{round(candidate['stop']['price'], 2)}"

    return None


def _v2_context_fold(v2_result) -> Optional[dict]:
    """A compact fold of Market Analysis V2's context -- regime/volatility/session plus the nearest
    1-2 key areas and any cross-timeframe conflicts. None when V2 has nothing to say (UNAVAILABLE/
    INSUFFICIENT_DATA), never a fabricated placeholder."""
    if v2_result is None:
        return None
    interpretation = getattr(v2_result, "interpretation", None)
    if interpretation is None or interpretation.context is None:
        return None
    ctx = interpretation.context
    nearest_areas = sorted(
        (interpretation.key_areas or []), key=lambda a: a.distance_atr if a.distance_atr is not None else 1e9,
    )[:2]
    return {
        "regime": ctx.regime.state, "volatility": ctx.volatility.state, "session": ctx.session.state,
        "nearest_key_areas": [
            {"low": a.low, "high": a.high, "side": a.side, "relation": a.relation, "distance_atr": a.distance_atr}
            for a in nearest_areas
        ],
        "cross_timeframe_conflicts": (interpretation.confluence.cross_timeframe_conflicts
                                      if interpretation.confluence else []),
    }


def build_snapshot(entry_model_result: dict, v2_result=None) -> dict:
    """The compact, structured snapshot handed to the LLM -- every field named in the task spec,
    each omitted (not fabricated) when the underlying engine hasn't produced it yet."""
    candidate = entry_model_result.get("entry_candidate")
    return {
        "symbol": entry_model_result.get("symbol"),
        "as_of": entry_model_result.get("as_of"),
        "state": entry_model_result.get("state"),
        "working_direction": working_direction(entry_model_result),
        "higher_timeframe": entry_model_result.get("higher_timeframe"),
        "intraday": entry_model_result.get("intraday"),
        "setup_15m": entry_model_result.get("setup_15m"),
        "confirmation_5m": entry_model_result.get("confirmation_5m"),
        "precision_1m": entry_model_result.get("precision_1m"),
        "supporting_evidence": entry_model_result.get("supporting_evidence", []),
        "contradicting_evidence": entry_model_result.get("contradicting_evidence", []),
        "confidence": entry_model_result.get("confidence"),
        "invalidation": entry_model_result.get("invalidation"),
        "next_condition": entry_model_result.get("next_condition"),
        "entry_candidate": candidate,  # None if not yet built -- never fabricated
        "market_context": _v2_context_fold(v2_result),
    }


def fingerprint(snapshot: dict) -> str:
    """sha256 of the sorted-JSON snapshot. Two polls of the same real-world candidate with no
    material evidence change produce the same fingerprint -- the signal evaluator.py uses to skip
    re-judging an unchanged candidate."""
    canonical = json.dumps(snapshot, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def candidate_created_at(entry_model_result: dict) -> datetime:
    """Best available 'first seen' timestamp for a brand-new candidate_key: the setup's own as_of
    (the last closed M5 bar time) -- not wall-clock now, so it stays meaningful under replay/testing
    with a fixed clock."""
    as_of = entry_model_result.get("as_of")
    if as_of:
        return datetime.fromisoformat(as_of)
    from datetime import timezone
    return datetime.now(timezone.utc)
