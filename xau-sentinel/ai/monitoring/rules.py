"""Deterministic alert rules (Stage 13) — one pure function per AlertType,
each `(previous, current, raw) -> List[AlertEvent]`. Every rule is a plain
comparison of two already-computed MonitoringSnapshot fields; nothing here
calls an LLM provider, asks whether a setup "looks" A+, or reinterprets the
deterministic rating in any way (see ai/monitoring/engine.py's docstring
and tests/test_monitoring_rules.py's structural "never touches an LLM"
test). `raw` (a RawEvaluationBundle) supplies the rich, already-decided
facts an alert's payload quotes — never recomputed here.

Every dedup_key is built from stable identity (alert type + the specific
transition + an identifier + a timestamp), never a random id, so the same
underlying transition can only ever produce one alert (ai/monitoring/store.py
enforces this again at the database level via a UNIQUE index).

Stage 23B (VAL-019): the timestamp component of the four transition keys
is the PREVIOUS snapshot's timestamp (the baseline the transition was
measured from), never the current cycle's. If a cycle persists some alerts
and then fails before ai/monitoring/engine.py advances its baseline, the
retry cycle diffs against that SAME baseline and so rebuilds byte-identical
keys — the UNIQUE index then turns the re-detection into a no-op instead
of a duplicate alert (and a duplicate outbound notification). A genuine repeat
of the same transition later is still a new alert, because by then the
baseline has moved on and carries a different timestamp.
"""
from typing import List, Optional

from ai.monitoring.models import AlertEvent, AlertType, MonitoringSnapshot, RawEvaluationBundle, Severity

_RISK_SEVERITY = {
    "SAFE": Severity.INFO,
    "UNKNOWN": Severity.INFO,
    "WARNING": Severity.WARNING,
    "CRITICAL": Severity.CRITICAL,
    "BREACHED": Severity.CRITICAL,
}


def setup_state_changed(previous: Optional[MonitoringSnapshot], current: MonitoringSnapshot,
                         raw: RawEvaluationBundle) -> List[AlertEvent]:
    if previous is None or previous.setup_state == current.setup_state:
        return []
    setup = raw.setup_result
    direction_label = f" ({current.setup_direction})" if current.setup_direction else ""
    return [AlertEvent(
        type=AlertType.SETUP_STATE_CHANGED, severity=Severity.INFO,
        title=f"Setup state: {previous.setup_state} → {current.setup_state}",
        message=f"XAUUSD setup{direction_label} moved from {previous.setup_state} to {current.setup_state}. "
                f"{setup.reason}",
        dedup_key=f"SETUP_STATE_CHANGED:{previous.setup_state}->{current.setup_state}:"
                   f"{current.setup_direction}:{previous.timestamp}",
        payload={
            "previous_state": previous.setup_state, "current_state": current.setup_state,
            "direction": current.setup_direction, "checklist": dict(setup.checklist),
            "reason": setup.reason,
        },
    )]


def aplus_setup_detected(previous: Optional[MonitoringSnapshot], current: MonitoringSnapshot,
                          raw: RawEvaluationBundle) -> List[AlertEvent]:
    """Fires on a cross INTO A+, and (Stage 23B, VAL-023) also on a change
    of setup while already A+ — the direction flipped, or a new candidate
    sweep replaced the prior one with no non-A+ cycle in between. Either is
    a different trade (new entry/SL/TP) that must be announced; the
    dedup_key already carries direction + candidate_sweep_time, so it is
    distinct from the replaced setup's alert."""
    if previous is None or current.aplus_rating != "A+":
        return []
    if previous.aplus_rating == "A+" and (
        previous.aplus_direction == current.aplus_direction
        and previous.aplus_candidate_key == current.aplus_candidate_key
    ):
        return []
    result = raw.strategy_result
    return [AlertEvent(
        type=AlertType.APLUS_SETUP_DETECTED, severity=Severity.INFO,
        title=f"A+ setup detected — {current.aplus_direction}",
        message=f"{current.aplus_direction} A+ setup confirmed — entry {result.entry}, "
                f"SL {result.stop_loss}, target {result.target}, R:R 1:{result.rr}.",
        dedup_key=f"APLUS_SETUP_DETECTED:{current.aplus_direction}:{result.candidate_sweep_time}",
        payload={
            "direction": current.aplus_direction, "entry": result.entry, "stop_loss": result.stop_loss,
            "target": result.target, "rr": result.rr, "rating": result.rating.value,
            "criteria": [c.model_dump() for c in result.criteria],
            "fundednext_safety_level": result.fundednext.safety_level,
        },
    )]


