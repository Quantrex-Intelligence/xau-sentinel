"""Pydantic contracts for historical setup similarity — typed views of what
ai/similarity/engine.py already produces, never a place new data gets
invented. Deliberately has no "confidence"/"probability" field anywhere —
see ai/similarity/scoring.py's docstring: this is feature similarity, never
a win-probability estimate."""
from typing import List, Optional

from pydantic import BaseModel


class SetupFeaturesOut(BaseModel):
    direction: Optional[str] = None
    h4_structure: Optional[str] = None
    h1_structure: Optional[str] = None
    m15_structure: Optional[str] = None
    m5_structure: Optional[str] = None
    regime: Optional[str] = None
    liquidity_kind: Optional[str] = None
    mss_direction: Optional[str] = None
    displacement: Optional[str] = None
    session: Optional[str] = None
    planned_rr: Optional[float] = None


class OutcomeOut(BaseModel):
    status: str
    result: Optional[str] = None
    r_multiple: Optional[float] = None
    pnl: Optional[float] = None
    duration_minutes: Optional[float] = None
    entry_date: Optional[str] = None
    entry_time: Optional[str] = None


class SimilarSetupOut(BaseModel):
    trade_id: int
    similarity: float
    entry_snapshot: SetupFeaturesOut
    outcome: OutcomeOut
    matched_features: List[str]
    different_features: List[str]


class SimilarityResultOut(BaseModel):
    query_features: SetupFeaturesOut
    matches: List[SimilarSetupOut]
    considered_count: int
    excluded_count: int
