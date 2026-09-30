"""Data shapes for Telegram alert delivery (Stage 14). Pure data only —
no HTTP/formatting/persistence logic lives here.

Delivery status answers a DIFFERENT question than a monitoring alert's own
existence: Stage 13's ai/monitoring/models.py::AlertEvent answers "should
this alert exist?"; AlertDelivery below answers "have I already delivered
THIS alert to THIS channel?" The two are deliberately never merged into
one table (see ai/notifications/store.py).
"""
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    SENT = "SENT"
    FAILED = "FAILED"


@dataclass
class AlertDelivery:
    alert_id: int
    channel: str  # "telegram"
    status: DeliveryStatus = DeliveryStatus.PENDING
    attempt_count: int = 0
    last_attempt_at: Optional[str] = None
    sent_at: Optional[str] = None
    error: Optional[str] = None
    # Whether the MOST RECENT failure was retryable — a non-retryable
    # failure (bad token/chat id) is terminal regardless of attempt_count,
    # so this must be persisted, not just returned transiently from
    # DeliveryResult (see ai/notifications/delivery.py::attempt_deliveries()).
    retryable: bool = True
    id: Optional[int] = None
    created_at: Optional[str] = None


@dataclass
class DeliveryResult:
    """What a NotificationProvider.send() call returns — never raises for
    an ordinary delivery failure (auth error, timeout, rate limit); only a
    programming error should raise. `retryable` is what lets the delivery
    worker distinguish "try again later" from "this will never succeed
    without a config change" (see ai/notifications/providers/telegram.py)."""
    success: bool
    error: Optional[str] = None
    retryable: bool = True
    # Stage 23B (VAL-034): the provider's own "don't retry before N
    # seconds" instruction (Telegram's 429 `parameters.retry_after`), when
    # it gave one. None means no instruction — the worker's normal backoff
    # applies.
    retry_after_seconds: Optional[float] = None
