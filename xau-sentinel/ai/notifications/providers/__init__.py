"""Notification provider factory — mirrors ai/providers/__init__.py's
exact pattern. Picks the provider named by config.NOTIFICATION_PROVIDER
unless the caller overrides it explicitly (tests/E2E do this to force the
mock provider regardless of the environment)."""
from typing import Optional

import config
from ai.notifications.providers.base import NotificationProvider
from ai.notifications.providers.mock import MockNotificationProvider

__all__ = ["NotificationProvider", "get_notification_provider"]

_NON_TELEGRAM_PROVIDERS = {"mock": MockNotificationProvider}


def get_notification_provider(name: Optional[str] = None) -> NotificationProvider:
    provider_name = (name or config.NOTIFICATION_PROVIDER or "telegram").strip().lower()

    if provider_name == "telegram":
        from ai.notifications.providers.telegram import TelegramNotificationProvider
        return TelegramNotificationProvider()

    provider_cls = _NON_TELEGRAM_PROVIDERS.get(provider_name)
    if provider_cls is None:
        raise ValueError(
            f"Unknown NOTIFICATION_PROVIDER '{provider_name}'. Valid options: telegram, mock."
        )
    return provider_cls()
