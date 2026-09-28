"""Typed shapes for the tool layer — mirrors the rest of ai/'s convention
(schemas are typed views of what the code already produces, never a place
new data gets invented)."""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from pydantic import BaseModel


@dataclass
class ToolResult:
    """What every tool handler returns, before executor.py serializes it to
    a plain dict for the provider. `data_available=False` is how a tool
    degrades (no connection, no matching trade, empty knowledge base) — it
    is never allowed to fabricate a value instead."""
    data_available: bool
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: Optional[str] = None
    reason: Optional[str] = None
    source: Optional[str] = None  # which deterministic engine/module this traces to

    def to_dict(self) -> dict:
        out: Dict[str, Any] = {
            "data_available": self.data_available,
            "timestamp": self.timestamp,
            "source": self.source,
        }
        if self.reason is not None:
            out["reason"] = self.reason
        out.update(self.data)
        return out


class ToolUsageOut(BaseModel):
    """One tool call made during a chat turn — the UI's "Tools used"
    transparency panel renders this list directly, mirroring how
    KnowledgeSourceOut already works for Stage 5's RAG citations."""
    name: str
    label: str
    data_available: bool
    timestamp: Optional[str] = None
