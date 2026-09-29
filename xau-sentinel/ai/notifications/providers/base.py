"""Notification provider abstraction — mirrors ai/providers/base.py's exact
shape (one ABC, config-keyed factory in __init__.py) so a real channel can
be swapped for a mock one in tests without touching the delivery worker.

send() never raises for an ordinary delivery failure (auth rejected,
timeout, rate limit) — it returns a DeliveryResult, so the delivery worker
can persist attempt_count/error/retryable without a try/except around
every provider. A raised exception here would mean a genuine programming
error, not "Telegram was unreachable."
"""
from abc import ABC, abstractmethod

from ai.notifications.models import DeliveryResult


class NotificationProvider(ABC):
    name: str = "base"

    @abstractmethod
    def send(self, message: str) -> DeliveryResult:
        raise NotImplementedError
