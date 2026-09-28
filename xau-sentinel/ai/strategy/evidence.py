"""The "Evidence Builder" (Stage 10): gathers RELEVANT supporting evidence
for the A+ evaluator's LLM explanation from Market Intelligence, historical
similarity, strategy RAG, and trading memory — alongside, never touching,
the already-decided deterministic rating in ai/strategy/evaluator.py.

Every call here is independently isolated: a broken/unavailable Market
Intelligence provider, an empty journal (no historical matches), an empty
knowledge base, or an empty memory store each degrade that ONE field, never
raise, and never take the others down with them (see
build_contextual_evidence()). "Relevant" is decided here, not by dumping
whatever came back — an evidence source with nothing genuinely useful is
marked not relevant and the callers below render it as absent/limited
rather than padding the analysis (the Stage 10 spec's own "relevant
evidence, not maximum context size" requirement).

Every renderer in this file builds plain, deterministic text from
`StrategyEvaluationOut`/`ContextualEvidence` — none of them call an LLM.
The one and only LLM-authored field in the whole pipeline is
`ContextualAnalysisOut.interpretation`, built in
ai/strategy/evaluator.py::attach_llm_explanation(), never here.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from ai.knowledge import retrieval as knowledge_retrieval
from ai.knowledge.models import RetrievedChunk
from ai.market_intelligence import context as mi_context
from ai.market_intelligence.models import MarketIntelligenceContext
from ai.market_intelligence.quality import build_event_risk_context, build_intelligence_summary, classify_news_relevance
from ai.memory import retrieval as memory_retrieval
from ai.memory.models import RetrievedMemory
from ai.similarity import engine as similarity_engine
from ai.similarity.models import SimilarityResult
from ai.strategy.schemas import CriterionStatus, MarketIntelligenceSummaryOut, StrategyEvaluationOut

_HISTORICAL_DESCRIPTIVE_NOTE = "Descriptive only — not a prediction of this trade's outcome."


@dataclass
class ContextualEvidence:
    market_intelligence: Optional[MarketIntelligenceContext] = None
    market_intelligence_relevant: bool = False
    similarity: Optional[SimilarityResult] = None
    similarity_relevant: bool = False
    knowledge_chunks: List[RetrievedChunk] = field(default_factory=list)
    memory: List[RetrievedMemory] = field(default_factory=list)


def _relevance_query(result: StrategyEvaluationOut) -> str:
    """A short, deterministic query built from the evaluation itself — so
    "relevant" means relevant to THIS setup, never a fixed canned string.
    Reused for both the RAG and memory lookups."""
    parts = [result.direction or "", result.rating.value, "A+ strategy setup"]
    if result.missing_conditions:
        parts.append(" ".join(result.missing_conditions))
    return " ".join(p for p in parts if p).strip()


def _has_relevant_news(mi: MarketIntelligenceContext) -> bool:
    """Stage 12: "relevant" news means genuinely classified RELEVANT to
    XAUUSD (ai.market_intelligence.quality.classify_news_relevance) — not
    simply "any news article exists." mi.news is already relevance-
    filtered by context.py's _get_news(), so in practice this re-check is
    a defense-in-depth belt-and-suspenders check, not the only gate."""
    return any(
        classify_news_relevance(n.headline, n.summary, n.category, n.assets) == "RELEVANT" for n in mi.news
    )


def _is_market_intelligence_relevant(mi: Optional[MarketIntelligenceContext]) -> bool:
    if mi is None:
        return False
    has_high_event = any(e.importance == "HIGH" for e in mi.events)
    return has_high_event or _has_relevant_news(mi)


def build_contextual_evidence(result: StrategyEvaluationOut) -> ContextualEvidence:
    market_intelligence = None
    mi_relevant = False
    try:
        market_intelligence = mi_context.build_market_intelligence_context()
        mi_relevant = _is_market_intelligence_relevant(market_intelligence)
    except Exception:  # noqa: BLE001 - one evidence source failing must never break the others
        pass

    similarity = None
    similarity_relevant = False
    try:
        features, _exclude_id = similarity_engine.resolve_query_features(None)
        if features is not None:
            similarity = similarity_engine.find_similar_setups(features)
            similarity_relevant = len(similarity.matches) > 0
    except Exception:  # noqa: BLE001
        pass

    query = _relevance_query(result)
    knowledge_chunks: List[RetrievedChunk] = []
    memory: List[RetrievedMemory] = []
    try:
        knowledge_chunks = knowledge_retrieval.retrieve(query) if query else []
    except Exception:  # noqa: BLE001
        pass
    try:
        memory = memory_retrieval.retrieve_memory(query) if query else []
    except Exception:  # noqa: BLE001
        pass

    return ContextualEvidence(
        market_intelligence=market_intelligence, market_intelligence_relevant=mi_relevant,
        similarity=similarity, similarity_relevant=similarity_relevant,
        knowledge_chunks=knowledge_chunks, memory=memory,
    )


# ---------------------------------------------------------------------------
# Deterministic section renderers — plain Python, never LLM output.
# ---------------------------------------------------------------------------

def technical_summary(result: StrategyEvaluationOut) -> str:
    if not result.context_evidence:
        return "No additional technical context beyond the checklist above."
    return " ".join(result.context_evidence)


def strategy_summary(result: StrategyEvaluationOut) -> str:
    satisfied = [c.name for c in result.criteria if c.status == CriterionStatus.PASSED]
    lines = [f"Deterministic rating: {result.rating.value}."]
    if satisfied:
        lines.append("Satisfied: " + ", ".join(satisfied) + ".")
    if result.missing_conditions:
        lines.append("Missing: " + ", ".join(result.missing_conditions) + ".")
    if result.invalidation:
        lines.append(f"Invalidation: {result.invalidation}")
    return " ".join(lines)


def risk_context(result: StrategyEvaluationOut) -> str:
    fn = result.fundednext
    if not fn.data_available:
        return f"FundedNext risk data unavailable — {fn.reason or 'no reason given'}."
    return (
        f"Safety level {fn.safety_level}, daily loss used {fn.daily_loss_used_pct}% "
        f"(A+ limit {fn.max_daily_loss_used_pct_allowed}%)."
    )


def market_intelligence_summary(evidence: ContextualEvidence) -> MarketIntelligenceSummaryOut:
    mi = evidence.market_intelligence
    if mi is None or not evidence.market_intelligence_relevant:
        return MarketIntelligenceSummaryOut(relevant=False)

    macro = None
    if mi.macro and mi.macro.data_available:
        macro = (
            f"Fed funds {mi.macro.fed_funds_rate}%, CPI YoY {mi.macro.cpi_yoy}%, "
            f"10Y yield {mi.macro.us10y_yield}%."
        )

    high_events = [e for e in mi.events if e.importance == "HIGH"]
    events = "; ".join(f"{e.name} ({e.scheduled_at})" for e in high_events[:3]) if high_events else None

    relevant_news = [n for n in mi.news if classify_news_relevance(n.headline, n.summary, n.category, n.assets) == "RELEVANT"]
    news = "; ".join(n.headline for n in relevant_news[:3]) if relevant_news else None

    cross_asset = None
    if mi.cross_asset and mi.cross_asset.data_available:
        cross_asset = f"DXY {mi.cross_asset.dxy}, US10Y {mi.cross_asset.us10y_yield}%, VIX {mi.cross_asset.vix}."

    overall = build_intelligence_summary(mi).overall
    freshness = mi.macro.freshness if mi.macro else None

    return MarketIntelligenceSummaryOut(
        relevant=True, macro=macro, events=events, news=news, cross_asset=cross_asset,
        freshness=freshness, overall=overall,
    )


def historical_context(evidence: ContextualEvidence) -> str:
    if not evidence.similarity_relevant or evidence.similarity is None or not evidence.similarity.matches:
        return f"Historical similarity evidence is limited — no sufficiently similar past setups found. {_HISTORICAL_DESCRIPTIVE_NOTE}"

    lines = []
    for m in evidence.similarity.matches[:3]:
        outcome = m.outcome.result or ("open" if m.outcome.status == "OPEN" else "unknown")
        lines.append(f"Trade #{m.trade_id} ({m.similarity * 100:.0f}% similar, outcome: {outcome})")
    return "; ".join(lines) + f". {_HISTORICAL_DESCRIPTIVE_NOTE}"


def uncertainties(result: StrategyEvaluationOut, evidence: ContextualEvidence) -> List[str]:
    items = list(result.missing_conditions)
    if not evidence.market_intelligence_relevant:
        items.append("No materially relevant macro/news evidence available right now.")
    if not evidence.similarity_relevant:
        items.append("Limited historical similarity evidence.")
    if not evidence.knowledge_chunks:
        items.append("No directly relevant strategy documentation retrieved.")
    if not evidence.memory:
        items.append("No relevant recorded preferences or lessons.")
    return items


def _freshness_tag(freshness: str, source: Optional[str], timestamp: Optional[str]) -> str:
    """Stage 12: every Market Intelligence line the LLM reads carries its
    own explicit freshness/source/timestamp — ground rule 10 tells the
    model to check the timestamp and say plainly if data looks stale, but
    it can't act on that instruction if the rendered text never states it.
    STALE is called out by name so the model cannot describe it as
    current."""
    label = f"[{freshness}, source={source or 'unknown'}, as of {timestamp or 'unknown'}]"
    if freshness == "STALE":
        label += " — STALE, do not treat as current"
    return label


def render_for_llm(evidence: ContextualEvidence) -> str:
    """Appended to the existing deterministic rendering in
    ai/strategy/evaluator.py::_render_for_llm() only when evidence is
    given — the LLM sees exactly this text as supporting context, in the
    same precedence order STRATEGY_SYSTEM_PROMPT's rule 6 states."""
    parts: List[str] = []

    if evidence.market_intelligence_relevant and evidence.market_intelligence:
        mi = evidence.market_intelligence
        parts.append("Market Intelligence (external, time-stamped, supporting only):")
        if mi.macro and mi.macro.data_available:
            tag = _freshness_tag(mi.macro.freshness, mi.macro.source, mi.macro.generated_at)
            parts.append(
                f"- Macro {tag}: Fed funds {mi.macro.fed_funds_rate}%, CPI YoY {mi.macro.cpi_yoy}%, "
                f"10Y yield {mi.macro.us10y_yield}%"
            )
        high_events = [e for e in mi.events if e.importance == "HIGH"]
        if high_events:
            parts.append("- High-importance events: " + "; ".join(e.name for e in high_events[:3]))
        risk_items = build_event_risk_context(high_events)
        nearest = next((i for i in risk_items if i.status == "UPCOMING"), None)
        if nearest:
            parts.append(
                f"- Nearest high-impact event: {nearest.event} in {nearest.minutes_until} minutes "
                f"(importance {nearest.importance}, source={nearest.source})"
            )
        relevant_news = [
            n for n in mi.news if classify_news_relevance(n.headline, n.summary, n.category, n.assets) == "RELEVANT"
        ]
        if relevant_news:
            parts.append("- Recent relevant news: " + "; ".join(n.headline for n in relevant_news[:3]))
        if mi.cross_asset and mi.cross_asset.data_available:
            tag = _freshness_tag(mi.cross_asset.freshness, mi.cross_asset.source, mi.cross_asset.generated_at)
            parts.append(f"- Cross-asset {tag}: DXY {mi.cross_asset.dxy}, VIX {mi.cross_asset.vix}")
        overall = build_intelligence_summary(mi).overall
        parts.append(f"- Overall Market Intelligence availability: {overall}")
    else:
        parts.append("Market Intelligence: not materially relevant right now.")

    if evidence.similarity_relevant and evidence.similarity:
        parts.append(f"Historical similarity ({_HISTORICAL_DESCRIPTIVE_NOTE}):")
        for m in evidence.similarity.matches[:3]:
            outcome = m.outcome.result or ("open" if m.outcome.status == "OPEN" else "unknown")
            parts.append(f"- Trade #{m.trade_id}: {m.similarity * 100:.0f}% similar, outcome {outcome}")
    else:
        parts.append("Historical similarity: limited, no sufficiently similar past setups.")

    if evidence.knowledge_chunks:
        parts.append("Strategy knowledge:")
        for c in evidence.knowledge_chunks[:3]:
            parts.append(f"- {c.title}: {c.text[:200]}")

    if evidence.memory:
        parts.append("User-confirmed memory:")
        for m in evidence.memory[:3]:
            parts.append(f"- {m.category.value}: {m.content}")

    return "\n".join(parts)
