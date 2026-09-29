"""Explanation generation (Stage 15) — the one place everything in this
package comes together: look up the subject, gather relevance-gated
evidence (ai/explanations/context.py), call the SAME provider abstraction
and safety filters Stage 3/8/10 already established, assemble the
structured AlertExplanation, and cache it.

Never blocks alert creation: this module is only ever invoked from an
explicit API request (api/routes/explanations.py), never from
ai/monitoring/engine.py or ai/notifications/delivery.py's background
loops. An LLM/provider outage narrows only `interpretation` — every other
field is plain Python, populated before the provider is ever called,
exactly like ai/strategy/evaluator.py::attach_llm_explanation()'s existing
"outage only narrows, never breaks" contract.
"""
from datetime import datetime, timezone
from typing import Optional

from journal import trades as trades_repo

from ai.explanations import context as ctx
from ai.explanations import store
from ai.explanations.models import AlertExplanation
from ai.explanations.prompts import EXPLANATION_SYSTEM_PROMPT
from ai.monitoring import store as monitoring_store
from ai.monitoring.models import AlertEvent
from ai.prompts import SAFETY_OVERRIDE_MESSAGE, contains_actionable_directive, contains_predictive_probability_claim
from ai.providers import get_provider
from ai.providers.base import ProviderConfigError, ProviderRequestError, ProviderResponseError
from ai.strategy.evidence import historical_context as historical_context_text
from ai.strategy.evidence import render_for_llm as render_evidence_for_llm


class ExplanationNotFoundError(Exception):
    """The alert/trade id doesn't exist — the route maps this to a 404,
    never a crash."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _summary_for_alert(alert: AlertEvent) -> str:
    return alert.title or alert.message


def _summary_for_trade(trade: dict) -> str:
    direction = trade.get("direction") or "Unknown direction"
    result = trade.get("result") or trade.get("status") or "unknown outcome"
    return f"{direction} trade on {trade.get('trade_date', 'an unknown date')} — {result}."


def _render_prompt(facts: list, risk_lines: list, evidence_text: str) -> str:
    parts = ["Deterministic facts:"] + [f"- {f}" for f in facts]
    if risk_lines:
        parts += ["", "Risk context:"] + [f"- {r}" for r in risk_lines]
    parts += ["", evidence_text]
    return "\n".join(parts)


def _call_llm(prompt: str) -> tuple:
    """Returns (interpretation, provider_name, model_name, error) — never
    raises; a config/request/response failure degrades to a clear
    unavailable message instead."""
    try:
        provider = get_provider()
    except ProviderConfigError as exc:
        return None, None, None, f"AI explanation unavailable — {exc}"

    try:
        response = provider.chat(EXPLANATION_SYSTEM_PROMPT, [{"role": "user", "content": prompt}])
    except (ProviderRequestError, ProviderResponseError) as exc:
        return None, None, None, f"AI explanation unavailable — {exc}"

    text = response.text
    if contains_actionable_directive(text) or contains_predictive_probability_claim(text):
        text = SAFETY_OVERRIDE_MESSAGE
    return text, response.provider, response.model, None


def _assemble(
    subject_type: str, subject_id: int, explanation_type: str, summary: str, facts: list,
    subject_evidence: ctx.SubjectEvidence, rules: dict,
) -> AlertExplanation:
    evidence = subject_evidence.evidence
    risk_lines = ctx.render_risk_context(subject_evidence.fundednext_status)
    evidence_text = render_evidence_for_llm(evidence)
    prompt = _render_prompt(facts, risk_lines, evidence_text)

    interpretation, provider_name, model_name, error = _call_llm(prompt)

    return AlertExplanation(
        subject_type=subject_type, subject_id=subject_id, explanation_type=explanation_type,
        summary=summary, deterministic_facts=facts, supporting_context=ctx.render_supporting_context(evidence),
        risk_context=risk_lines, historical_context=historical_context_text(evidence),
        knowledge_context=ctx.render_knowledge_context(evidence), memory_context=ctx.render_memory_context(evidence),
        uncertainties=ctx.render_uncertainties(subject_evidence, rules),
        interpretation=interpretation or (error or "AI explanation unavailable."),
        sources=ctx.build_sources(subject_evidence), generated_at=_now_iso(),
        llm_provider=provider_name, llm_model=model_name, llm_error=error,
    )


def explain_alert(alert_id: int, force: bool = False) -> AlertExplanation:
    if not force:
        cached = store.get_cached("alert", alert_id)
        if cached is not None:
            return cached

    alert = monitoring_store.get_by_id(alert_id)
    if alert is None:
        raise ExplanationNotFoundError(f"No monitoring alert with id {alert_id}.")

    rules = ctx.ALERT_EVIDENCE_RULES.get(alert.type, ctx.DEFAULT_EVIDENCE_RULES)
    subject_evidence = ctx.gather_evidence_for_alert(alert)
    facts = ctx.deterministic_facts_for_alert(alert)

    explanation = _assemble(
        "alert", alert_id, alert.type.value, _summary_for_alert(alert), facts, subject_evidence, rules,
    )
    return store.save(explanation)


def explain_trade(trade_id: int, force: bool = False) -> AlertExplanation:
    if not force:
        cached = store.get_cached("trade", trade_id)
        if cached is not None:
            return cached

    trade = trades_repo.get_trade(trade_id)
    if trade is None:
        raise ExplanationNotFoundError(f"No trade with id {trade_id}.")

    rules = dict(risk=False, mi=False, similarity=True, rag=True, memory=True)
    subject_evidence = ctx.gather_evidence_for_trade(trade_id, trade)
    facts = ctx.deterministic_facts_for_trade(trade)

    explanation = _assemble(
        "trade", trade_id, "TRADE", _summary_for_trade(trade), facts, subject_evidence, rules,
    )
    return store.save(explanation)
