"""Offline notification provider — required by the spec so no test or E2E
run ever needs a real Telegram bot (mirrors ai/providers/mock_provider.py's
role for the LLM). Records every message it was asked to send, in order,
so tests can assert on exactly what would have been delivered.
"""
from typing import List

from ai.notifications.models import DeliveryResult
from ai.notifications.providers.base import NotificationProvider


class MockNotificationProvider(NotificationProvider):
    name = "mock"

    def __init__(self):
        self.sent_messages: List[str] = []

    def send(self, message: str) -> DeliveryResult:
        self.sent_messages.append(message)
        return DeliveryResult(success=True)
