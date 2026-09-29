"""Pydantic contract for the monitoring alert API — a typed mirror of
ai/monitoring/models.py::AlertEvent, never a place new data gets
invented."""
from typing import Any, Dict, Optional

from pydantic import BaseModel


class AlertEventOut(BaseModel):
    id: int
    type: str
    severity: str
    title: str
    message: str
    symbol: str
    payload: Dict[str, Any]
    dedup_key: str
    acknowledged: bool
    timestamp: str


class AcknowledgeResultOut(BaseModel):
    acknowledged: bool
    count: Optional[int] = None
