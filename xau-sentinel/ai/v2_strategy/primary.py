"""The primary A+ evaluation path: Analysis V2 supplies the market facts.

    MT5 -> Analysis V2 -> A+ adapter (facts_from_v2) -> A+ decision (decide_from_facts)
        -> FundedNext gate (inside the decision, unchanged) -> LLM explanation (optional)

The A+ decision is the same function the legacy path uses. Only where its facts
come from differs. If V2 cannot support a read, this path raises V2UnavailableError
and does NOT fall back to the legacy calculation, so a caller can never receive a
rating built from facts it did not expect.
"""
from datetime import datetime, timezone

from ai.strategy import evidence as evidence_builder
from ai.strategy.evaluator import attach_llm_explanation, decide_from_facts
from ai.strategy.schemas import StrategyEvaluationOut
from ai.v2_strategy.bridge import V2NotEvaluable, facts_from_v2
from analysis.v2.engine import build_analysis
from mt5 import market_data
from risk import settings_store
from risk.fundednext import compute_status
from risk.models import AccountType, FundedNextStatus, Phase


class V2UnavailableError(Exception):
    """V2 cannot support an A+ read. Raised instead of falling back silently."""


def evaluate_primary(candles: dict, fundednext_status: FundedNextStatus, now: datetime) -> StrategyEvaluationOut:
    """Deterministic primary evaluation. Pure given its inputs: no LLM, no I/O."""
    analysis = build_analysis(candles, now=now)
    try:
        facts = facts_from_v2(analysis, candles)
    except V2NotEvaluable as exc:
        raise V2UnavailableError(str(exc)) from exc
    return decide_from_facts(facts, fundednext_status, now)


def evaluate_current_setup_primary() -> StrategyEvaluationOut:
    """Live wiring for the API route. Market-data errors propagate as
    market_data.MarketDataError (the route maps them to 503); V2 failures propagate
    as V2UnavailableError (the route maps them to 503 with the reason)."""
    candles = market_data.get_all_candles(300)
    settings = settings_store.get_settings()
    fn_status = compute_status(
        AccountType(settings["account_type"]), Phase(settings["phase"]), settings["consistency_enabled"],
    )
    result = evaluate_primary(candles, fn_status, datetime.now(timezone.utc))
    evidence = evidence_builder.build_contextual_evidence(result)
    return attach_llm_explanation(result, evidence)