def aplus_setup_invalidated(previous: Optional[MonitoringSnapshot], current: MonitoringSnapshot,
                             raw: RawEvaluationBundle) -> List[AlertEvent]:
    if previous is None or previous.aplus_rating != "A+" or current.aplus_rating == "A+":
        return []
    result = raw.strategy_result
    return [AlertEvent(
        type=AlertType.APLUS_SETUP_INVALIDATED, severity=Severity.INFO,
        title="A+ setup invalidated",
        message=f"The previously confirmed A+ setup is no longer valid "
                f"({result.invalidation or 'deterministic conditions no longer met'}).",
        dedup_key=f"APLUS_SETUP_INVALIDATED:{previous.aplus_direction}:{previous.timestamp}",
        payload={
            "previous_direction": previous.aplus_direction, "invalidation": result.invalidation,
            "rating": result.rating.value,
        },
    )]


def risk_status_changed(previous: Optional[MonitoringSnapshot], current: MonitoringSnapshot,
                         raw: RawEvaluationBundle) -> List[AlertEvent]:
    if previous is None or previous.risk_safety_level == current.risk_safety_level:
        return []
    status = raw.fundednext_status
    severity = _RISK_SEVERITY.get(current.risk_safety_level, Severity.INFO)
    return [AlertEvent(
        type=AlertType.RISK_STATUS_CHANGED, severity=severity,
        title=f"FundedNext risk: {previous.risk_safety_level} → {current.risk_safety_level}",
        message=f"FundedNext safety level moved from {previous.risk_safety_level} to "
                f"{current.risk_safety_level}. {status.reason}",
        dedup_key=f"RISK_STATUS_CHANGED:{previous.risk_safety_level}->{current.risk_safety_level}:"
                   f"{previous.timestamp}",
        payload={
            "previous_status": previous.risk_safety_level, "current_status": current.risk_safety_level,
            "daily_loss_used_pct": status.daily_loss_used_pct, "max_drawdown_used_pct": status.max_drawdown_used_pct,
            "reason": status.reason,
        },
    )]


def market_intelligence_quality_changed(previous: Optional[MonitoringSnapshot], current: MonitoringSnapshot,
                                         raw: RawEvaluationBundle) -> List[AlertEvent]:
    if previous is None or previous.mi_overall_quality == current.mi_overall_quality:
        return []
    severity = Severity.INFO if current.mi_overall_quality == "AVAILABLE" else Severity.WARNING
    summary = raw.intelligence_summary
    return [AlertEvent(
        type=AlertType.MARKET_INTELLIGENCE_QUALITY_CHANGED, severity=severity,
        title=f"Market Intelligence quality: {previous.mi_overall_quality} → {current.mi_overall_quality}",
        message=f"Overall Market Intelligence availability moved from {previous.mi_overall_quality} "
                f"to {current.mi_overall_quality}.",
        dedup_key=f"MARKET_INTELLIGENCE_QUALITY_CHANGED:{previous.mi_overall_quality}->"
                   f"{current.mi_overall_quality}:{previous.timestamp}",
        payload={
            "previous_quality": previous.mi_overall_quality, "current_quality": current.mi_overall_quality,
            "macro_quality": summary.macro.quality if summary else None,
            "cross_asset_quality": summary.cross_asset.quality if summary else None,
            "news_quality": summary.news.quality if summary else None,
        },
    )]


def high_impact_event_near(previous: Optional[MonitoringSnapshot], current: MonitoringSnapshot,
                            raw: RawEvaluationBundle) -> List[AlertEvent]:
    if previous is None or current.nearby_high_impact_event_key is None:
        return []
    if previous.nearby_high_impact_event_key == current.nearby_high_impact_event_key:
        return []
    event = raw.nearest_event
    if event is None:
        return []
    return [AlertEvent(
        type=AlertType.HIGH_IMPACT_EVENT_NEAR, severity=Severity.WARNING,
        title=f"High-impact event near: {event.event}",
        message=f"{event.event} is scheduled in {event.minutes_until} minutes (importance {event.importance}). "
                f"This reports event risk only — never a prediction of the result.",
        dedup_key=f"HIGH_IMPACT_EVENT_NEAR:{current.nearby_high_impact_event_key}",
        payload={
            "event": event.event, "country": raw.nearest_event_country, "importance": event.importance,
            "event_time": event.event_time, "status": event.status, "minutes_until": event.minutes_until,
            "assets": event.assets, "source": event.source,
        },
    )]


RULES = [
    setup_state_changed, aplus_setup_detected, aplus_setup_invalidated,
    risk_status_changed, market_intelligence_quality_changed, high_impact_event_near,
]


def evaluate_all(previous: Optional[MonitoringSnapshot], current: MonitoringSnapshot,
                  raw: RawEvaluationBundle) -> List[AlertEvent]:
    alerts: List[AlertEvent] = []
    for rule in RULES:
        alerts.extend(rule(previous, current, raw))
    return alerts
