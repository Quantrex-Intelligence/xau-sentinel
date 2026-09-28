"""Data shapes for historical setup similarity (Stage 8). Pure data — no
extraction, scoring, or storage logic lives here.

SetupFeatures deliberately covers only what journal_context actually
captures at entry (see ai/similarity/features.py's docstring) — every field
is Optional, and a missing field is never fabricated, only excluded from
scoring (see ai/similarity/scoring.py).
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class SetupFeatures:
    direction: Optional[str] = None          # "BUY" | "SELL"
    h4_structure: Optional[str] = None        # "BULLISH" | "BEARISH" | "RANGING" | "PULLBACK"
    h1_structure: Optional[str] = None
    m15_structure: Optional[str] = None
    m5_structure: Optional[str] = None
    regime: Optional[str] = None               # e.g. "TRENDING UP", "HIGH VOLATILITY"
    liquidity_kind: Optional[str] = None        # "sweep_high" | "sweep_low"
    mss_direction: Optional[str] = None          # "bullish" | "bearish"
    displacement: Optional[str] = None            # "bullish" | "bearish"
    session: Optional[str] = None                   # "Asian" | "London" | "New York" | "Off-session"
    planned_rr: Optional[float] = None


@dataclass
class Outcome:
    """Attached to a match strictly AFTER scoring — never an input to
    score(). "UNKNOWN" (result=None) covers an OPEN trade or one closed
    without a recorded result, never guessed."""
    status: str                    # "OPEN" | "CLOSED"
    result: Optional[str] = None     # "WIN" | "LOSS" | "BE" | None
    r_multiple: Optional[float] = None
    pnl: Optional[float] = None
    duration_minutes: Optional[float] = None
    entry_date: Optional[str] = None
    entry_time: Optional[str] = None


@dataclass
class MatchedSetup:
    trade_id: int
    similarity: float
    entry_snapshot: SetupFeatures
    outcome: Outcome
    matched_features: List[str] = field(default_factory=list)
    different_features: List[str] = field(default_factory=list)


@dataclass
class SimilarityResult:
    matches: List[MatchedSetup] = field(default_factory=list)
    considered_count: int = 0   # candidates that had enough data to be scored
    excluded_count: int = 0     # candidates skipped for insufficient entry-time data
