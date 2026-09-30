"""Telegram Bot API client — a thin sendMessage wrapper, isolated here so
every Telegram-specific detail (the API shape, error classification,
retryability) lives in exactly one file. httpx is already a project
dependency (api/requirements.txt) — no new one added for this.

SECURITY-CRITICAL: the bot token is embedded in the request URL
(https://api.telegram.org/bot<TOKEN>/sendMessage). httpx's own exceptions
(HTTPStatusError in particular) embed the full request URL in their
default string representation — every exception here is caught and a
NEW, hand-built error string is raised/returned instead (status code +
Telegram's own JSON `description` field only), so the token can never
leak into a persisted `alert_deliveries.error` row, a log line, or an API
response. tests/test_notifications_providers.py asserts this directly.
"""
from typing import Optional

import httpx

import config
from ai.notifications.models import DeliveryResult
from ai.notifications.providers.base import NotificationProvider

_API_BASE = "https://api.telegram.org"
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class NotificationConfigError(Exception):
    """Telegram is enabled but not configured (missing bot token/chat id).
    Never includes the token (there isn't one to include)."""


def _retry_after_seconds(response: httpx.Response) -> Optional[float]:
    """Stage 23B (VAL-034): how long Telegram asked us to wait on a 429 —
    its JSON `parameters.retry_after` first, then the standard Retry-After
    header. None when neither is present or parseable (the worker's fixed
    backoff then applies, as before)."""
    try:
        body = response.json()
    except ValueError:
        body = None
    candidates = []
    if isinstance(body, dict) and isinstance(body.get("parameters"), dict):
        candidates.append(body["parameters"].get("retry_after"))
    headers = getattr(response, "headers", None) or {}
    candidates.append(headers.get("Retry-After"))
    for value in candidates:
        try:
            seconds = float(value)
        except (TypeError, ValueError):
            continue
        if seconds >= 0:
            return seconds
    return None


def _telegram_description(response: httpx.Response) -> Optional[str]:
    try:
        body = response.json()
    except ValueError:
        return None
    if isinstance(body, dict):
        return body.get("description")
    return None


class TelegramNotificationProvider(NotificationProvider):
    name = "telegram"

    def __init__(self):
        if not config.TELEGRAM_BOT_TOKEN or not config.TELEGRAM_CHAT_ID:
            raise NotificationConfigError(
                "TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must both be set. See .env.example, "
                "or set NOTIFICATION_PROVIDER=mock to use the offline provider instead."
            )
        self._token = config.TELEGRAM_BOT_TOKEN
        self._chat_id = config.TELEGRAM_CHAT_ID

    def send(self, message: str) -> DeliveryResult:
        url = f"{_API_BASE}/bot{self._token}/sendMessage"
        try:
            response = httpx.post(
                url, json={"chat_id": self._chat_id, "text": message},
                timeout=config.TELEGRAM_HTTP_TIMEOUT_SECONDS,
            )
        except httpx.TimeoutException:
            return DeliveryResult(success=False, error="Telegram request timed out.", retryable=True)
        except httpx.HTTPError:
            # Any other httpx transport-level failure (connection refused,
            # DNS failure, etc.) — never the raw exception text, which some
            # httpx exceptions populate with the request URL.
            return DeliveryResult(success=False, error="Telegram request failed (network error).", retryable=True)

        if response.status_code == 200:
            return DeliveryResult(success=True)

        description = _telegram_description(response) or "no further detail"
        error = f"Telegram API returned HTTP {response.status_code}: {description}"
        retryable = response.status_code in _RETRYABLE_STATUS_CODES
        retry_after = _retry_after_seconds(response) if response.status_code == 429 else None
        return DeliveryResult(success=False, error=error, retryable=retryable, retry_after_seconds=retry_after)
