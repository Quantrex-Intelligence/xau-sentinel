"""Real-Time Monitoring engine (Stage 13): periodically builds a compact
MonitoringSnapshot from the SAME deterministic engines every other route
already calls, diffs it against the previous cycle, and turns any genuine
transition into a persisted, deduplicated AlertEvent via ai/monitoring/rules.py.

Structural guarantee, not just a behavioral one: this module (and
ai/monitoring/rules.py) never imports ai.providers, never calls
get_provider()/.chat(), and never calls
ai.strategy.evaluator.evaluate_current_setup()/attach_llm_explanation() —
only the pure evaluate_deterministic(). There is no code path from here to
any LLM provider at all (see tests/test_monitoring_engine.py's structural
test). This is what makes "the LLM must NOT decide whether an alert
condition exists" true by construction.

Module-level `_last_snapshot` is the ONLY state this engine keeps between
cycles — an in-process variable, not Redis/a message broker/anything else
(matches Stage 11's cache.py: no infrastructure beyond a single local
process for a single-user tool). It resets to None on every server
restart; the first cycle after a reset only establishes the baseline and
never generates an alert, so a restart never re-announces the current
state as if it just changed.
"""
import asyncio
from datetime import datetime, timezone
from typing import List, Optional

import config
from analysis.setup import detect_setup
from ai.market_intelligence import context as mi_context
from ai.market_intelligence.quality import build_event_risk_context, build_intelligence_summary
from ai.monitoring import rules, store
from ai.monitoring.models import AlertEvent, MonitoringSnapshot, RawEvaluationBundle
from ai.strategy.evaluator import evaluate_deterministic
from mt5 import market_data
from risk import settings_store
from risk.fundednext import compute_status
from risk.models import AccountType, Phase

_last_snapshot: Optional[MonitoringSnapshot] = None


def reset_state() -> None:
    """Test-only escape hatch (mirrors ai/market_intelligence/providers/cache.py::clear())
    — production code never needs to call this."""
    global _last_snapshot
    _last_snapshot = None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_bundle(now: datetime) -> RawEvaluationBundle:
    candles = market_data.get_all_candles(300)
    setup_result = detect_setup(candles)

    fn_settings = settings_store.get_settings()
    fn_status = compute_status(
        AccountType(fn_settings["account_type"]), Phase(fn_settings["phase"]),
        consistency_enabled=fn_settings["consistency_enabled"],
    )
    strategy_result = evaluate_deterministic(candles, fn_status, now=now)

    mi_ctx = mi_context.build_market_intelligence_context()
    intelligence_summary = build_intelligence_summary(mi_ctx, now)

    high_events = [e for e in mi_ctx.events if e.importance == "HIGH"]
    risk_items = build_event_risk_context(high_events, now)
    nearest = next(
        (i for i in risk_items if i.status == "UPCOMING" and 0 <= i.minutes_until <= config.MONITORING_EVENT_WARNING_MINUTES),
        None,
    )
    nearest_country = None
    if nearest is not None:
        matching = next(
            (e for e in high_events if e.name == nearest.event and e.scheduled_at == nearest.event_time), None,
        )
        nearest_country = matching.country if matching else None

    return RawEvaluationBundle(
        setup_result=setup_result, strategy_result=strategy_result, fundednext_status=fn_status,
        intelligence_summary=intelligence_summary, nearest_event=nearest, nearest_event_country=nearest_country,
    )


def _to_snapshot(bundle: RawEvaluationBundle, now: datetime) -> MonitoringSnapshot:
    nearest_key = None
    if bundle.nearest_event is not None:
        nearest_key = f"{bundle.nearest_event.event}:{bundle.nearest_event.event_time}"

    return MonitoringSnapshot(
        setup_state=bundle.setup_result.state, setup_direction=bundle.setup_result.direction,
        aplus_rating=bundle.strategy_result.rating.value, aplus_direction=bundle.strategy_result.direction,
        risk_safety_level=bundle.fundednext_status.safety_level.value,
        mi_overall_quality=bundle.intelligence_summary.overall,
        nearby_high_impact_event_key=nearest_key, timestamp=now.isoformat(),
    )


def run_monitoring_cycle() -> List[AlertEvent]:
    """Synchronous, side-effect-bounded: fetches current state, diffs
    against the previous cycle, persists any newly detected alerts, purges
    old ones, and returns exactly the alerts created THIS cycle (an empty
    list on the baseline-establishing first cycle, or any cycle with no
    genuine transition)."""
    global _last_snapshot
    now = _now()

    bundle = _build_bundle(now)
    current = _to_snapshot(bundle, now)
    previous = _last_snapshot

    candidate_alerts = rules.evaluate_all(previous, current, bundle)

    created: List[AlertEvent] = []
    for alert in candidate_alerts:
        persisted = store.create_alert(alert)
        if persisted is not None:
            created.append(persisted)

    store.purge_older_than(config.ALERT_RETENTION_DAYS)
    _last_snapshot = current
    return created


async def run_forever() -> None:
    while True:
        try:
            run_monitoring_cycle()
        except Exception:  # noqa: BLE001 - one bad cycle (e.g. a transient MT5/HTTP failure) must never kill the loop
            pass
        await asyncio.sleep(config.MONITORING_INTERVAL_SECONDS)
