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

Stage 23B keeps three pieces of in-process state (the same "module-level,
resets on restart" pattern as ai/monitoring/engine.py's `_last_snapshot`):
  - `_worker_started_at` (VAL-022): discovery only picks up alerts created
    after the worker started, so enabling Telegram never floods the chat
    with old alerts.
  - `_sent_unrecorded` (VAL-020): deliveries Telegram accepted but whose
    SENT write then failed; the next cycle retries the write, never the send.
  - `_rate_limited_until` (VAL-034): the channel-wide pause a Telegram 429
    `retry_after` asked for.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Set

import config
from ai.monitoring import store as monitoring_store
from ai.notifications import store
from ai.notifications.formatter import format_alert
from ai.notifications.models import AlertDelivery, DeliveryStatus
from ai.notifications.providers import get_notification_provider
from ai.notifications.providers.telegram import NotificationConfigError

CHANNEL = "telegram"

logger = logging.getLogger(__name__)

_worker_started_at: Optional[datetime] = None
_sent_unrecorded: Set[int] = set()
_rate_limited_until: Optional[datetime] = None


def reset_state() -> None:
    """Test-only escape hatch (mirrors ai/monitoring/engine.py::reset_state())."""
    global _worker_started_at, _rate_limited_until
    _worker_started_at = None
    _rate_limited_until = None
    _sent_unrecorded.clear()


def mark_worker_started(now: Optional[datetime] = None) -> None:
    """Stage 23B (VAL-022): records when the delivery worker came up; alerts
    created before this are history, not news, and are never queued."""
    global _worker_started_at
    _worker_started_at = now or _now()


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
    """Stage 23B (VAL-022): once the worker has started, only alerts
    created at or after that moment are queued. Before, turning Telegram on
    (or restarting after downtime) queued up to 100 historical alerts,
    stale A+ setups included, with nothing marking them as old. Alerts
    raised while delivery was off stay visible in the app; they are just
    never sent to Telegram."""
    alerts = monitoring_store.list_alerts(limit=100)
    delivered_ids = store.get_delivered_alert_ids(CHANNEL)
    created = 0
    for alert in alerts:
        if alert.id in delivered_ids:
            continue
        if _worker_started_at is not None:
            created_at = _parse_iso(alert.timestamp)
            if created_at is None or created_at < _worker_started_at:
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


def _record_sent(delivery_id: int) -> Optional[AlertDelivery]:
    """Stage 23B (VAL-020): the message is already in the chat, so a failed
    SENT write must never lead to a resend. The id is remembered and the
    write retried next cycle, instead of leaving a PENDING row that the
    next cycle would send again."""
    try:
        updated = store.mark_sent(delivery_id)
    except Exception:  # noqa: BLE001 - a DB hiccup must never trigger a duplicate message
        logger.exception("Delivery %s was sent but could not be marked SENT; will retry the write", delivery_id)
        _sent_unrecorded.add(delivery_id)
        return None
    _sent_unrecorded.discard(delivery_id)
    return updated


def _attempt_one(provider, delivery: AlertDelivery, now: datetime) -> Optional[AlertDelivery]:
    global _rate_limited_until
    alert = monitoring_store.get_by_id(delivery.alert_id)
    if alert is None:
        return None  # the underlying alert was purged by retention — nothing to send

    message = format_alert(alert)
    try:
        result = provider.send(message)
    except Exception as exc:  # noqa: BLE001 - Stage 23B (VAL-020), see attempt_deliveries()
        # Only the exception TYPE is persisted, never its text: some httpx
        # exceptions embed the request URL, which carries the bot token.
        logger.error("Notification provider raised %s for delivery %s", type(exc).__name__, delivery.id)
        return store.mark_failed(
            delivery.id, f"Delivery failed with an unexpected {type(exc).__name__}.", retryable=True,
        )

    if result.success:
        return _record_sent(delivery.id)
    if result.retry_after_seconds is not None:
        _rate_limited_until = now + timedelta(seconds=result.retry_after_seconds)
    return store.mark_failed(
        delivery.id, result.error or "Delivery failed for an unknown reason.", retryable=result.retryable,
    )


def attempt_deliveries() -> List[AlertDelivery]:
    """Returns the deliveries actually attempted this cycle (sent or
    freshly failed) — an empty list when nothing was due.

    Stage 23B hardening:
      - VAL-020: each delivery is isolated. A provider exception type
        send() doesn't classify (e.g. httpx.InvalidURL, which is not an
        httpx.HTTPError) now marks just that delivery FAILED, so
        TELEGRAM_MAX_RETRIES still applies. Before, it escaped and aborted
        the whole cycle, every cycle, for every queued item. A failed SENT
        write is retried as a write, never as a resend.
      - VAL-034: a 429's `retry_after` pauses the whole channel until it
        expires. Telegram's rate limit is per bot, not per message, so
        sending the rest of the queue would only burn every other
        delivery's retries on further 429s."""
    global _rate_limited_until
    now = _now()
    if _rate_limited_until is not None:
        if now < _rate_limited_until:
            return []
        _rate_limited_until = None

    try:
        provider = get_notification_provider()
    except NotificationConfigError:
        # Enabled but not configured — a systemic config problem, not a
        # per-alert failure. Skip the cycle silently rather than marking
        # every pending delivery FAILED for a reason no retry can fix.
        return []

    attempted: List[AlertDelivery] = []
    for delivery in store.list_pending_and_retryable_failed(CHANNEL):
        if delivery.id in _sent_unrecorded:
            _record_sent(delivery.id)  # already delivered — finish the bookkeeping, never resend
            continue
        if delivery.status == DeliveryStatus.FAILED and delivery.attempt_count >= config.TELEGRAM_MAX_RETRIES:
            continue
        if not _is_due(delivery, now):
            continue

        try:
            updated = _attempt_one(provider, delivery, now)
        except Exception:  # noqa: BLE001 - one bad delivery (e.g. a failed DB write) must not block the rest
            logger.exception("Delivery %s failed unexpectedly; continuing with the rest of the queue", delivery.id)
            continue
        if updated is not None:
            attempted.append(updated)
        if _rate_limited_until is not None:
            break  # VAL-034: rate-limited — the rest of the queue waits out retry_after
    return attempted


def run_delivery_cycle() -> List[AlertDelivery]:
    discover_new_alerts()
    return attempt_deliveries()


async def run_forever() -> None:
    """Stage 23B: the cycle runs in a worker thread (VAL-021), because
    SQLite and the blocking Telegram HTTP call would otherwise stall the
    event loop. A failed cycle is logged (VAL-033), not swallowed."""
    mark_worker_started()
    while True:
        try:
            await asyncio.to_thread(run_delivery_cycle)
        except Exception:  # noqa: BLE001 - one bad cycle must never kill the loop
            logger.exception("Notification delivery cycle failed; retrying in %ss",
                             config.TELEGRAM_POLL_INTERVAL_SECONDS)
        await asyncio.sleep(config.TELEGRAM_POLL_INTERVAL_SECONDS)
