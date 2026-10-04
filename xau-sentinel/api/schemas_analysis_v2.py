"""Response contract for GET /api/analysis/v2 (read-only Analysis Engine V2 view).

The response is split into three labelled groups so a reader can always tell
what kind of statement each one is:

    facts           observed from closed candles (prices, structure states, events)
    interpretation  relationships derived from those facts (relations, confluence, context)
    scenarios       conditional "if/then" statements, never predictions

No field carries a probability, a confidence percentage, a score, or a
trading instruction. Missing values are null, never zero.
"""
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


class Freshness(BaseModel):
    generated_at_utc: str
    as_of_utc: Optional[str] = Field(None, description="Open time of the last closed M5 bar")
    m5_bar_close_utc: Optional[str] = None
    age_seconds: Optional[float] = None
    threshold_seconds: float
    stale: bool


class TimeframeSource(BaseModel):
    bars: int
    last_bar_open_utc: Optional[str] = None
    last_bar_closed: Optional[bool] = None


class Source(BaseModel):
    provider: str  # "MT5 live" | "MOCK (synthetic, not market data)" | "unavailable"
    mode: str
    symbol: str
    server_timezone: str
    timeframes: Dict[str, TimeframeSource]


class Dimension(BaseModel):
    state: str
    detail: str


class TimeframeStructure(BaseModel):
    timeframe: str
    state: str
    reason: str
    last_bos: Optional[str] = None
    last_mss: Optional[str] = None
    last_high: Optional[float] = None
    last_low: Optional[float] = None
    last_high_label: Optional[str] = None
    last_low_label: Optional[str] = None


class SweepOut(BaseModel):
    time_utc: Optional[str] = None
    label: str
    level_name: str
    level_price: Optional[float] = None
    kind: str


class VolumeOut(BaseModel):
    relative_volume: Optional[float] = None
    volume_percentile: Optional[float] = None
    state: str


class Observations(BaseModel):
    current_price: Optional[float] = None
    atr_m5: Optional[float] = None
    atr_h1: Optional[float] = None
    atr_percentile_m5: Optional[float] = None
    atr_change_m5: Optional[float] = None
    range_ratio_m5: Optional[float] = None
    displacement_m5: Optional[str] = None
    volume_m5: VolumeOut
    session: Optional[str] = None
    zones: Dict[str, float]
    zone_distances_atr: Dict[str, float]
    recent_high: Optional[float] = None
    recent_low: Optional[float] = None
    sweeps: List[SweepOut]
    equal_levels: List[SweepOut]


class EventOut(BaseModel):
    kind: str
    timeframe: str
    time_utc: str
    direction: Optional[str] = None
    price: Optional[float] = None
    detail: str


class ComponentOut(BaseModel):
    label: str
    price: float
    timeframe: str
    kind: str
    source: str
    note: str


class KeyAreaOut(BaseModel):
    low: float
    high: float
    side: str
    strength_status: str
    strength_reason: str
    relation: str  # BROKEN | INSIDE | REJECTING | APPROACHING | ABOVE | BELOW | UNKNOWN
    distance_atr: Optional[float] = None
    reasons: List[str]
    components: List[ComponentOut]
    events: List[EventOut]


class Lean(BaseModel):
    source: str
    timeframe: str
    lean: str  # bullish | bearish | neutral
    detail: str


class Confluence(BaseModel):
    reference: Optional[str] = None
    reference_reason: str
    supporting: List[Lean]
    contradicting: List[Lean]
    neutral: List[Lean]
    bullish: List[Lean]
    bearish: List[Lean]
    cross_timeframe_conflicts: List[str]


class Context(BaseModel):
    direction: Dimension
    structure: Dict[str, Dimension]
    regime: Dimension
    volatility: Dimension
    volume: Dimension
    liquidity: Dimension
    momentum: Dimension
    session: Dimension
    price_location: Dimension


class ScenarioOut(BaseModel):
    name: str
    direction: Optional[str] = None
    condition: str
    supporting_conditions: List[str]
    confirmation_requirements: List[str]
    invalidation_conditions: List[str]
    key_area_refs: List[str]
    event_refs: List[str]
    disclaimer: str


class Facts(BaseModel):
    observations: Optional[Observations] = None
    structure: Dict[str, TimeframeStructure] = Field(default_factory=dict)


class Interpretation(BaseModel):
    context: Optional[Context] = None
    key_areas: List[KeyAreaOut] = Field(default_factory=list)
    confluence: Optional[Confluence] = None
    narrative: List[str] = Field(default_factory=list)


class AnalysisV2Out(BaseModel):
    status: str  # OK | STALE | INSUFFICIENT_DATA | UNAVAILABLE
    status_reason: str
    freshness: Freshness
    source: Source
    notes: List[str]
    data_issues: List[str]
    facts: Facts
    events: List[EventOut]
    interpretation: Interpretation
    scenarios: List[ScenarioOut]
