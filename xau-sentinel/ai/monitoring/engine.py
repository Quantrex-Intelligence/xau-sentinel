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

Module-level `_last_snapshot` is the baseline this engine diffs against
— an in-process variable, not Redis/a message broker/anything else
(matches Stage 11's cache.py: no infrastructure beyond a single local
process for a single-user tool). DEP-004: every time it advances it is
also mirrored to a one-row SQLite table (ai/monitoring/store.py's
`monitoring_baseline`), so the first cycle after a restart diffs against
the pre-restart state and a transition that happened during the downtime
is still alerted. That persisted baseline is only trusted if it was saved
within BASELINE_MAX_AGE; an older (or missing/corrupt) one is ignored and
the first cycle only establishes a baseline, never alerting, as before.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import config
from analysis.setup import detect_setup
from ai.market_intelligence import context as mi_context
from ai.market_intelligence.quality import build_event_risk_context, build_intelligence_summary
from ai.monitoring import rules, store
from ai.monitoring.models import AlertEvent, MonitoringSnapshot, RawEvaluationBundle
from ai.strategy.evaluator import evaluate_deterministic
from mt5 import connection, market_data
from risk import settings_store
from risk.fundednext import compute_status
from risk.models import AccountType, Phase

logger = logging.getLogger(__name__)

_last_snapshot: Optional[MonitoringSnapshot] = None

# DEP-004: how old a persisted baseline may be and still be diffed against
# after a restart. A restart/redeploy/crash-recovery takes seconds to a few
# minutes; anything older than this means the process was down long enough
# that "A before, B now" is no longer a transition anyone needs to hear
# about as if it just happened (a stale A+ -> INVALID, yesterday's risk
# level), so the conservative choice is to re-baseline silently, exactly as
# before DEP-004. A module constant rather than a config value on purpose.
BASELINE_MAX_AGE = timedelta(minutes=10)


def reset_state() -> None:
    """Test-only escape hatch (mirrors ai/market_intelligence/providers/cache.py::clear())
    — production code never needs to call this. Simulates a process
    restart: the in-memory baseline is dropped, and the next cycle will try
    the persisted one again (see _restore_baseline())."""
    global _last_snapshot
    _last_snapshot = None


def _restore_baseline(now: datetime) -> Optional[MonitoringSnapshot]:
    """DEP-004: the first cycle of a process diffs against the persisted
    pre-restart snapshot, but only if it was saved within BASELINE_MAX_AGE
    of `now`. Stale, future-dated (clock skew), missing, corrupt or
    unreadable baselines all return None, i.e. the first cycle only
    establishes a baseline and never alerts, same as before DEP-004."""
    try:
        loaded = store.load_baseline()
    except Exception:  # noqa: BLE001 - a DB problem must never block monitoring
        logger.exception("Could not read the persisted monitoring baseline; starting fresh")
        return None
    if loaded is None:
        return None
    snapshot, saved_at = loaded
    age = now - saved_at
    if age < timedelta(0) or age > BASELINE_MAX_AGE:
        logger.info("Ignoring persisted monitoring baseline saved at %s (age %s)", saved_at.isoformat(), age)
        return None
    return snapshot


def _set_baseline(snapshot: MonitoringSnapshot) -> None:
    """Advances the in-memory baseline and mirrors it to the persisted row.
    A persistence failure is logged and otherwise ignored: the in-memory
    baseline is authoritative for this process, so the cycle carries on."""
    global _last_snapshot
    _last_snapshot = snapshot
    try:
        store.save_baseline(snapshot)
    except Exception:  # noqa: BLE001 - persistence is best-effort (DEP-004)
        logger.exception("Could not persist the monitoring baseline; keeping it in memory only")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _build_bundle(now: datetime) -> RawEvaluationBundle:
    # OP-001 (docs/validation/OPERATIONAL_ISSUES.md): the monitoring loop is
    # its own independent MT5 consumer and previously relied entirely on a
    # UI/API request having connected it first (app.py / api/snapshot.py's
    # own copy of this same idiom) — on a cold start with nobody using the
    # dashboard, every cycle failed with "MT5 not connected" indefinitely.
    # Checked every cycle, not just once at startup, so a genuine mid-session
    # disconnect self-heals too, not only the first-cycle case.
    if config.IS_LIVE and not connection.is_connected():
        connection.connect()
    candles = market_data.get_all_candles(300)
    # Stage 23B: the same cycle `now` evaluate_deterministic() gets below,
    # so both engines judge candle closure/staleness against one clock.
    setup_result = detect_setup(candles, now=now)

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
        aplus_candidate_key=bundle.strategy_result.candidate_sweep_time,
    )


def run_monitoring_cycle() -> List[AlertEvent]:
    """Synchronous, side-effect-bounded: fetches current state, diffs
    against the previous cycle, persists any newly detected alerts, purges
    old ones, and returns exactly the alerts created THIS cycle (an empty
    list on the baseline-establishing first cycle, or any cycle with no
    genuine transition).

    Stage 23B (VAL-019): the baseline advances as soon as every candidate
    alert is persisted, BEFORE the retention purge, so a failing purge can
    never pin the diff to a stale baseline. If an insert itself fails, the
    baseline is left alone and the next cycle re-detects the transition —
    but rules.py keys the transition on that unchanged baseline's
    timestamp, so already-inserted alerts are deduplicated and only the
    missing ones are created."""
    now = _now()

    bundle = _build_bundle(now)
    current = _to_snapshot(bundle, now)
    # DEP-004: with no in-memory baseline (a fresh process, or every
    # earlier cycle failed before advancing it), fall back to the persisted
    # one. A retry after a failed first cycle restores the SAME row, so the
    # baseline-timestamp dedup keys (VAL-019) still absorb re-detections.
    previous = _last_snapshot if _last_snapshot is not None else _restore_baseline(now)

    candidate_alerts = rules.evaluate_all(previous, current, bundle)

    created: List[AlertEvent] = []
    for alert in candidate_alerts:
        persisted = store.create_alert(alert)
        if persisted is not None:
            created.append(persisted)
    _set_baseline(current)

    store.purge_older_than(config.ALERT_RETENTION_DAYS)
    return created


async def run_forever() -> None:
    """Stage 23B: the cycle runs in a worker thread (VAL-021) — it does
    blocking MT5 reads, HTTP calls and SQLite writes, which would otherwise
    freeze every other async handler (the WebSocket included) for the whole
    cycle. A failed cycle is logged with its traceback (VAL-033) rather
    than swallowed silently, and the loop carries on."""
    while True:
        try:
            await asyncio.to_thread(run_monitoring_cycle)
        except Exception:  # noqa: BLE001 - one bad cycle (e.g. a transient MT5/HTTP failure) must never kill the loop
            logger.exception("Monitoring cycle failed; retrying in %ss", config.MONITORING_INTERVAL_SECONDS)
        await asyncio.sleep(config.MONITORING_INTERVAL_SECONDS)
