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
    adx_h1: Optional[float] = None  # trend strength only, no direction
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
    # Every level a collapsed event was recorded at (one entry for a plain event).
    levels: List[float] = Field(default_factory=list)
    # True for an area event replaced by a later opposite event on the same area. Shown only as evidence.
    superseded: bool = False


class CorroborationOut(BaseModel):
    """Another record of the SAME level (same timeframe and price), kept for provenance."""
    timeframe: str
    kind: str
    source: str
    note: str


class ComponentOut(BaseModel):
    label: str
    price: float
    timeframe: str
    kind: str
    source: str
    note: str
    also_recorded_as: List[CorroborationOut] = Field(default_factory=list)


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
    trend_strength: Dimension


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
    state: str = "ACTIVE"  # ACTIVE | INVALIDATED (invalidation already met by the last closed M5 close)
    invalidated_reason: str = ""


class Facts(BaseModel):
    observations: Optional[Observations] = None
    structure: Dict[str, TimeframeStructure] = Field(default_factory=dict)


class SequenceStepOut(BaseModel):
    name: str  # SWEEP | STRUCTURE_SHIFT | DISPLACEMENT | RETRACEMENT
    status: str  # CONFIRMED | WAITING | INVALIDATED | NOT_REACHED
    bar_time_utc: Optional[str] = None
    level: Optional[float] = None
    detail: str


class SequenceOut(BaseModel):
    direction: str  # bullish | bearish
    stage: str  # last confirmed step, or INVALIDATED
    is_complete: bool
    invalidated: bool
    invalidation_reason: str
    next_step: Optional[str] = None
    superseded_by_utc: Optional[str] = None
    sweep_depth_atr: Optional[float] = None
    bars_since_sweep: Optional[int] = None
    bars_sweep_to_shift: Optional[int] = None
    chronology_ok: bool
    # MSS_FIRST | DISPLACEMENT_FIRST | SIMULTANEOUS once both have happened; None otherwise.
    ordering: Optional[str] = None
    # Set when a later sweep owns this sequence's structure shift; this sweep then does not confirm it.
    mss_owner_time_utc: Optional[str] = None
    sweep_time_utc: Optional[str] = None
    sweep_level_name: str
    sweep_level_price: Optional[float] = None
    steps: List[SequenceStepOut]
    wording: Dict[str, str]  # observed | sequence | conditional, factual only


class Interpretation(BaseModel):
    context: Optional[Context] = None
    key_areas: List[KeyAreaOut] = Field(default_factory=list)  # active areas only, within ACTIVE_AREA_ATR of price
    distant_key_area_count: int = 0  # areas further from price than ACTIVE_AREA_ATR; counted, not listed
    confluence: Optional[Confluence] = None
    narrative: List[str] = Field(default_factory=list)
    sequences: List[SequenceOut] = Field(default_factory=list)


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
