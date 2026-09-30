"""Data shapes for the Real-Time Monitoring & Alert Engine (Stage 13).

Pure data only — no engine/rule/persistence logic lives here. Every alert
carries an explicit `AlertType`/`Severity` (never a numeric score, same
"explicit states, not confidence scores" convention Stage 12 established),
a stable `dedup_key` (never a random id — see ai/monitoring/rules.py), and
an `acknowledged` flag that is the ONLY thing the API's acknowledge
endpoints are ever allowed to change.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional


class AlertType(str, Enum):
    SETUP_STATE_CHANGED = "SETUP_STATE_CHANGED"
    APLUS_SETUP_DETECTED = "APLUS_SETUP_DETECTED"
    APLUS_SETUP_INVALIDATED = "APLUS_SETUP_INVALIDATED"
    HIGH_IMPACT_EVENT_NEAR = "HIGH_IMPACT_EVENT_NEAR"
    MARKET_INTELLIGENCE_QUALITY_CHANGED = "MARKET_INTELLIGENCE_QUALITY_CHANGED"
    RISK_STATUS_CHANGED = "RISK_STATUS_CHANGED"


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


@dataclass
class MonitoringSnapshot:
    """The compact, comparison-only state Stage 13's spec asks for —
    nothing beyond what a transition-detection rule actually needs. Never
    serializes candles/criteria/full evaluation objects; those live only in
    RawEvaluationBundle, used transiently to build an alert's payload."""
    setup_state: str  # "NO SETUP" | "DEVELOPING" | "INVALIDATED" | "VALID"
    setup_direction: Optional[str]
    aplus_rating: str  # "A+" | "DEVELOPING" | "INVALID"
    aplus_direction: Optional[str]
    risk_safety_level: str  # "SAFE" | "WARNING" | "CRITICAL" | "BREACHED" | "UNKNOWN"
    mi_overall_quality: str  # "AVAILABLE" | "PARTIALLY_AVAILABLE" | "UNAVAILABLE"
    nearby_high_impact_event_key: Optional[str]
    timestamp: str
    # Stage 23B (VAL-023): identity of the A+ candidate (its
    # candidate_sweep_time), so a new setup replacing the prior one while
    # the rating stays A+ is still detectable as a change.
    aplus_candidate_key: Optional[str] = None


@dataclass
class RawEvaluationBundle:
    """The full deterministic-engine outputs behind one MonitoringSnapshot —
    used only to build a rich alert payload the one time a rule actually
    fires; never persisted or compared field-by-field itself."""
    setup_result: Any  # analysis.setup.SetupResult
    strategy_result: Any  # ai.strategy.schemas.StrategyEvaluationOut
    fundednext_status: Any  # risk.models.FundedNextStatus
    intelligence_summary: Any  # ai.market_intelligence.quality.IntelligenceSummary
    nearest_event: Any  # Optional[ai.market_intelligence.quality.EventRiskItem]
    nearest_event_country: Optional[str] = None


@dataclass
class AlertEvent:
    type: AlertType
    severity: Severity
    title: str
    message: str
    dedup_key: str
    payload: Dict[str, Any] = field(default_factory=dict)
    symbol: str = "XAUUSD"
    id: Optional[int] = None
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    acknowledged: bool = False
