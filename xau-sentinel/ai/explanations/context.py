"""Explanation evidence gathering (Stage 15) — reuses Stage 10's
ContextualEvidence dataclass and its already alert/trade-agnostic
renderers (market_intelligence_summary(), historical_context(),
render_for_llm() all take ONLY a ContextualEvidence, no
StrategyEvaluationOut) rather than re-implementing any of it. The only
genuinely new logic here is WHICH sources to gather for a given
AlertType/subject (see ALERT_EVIDENCE_RULES) and how to render the
result into the spec's FACT/CONTEXT tiers.

Every source is independently try/excepted — one broken/unavailable
provider degrades only its own field, exactly like
ai/strategy/evidence.py::build_contextual_evidence() already does; never
raises, never takes another source down with it.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ai.knowledge import retrieval as knowledge_retrieval
from ai.market_intelligence import context as mi_context
from ai.memory import retrieval as memory_retrieval
from ai.monitoring.models import AlertEvent, AlertType
from ai.similarity import engine as similarity_engine
from ai.strategy.evidence import ContextualEvidence, historical_context as historical_context_text
from ai.strategy.evidence import market_intelligence_summary as build_mi_summary
from risk import settings_store
from risk.fundednext import compute_status
from risk.models import AccountType, FundedNextStatus, Phase

# Which evidence sources genuinely apply to each alert type — the spec's
# own explicit example ("for RISK_STATUS_CHANGED, do not unnecessarily
# retrieve historical setup similarity") taken literally and extended
# consistently to the other types.
ALERT_EVIDENCE_RULES: Dict[AlertType, Dict[str, bool]] = {
    AlertType.APLUS_SETUP_DETECTED: dict(risk=True, mi=True, similarity=True, rag=True, memory=True),
    AlertType.APLUS_SETUP_INVALIDATED: dict(risk=True, mi=True, similarity=True, rag=True, memory=True),
    AlertType.SETUP_STATE_CHANGED: dict(risk=True, mi=True, similarity=True, rag=True, memory=True),
    AlertType.RISK_STATUS_CHANGED: dict(risk=True, mi=False, similarity=False, rag=True, memory=True),
    AlertType.HIGH_IMPACT_EVENT_NEAR: dict(risk=False, mi=True, similarity=False, rag=True, memory=False),
    AlertType.MARKET_INTELLIGENCE_QUALITY_CHANGED: dict(risk=False, mi=True, similarity=False, rag=False, memory=False),
}
# A future, not-yet-formatter-mapped AlertType: reasonably inclusive
# (risk/MI/RAG/memory) but never guesses at similarity relevance.
DEFAULT_EVIDENCE_RULES = dict(risk=True, mi=True, similarity=False, rag=True, memory=True)


@dataclass
class SubjectEvidence:
    evidence: ContextualEvidence
    fundednext_status: Optional[FundedNextStatus] = None


def _current_fundednext_status() -> Optional[FundedNextStatus]:
    try:
        settings = settings_store.get_settings()
        return compute_status(
            AccountType(settings["account_type"]), Phase(settings["phase"]), settings["consistency_enabled"],
        )
    except Exception:  # noqa: BLE001 - one evidence source failing must never break the others
        return None


def _gather_mi(evidence: ContextualEvidence) -> None:
    try:
        mi = mi_context.build_market_intelligence_context()
        evidence.market_intelligence = mi
        evidence.market_intelligence_relevant = bool(mi and mi.data_available)
    except Exception:  # noqa: BLE001
        pass


def _gather_similarity(evidence: ContextualEvidence, trade_id: Optional[int]) -> None:
    try:
        features, exclude_id = similarity_engine.resolve_query_features(trade_id)
        if features is not None:
            result = similarity_engine.find_similar_setups(features, exclude_trade_id=exclude_id)
            evidence.similarity = result
            evidence.similarity_relevant = len(result.matches) > 0
    except Exception:  # noqa: BLE001
        pass


def _gather_knowledge(evidence: ContextualEvidence, query: str) -> None:
    try:
        evidence.knowledge_chunks = knowledge_retrieval.retrieve(query) if query else []
    except Exception:  # noqa: BLE001
        pass


def _gather_memory(evidence: ContextualEvidence, query: str) -> None:
    try:
        evidence.memory = memory_retrieval.retrieve_memory(query) if query else []
    except Exception:  # noqa: BLE001
        pass


def _alert_query(alert: AlertEvent) -> str:
    return f"{alert.title} {alert.message}".strip()


def gather_evidence_for_alert(alert: AlertEvent) -> SubjectEvidence:
    rules = ALERT_EVIDENCE_RULES.get(alert.type, DEFAULT_EVIDENCE_RULES)
    evidence = ContextualEvidence()
    query = _alert_query(alert)

    if rules["mi"]:
        _gather_mi(evidence)
    if rules["similarity"]:
        _gather_similarity(evidence, trade_id=None)  # the current live setup
    if rules["rag"]:
        _gather_knowledge(evidence, query)
    if rules["memory"]:
        _gather_memory(evidence, query)

    fn_status = _current_fundednext_status() if rules["risk"] else None
    return SubjectEvidence(evidence=evidence, fundednext_status=fn_status)


def _trade_query(trade: Dict[str, Any]) -> str:
    parts = [trade.get("direction") or "", trade.get("setup") or "", trade.get("result") or "", "trade setup"]
    return " ".join(p for p in parts if p).strip()


def gather_evidence_for_trade(trade_id: int, trade: Dict[str, Any]) -> SubjectEvidence:
    """Market Intelligence is deliberately never gathered here — today's
    conditions describing a trade that closed in the past would misleadingly
    conflate current data with historical context (see the Stage 15 plan)."""
    evidence = ContextualEvidence()
    query = _trade_query(trade)

    _gather_similarity(evidence, trade_id=trade_id)
    _gather_knowledge(evidence, query)
    _gather_memory(evidence, query)

    return SubjectEvidence(evidence=evidence, fundednext_status=None)


# ---------------------------------------------------------------------------
# Deterministic facts — read only real fields, never invent one.
# ---------------------------------------------------------------------------

_ALERT_FACT_FIELDS: Dict[AlertType, List[str]] = {
    AlertType.SETUP_STATE_CHANGED: ["previous_state", "current_state", "direction", "reason"],
    AlertType.APLUS_SETUP_DETECTED: ["direction", "entry", "stop_loss", "target", "rr", "rating"],
    AlertType.APLUS_SETUP_INVALIDATED: ["previous_direction", "invalidation", "rating"],
    AlertType.RISK_STATUS_CHANGED: ["previous_status", "current_status", "daily_loss_used_pct", "max_drawdown_used_pct"],
    AlertType.MARKET_INTELLIGENCE_QUALITY_CHANGED: ["previous_quality", "current_quality", "macro_quality",
                                                      "cross_asset_quality", "news_quality"],
    AlertType.HIGH_IMPACT_EVENT_NEAR: ["event", "country", "importance", "event_time", "status", "minutes_until"],
}

_FIELD_LABELS = {
    "previous_state": "Previous state", "current_state": "Current state", "direction": "Direction",
    "reason": "Reason", "entry": "Entry", "stop_loss": "Stop loss", "target": "Target", "rr": "R:R",
    "rating": "Rating", "previous_direction": "Previous direction", "invalidation": "Invalidation reason",
    "previous_status": "Previous status", "current_status": "Current status",
    "daily_loss_used_pct": "Daily loss used %", "max_drawdown_used_pct": "Max drawdown used %",
    "previous_quality": "Previous quality", "current_quality": "Current quality", "macro_quality": "Macro quality",
    "cross_asset_quality": "Cross-asset quality", "news_quality": "News quality", "event": "Event",
    "country": "Country", "importance": "Importance", "event_time": "Event time", "status": "Status",
    "minutes_until": "Minutes until",
}


def deterministic_facts_for_alert(alert: AlertEvent) -> List[str]:
    fields = _ALERT_FACT_FIELDS.get(alert.type, [])
    facts = []
    for name in fields:
        value = alert.payload.get(name)
        if value is not None:
            facts.append(f"{_FIELD_LABELS.get(name, name)}: {value}")
    if not facts:
        facts.append(alert.message)
    return facts


def deterministic_facts_for_trade(trade: Dict[str, Any]) -> List[str]:
    fields = [
        ("direction", "Direction"), ("entry", "Entry"), ("stop_loss", "Stop loss"),
        ("take_profit", "Take profit"), ("planned_rr", "Planned R:R"), ("result", "Result"),
        ("pnl", "P/L"), ("r_multiple", "R multiple"), ("h1_bias", "H1 bias"), ("regime", "Regime"),
        ("liquidity", "Liquidity"), ("mss", "MSS"), ("displacement", "Displacement"),
    ]
    facts = []
    for key, label in fields:
        value = trade.get(key)
        if value not in (None, ""):
            facts.append(f"{label}: {value}")
    return facts


# ---------------------------------------------------------------------------
# CONTEXT-tier renderers
# ---------------------------------------------------------------------------

def render_risk_context(status: Optional[FundedNextStatus]) -> List[str]:
    if status is None:
        return []
    if not status.data_available:
        return [f"FundedNext risk data unavailable — {status.reason or 'no reason given'}."]
    lines = [
        f"Safety level: {status.safety_level.value}",
        f"Daily loss used: {status.daily_loss_used_pct}%",
        f"Max drawdown used: {status.max_drawdown_used_pct}%",
    ]
    if status.reason:
        lines.append(status.reason)
    return lines


def render_supporting_context(evidence: ContextualEvidence) -> List[str]:
    summary = build_mi_summary(evidence)
    if not summary.relevant:
        return []
    lines = []
    if summary.macro:
        lines.append(f"Macro: {summary.macro}")
    if summary.cross_asset:
        lines.append(f"Cross-asset: {summary.cross_asset}")
    if summary.events:
        lines.append(f"High-importance events: {summary.events}")
    if summary.news:
        lines.append(f"Recent relevant news: {summary.news}")
    if summary.freshness:
        lines.append(f"Freshness: {summary.freshness}")
    if summary.overall:
        lines.append(f"Overall Market Intelligence availability: {summary.overall}")
    return lines


def render_knowledge_context(evidence: ContextualEvidence) -> List[str]:
    return [f"{c.title}: {c.text[:200]}" for c in evidence.knowledge_chunks[:3]]


def render_memory_context(evidence: ContextualEvidence) -> List[str]:
    return [f"{m.category.value}: {m.content}" for m in evidence.memory[:3]]


def render_uncertainties(subject: SubjectEvidence, rules: Dict[str, bool]) -> List[str]:
    items = []
    if rules.get("mi") and not subject.evidence.market_intelligence_relevant:
        items.append("No materially relevant Market Intelligence evidence available.")
    if rules.get("similarity") and not subject.evidence.similarity_relevant:
        items.append("No sufficiently similar historical setups were found.")
    if rules.get("rag") and not subject.evidence.knowledge_chunks:
        items.append("No directly relevant strategy documentation retrieved.")
    if rules.get("memory") and not subject.evidence.memory:
        items.append("No relevant recorded preferences or lessons.")
    if rules.get("risk") and (subject.fundednext_status is None or not subject.fundednext_status.data_available):
        items.append("FundedNext risk data was unavailable at explanation time.")
    return items


def build_sources(subject: SubjectEvidence) -> List[str]:
    sources = []
    if subject.fundednext_status is not None and subject.fundednext_status.data_available:
        sources.append("fundednext")
    if subject.evidence.market_intelligence_relevant:
        sources.append("market_intelligence")
    if subject.evidence.similarity_relevant:
        sources.append("historical_similarity")
    if subject.evidence.knowledge_chunks:
        sources.append("knowledge_rag")
    if subject.evidence.memory:
        sources.append("memory")
    return sources


__all__ = [
    "SubjectEvidence", "gather_evidence_for_alert", "gather_evidence_for_trade",
    "deterministic_facts_for_alert", "deterministic_facts_for_trade",
    "render_risk_context", "render_supporting_context", "render_knowledge_context",
    "render_memory_context", "render_uncertainties", "build_sources",
    "historical_context_text", "ALERT_EVIDENCE_RULES", "DEFAULT_EVIDENCE_RULES",
]
