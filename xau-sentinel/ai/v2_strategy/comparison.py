"""Deterministic comparison of the legacy A+ path and the V2-fed A+ path.

For validation and debugging only. It is not shown to users and it changes no
rating. Both paths run the SAME decision step (decide_from_facts) on facts
from different sources, so any difference is a difference in facts, never in
rules.

Output: the facts each path used, the field-by-field differences, what A+
needs that V2 does not supply, the M5 MSS semantics check, both evaluations,
and whether they agree.
"""
from datetime import datetime
from typing import Optional

from analysis.sequence import evaluate_sequence
from analysis.v2.engine import build_analysis
from ai.strategy import rules
from ai.strategy.evaluator import collect_legacy_facts, decide_from_facts
from ai.strategy.facts import StrategyFacts
from ai.strategy.schemas import StrategyEvaluationOut
from ai.v2_strategy.bridge import V2NotEvaluable, facts_from_v2
from risk.models import FundedNextStatus

MISSING_FROM_V2 = (
    "M5 sequence after a sweep (MSS, displacement, retracement): not computed by V2; "
    "the existing analysis/sequence.py runs on closed M5 bars in both paths.",
    "Entry price: A+ uses the forming M5 close (closed_only exception); V2 reports the last closed close. "
    "The bridge keeps A+ semantics.",
    "FundedNext gate: external risk state, not market analysis.",
    "Key-area relations, confluence, regime, volume and volatility state: V2 context with no slot in the A+ rules.",
)


def _sweep_key(s):
    return (s.kind, s.level_name, float(s.level_price), str(s.time))


def _facts_summary(f: StrategyFacts) -> dict:
    return {
        "h4_state": f.h4.state, "h4_reason": f.h4.reason,
        "h1_state": f.h1.state, "h1_last_mss": f.h1.last_mss, "h1_last_bos": f.h1.last_bos,
        "m15_state": f.m15.state, "m5_state": f.m5.state,
        "sweeps": [_sweep_key(s) for s in f.sweeps],
        "equal_levels": [e.label for e in f.equal_levels],
        "zones": dict(sorted(f.zones.items())),
        "current_price": f.current_price,
        "data_stale": f.data_stale,
    }


def _differences(legacy: dict, v2: dict) -> list:
    out = []
    for key in legacy:
        if legacy[key] != v2[key]:
            out.append({"field": key, "legacy": legacy[key], "v2": v2[key]})
    return out


def _sequence_mss(facts: StrategyFacts) -> Optional[dict]:
    """A+'s own M5 MSS for the current candidate, from the existing sequence module."""
    candidate = rules.select_candidate(facts.sweeps)
    if candidate is None:
        return None
    direction = rules.candidate_direction(candidate)
    seq = evaluate_sequence(facts.m5_closed, candidate, direction)
    return {"direction": direction, "a_plus_mss_confirmed": bool(seq.mss_ok),
            "structure_m5_last_mss": facts.m5.last_mss}


def _evaluation_summary(e: StrategyEvaluationOut) -> dict:
    return {
        "rating": e.rating.value,
        "direction": e.direction,
        "criteria": [(c.name, c.status.value) for c in e.criteria],
        "missing_conditions": list(e.missing_conditions),
        "entry": e.entry, "stop_loss": e.stop_loss, "target": e.target, "rr": e.rr,
        "invalidation": e.invalidation,
    }


def compare_paths(candles: dict, fundednext_status: FundedNextStatus, now: datetime) -> dict:
    analysis = build_analysis(candles, now=now)
    legacy_facts = collect_legacy_facts(candles, now)
    legacy_eval = decide_from_facts(legacy_facts, fundednext_status, now)

    result = {
        "v2_analysis_status": analysis.status,
        "legacy_evaluation": _evaluation_summary(legacy_eval),
        "missing_from_v2": list(MISSING_FROM_V2),
        "v2_only_context": {
            "key_areas": len(analysis.areas),
            "confluence_reference": analysis.confluence.reference if analysis.confluence else None,
            "regime": analysis.context.regime.state if analysis.context else None,
        },
    }
    try:
        v2_facts = facts_from_v2(analysis, candles)
    except V2NotEvaluable as exc:
        result.update({"v2_status": "not_evaluable", "reason": str(exc)})
        return result

    v2_eval = decide_from_facts(v2_facts, fundednext_status, now)
    legacy_summary, v2_summary = _facts_summary(legacy_facts), _facts_summary(v2_facts)
    result.update({
        "v2_status": "evaluated",
        "legacy_inputs": legacy_summary,
        "v2_inputs": v2_summary,
        "differences": _differences(legacy_summary, v2_summary),
        "mss_semantics": {"legacy": _sequence_mss(legacy_facts), "v2": _sequence_mss(v2_facts)},
        "v2_evaluation": _evaluation_summary(v2_eval),
        "agreement": {
            "rating": legacy_eval.rating == v2_eval.rating,
            "criteria": [(c.name, c.status.value) for c in legacy_eval.criteria]
            == [(c.name, c.status.value) for c in v2_eval.criteria],
        },
    })
    return result
