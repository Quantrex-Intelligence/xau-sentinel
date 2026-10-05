"""Typed evidence and key-area models for Analysis Engine V2."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple

EVIDENCE_INSUFFICIENT = "INSUFFICIENT_SAMPLE"


@dataclass(frozen=True)
class Evidence:
    """One factual observation with the metadata needed to audit it."""
    timeframe: str  # "M5" | "M15" | "H1" | "H4" | "D1"
    timestamp: datetime  # UTC open time of the bar the evidence refers to
    kind: str  # e.g. "PDH", "H1_SWING_HIGH", "SWEEP_LOW", "EQUAL_HIGHS"
    value: float  # price level (or measured value) the evidence refers to
    source: str  # module that produced it, e.g. "analysis.zones"
    note: str = ""


@dataclass(frozen=True)
class KeyComponent:
    """One logical reference at one price. `evidence` is the primary provenance.
    `corroborations` holds other records of the SAME level (same timeframe and
    price) from other sources or with other statuses, such as "broken". They are
    kept so no provenance is lost, but they are not counted as separate evidence."""
    label: str  # e.g. "PDH", "H1 swing high", "equal highs"
    price: float
    evidence: Evidence
    corroborations: Tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class KeyArea:
    """A merged price region built from several independent references."""
    low: float
    high: float
    components: Tuple[KeyComponent, ...]
    side: str  # "RESISTANCE" | "SUPPORT" | "MIXED"
    strength_status: str  # "HIGH" | "MODERATE" | "LOW" | EVIDENCE_INSUFFICIENT
    strength_reason: str  # explicit evidence behind the status

    @property
    def mid(self) -> float:
        return (self.low + self.high) / 2

    @property
    def width(self) -> float:
        return self.high - self.low

    @property
    def distinct_sources(self) -> int:
        return len({c.evidence.source + ":" + c.label for c in self.components})


@dataclass(frozen=True)
class Relationship:
    """Where price sits relative to a key area, in ATR units."""
    area: KeyArea
    distance_atr: float  # 0 inside the area; positive above, negative below
    relation: str  # "INSIDE" | "APPROACHING" | "ABOVE" | "BELOW" | "FAR"
