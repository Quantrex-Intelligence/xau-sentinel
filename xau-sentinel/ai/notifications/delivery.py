"""Telegram delivery worker (Stage 14). Consumes ai.monitoring.store's
EXISTING, unmodified list_alerts() — never re-runs setup detection, the A+
evaluator, Market Intelligence, or risk calculations to decide what to
send; monitoring_alerts is the sole source for what gets delivered (spec
section 5's explicit requirement).

Two idempotent phases per cycle, mirroring ai/monitoring/engine.py's own
"synchronous, testable core + thin async wrapper" shape:
  1. discover_new_alerts() — every monitoring alert with no delivery row
     yet for this channel gets a new PENDING row (a repeat discovery is a
     silent no-op, enforced by store.py's UNIQUE(alert_id, channel)).
  2. attempt_deliveries() — every PENDING row, and every FAILED row that
     is still retryable, within its backoff window, and hasn't exhausted
     TELEGRAM_MAX_RETRIES, gets one delivery attempt.

CHANNEL is fixed at "telegram" for this stage — the one channel Stage 14
implements — kept as a named constant rather than hardcoded inline so a
future channel is an additive change, not a search-and-replace.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import config
from ai.monitoring import store as monitoring_store
from ai.notifications import store
from ai.notifications.formatter import format_alert
from ai.notifications.models import AlertDelivery, DeliveryStatus
from ai.notifications.providers import get_notification_provider
from ai.notifications.providers.telegram import NotificationConfigError

CHANNEL = "telegram"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def discover_new_alerts() -> int:
    alerts = monitoring_store.list_alerts(limit=100)
    delivered_ids = store.get_delivered_alert_ids(CHANNEL)
    created = 0
    for alert in alerts:
        if alert.id in delivered_ids:
            continue
        if store.create_pending(alert.id, CHANNEL) is not None:
            created += 1
    return created


def _is_due(delivery: AlertDelivery, now: datetime) -> bool:
    if delivery.status == DeliveryStatus.PENDING:
        return True
    # FAILED: only due once its backoff window has elapsed.
    last_attempt = _parse_iso(delivery.last_attempt_at)
    if last_attempt is None:
        return True
    backoff = timedelta(seconds=config.TELEGRAM_RETRY_BACKOFF_SECONDS * max(delivery.attempt_count, 1))
    return now >= last_attempt + backoff


def attempt_deliveries() -> List[AlertDelivery]:
    """Returns the deliveries actually attempted this cycle (sent or
    freshly failed) — an empty list when nothing was due."""
    try:
        provider = get_notification_provider()
    except NotificationConfigError:
        # Enabled but not configured — a systemic config problem, not a
        # per-alert failure. Skip the cycle silently rather than marking
        # every pending delivery FAILED for a reason no retry can fix.
        return []

    now = _now()
    attempted: List[AlertDelivery] = []
    for delivery in store.list_pending_and_retryable_failed(CHANNEL):
        if delivery.status == DeliveryStatus.FAILED and delivery.attempt_count >= config.TELEGRAM_MAX_RETRIES:
            continue
        if not _is_due(delivery, now):
            continue

        alert = monitoring_store.get_by_id(delivery.alert_id)
        if alert is None:
            continue  # the underlying alert was purged by retention — nothing to send

        message = format_alert(alert)
        result = provider.send(message)
        if result.success:
            updated = store.mark_sent(delivery.id)
        else:
            updated = store.mark_failed(
                delivery.id, result.error or "Delivery failed for an unknown reason.", retryable=result.retryable,
            )
        attempted.append(updated)
    return attempted


def run_delivery_cycle() -> List[AlertDelivery]:
    discover_new_alerts()
    return attempt_deliveries()


async def run_forever() -> None:
    while True:
        try:
            run_delivery_cycle()
        except Exception:  # noqa: BLE001 - one bad cycle must never kill the loop
            pass
        await asyncio.sleep(config.TELEGRAM_POLL_INTERVAL_SECONDS)
