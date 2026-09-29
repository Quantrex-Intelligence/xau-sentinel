"""Pydantic contracts for the notifications API — never carries a secret
field (bot_token/chat_id are configuration, not response data)."""
from typing import Optional

from pydantic import BaseModel


class TelegramStatusOut(BaseModel):
    enabled: bool
    configured: bool
    provider: str
    last_success_at: Optional[str] = None
    last_error_at: Optional[str] = None


class TelegramTestResultOut(BaseModel):
    success: bool
    error: Optional[str] = None
