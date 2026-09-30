"""Pydantic contracts for the notifications API — never carries a secret
field (bot_token/chat_id are configuration, not response data)."""
from typing import Optional

from pydantic import BaseModel


class TelegramStatusOut(BaseModel):
    enabled: bool
    configured: bool
    provider: str
    # A real monitoring alert was delivered (alert_deliveries only).
    last_success_at: Optional[str] = None
    last_error_at: Optional[str] = None
    # DEP-011: the last successful POST /telegram/test for the CURRENT
    # provider. Kept separate from last_success_at on purpose: a test
    # message proves the channel works, not that any alert was delivered.
    last_test_success_at: Optional[str] = None


class TelegramTestResultOut(BaseModel):
    success: bool
    error: Optional[str] = None
