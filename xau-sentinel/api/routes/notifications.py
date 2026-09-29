"""Telegram notification status/test routes (Stage 14) — read-only status
plus a single, clearly-labeled test message. Never returns
TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID in any response. The test endpoint
bypasses monitoring_alerts entirely (it does not touch ai.monitoring at
all) and 404s when Telegram isn't configured.
"""
import config
from fastapi import APIRouter, HTTPException

from ai.notifications import store
from ai.notifications.delivery import CHANNEL
from ai.notifications.providers import get_notification_provider
from ai.notifications.providers.telegram import NotificationConfigError
from ai.notifications.schemas import TelegramStatusOut, TelegramTestResultOut

router = APIRouter(prefix="/api/notifications", tags=["notifications"])

_TEST_MESSAGE = "XAU Sentinel Telegram connection test.\n\nNo trading action was performed."


def _is_configured() -> bool:
    return bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)


@router.get("/telegram/status", response_model=TelegramStatusOut)
def get_telegram_status():
    return TelegramStatusOut(
        enabled=config.TELEGRAM_ENABLED, configured=_is_configured(), provider=config.NOTIFICATION_PROVIDER,
        last_success_at=store.last_success_at(CHANNEL), last_error_at=store.last_error_at(CHANNEL),
    )


@router.post("/telegram/test", response_model=TelegramTestResultOut)
def send_telegram_test():
    if config.NOTIFICATION_PROVIDER == "telegram" and not _is_configured():
        raise HTTPException(status_code=404, detail="Telegram is not configured.")
    try:
        provider = get_notification_provider()
    except NotificationConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    result = provider.send(_TEST_MESSAGE)
    return TelegramTestResultOut(success=result.success, error=result.error)
