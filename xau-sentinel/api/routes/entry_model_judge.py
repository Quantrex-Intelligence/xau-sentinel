"""Read-only route for the Entry Model V2 LLM Setup Judge (shadow mode). No order, no action, and
no effect on /api/entry-model's own response -- see ai/entry_judge/__init__.py's module docstring
for the structural guarantee.

GET only, by design: a poll either returns the latest stored judgment for whatever candidate is
currently live (triggering a fresh LLM call only if the evidence materially changed since the last
one), a clear "not eligible yet" shape, or a clear "disabled" shape. Nothing here mutates any
trading state regardless of which branch runs.
"""
from fastapi import APIRouter

from api import analysis_v2
from api.routes.entry_model import build_entry_model_result
from ai.entry_judge.evaluator import judge_candidate
from ai.entry_judge.schemas import EntryJudgmentOut
from mt5 import market_data
import config

router = APIRouter(prefix="/api", tags=["entry-model-judge"])


def _disabled() -> EntryJudgmentOut:
    return EntryJudgmentOut(enabled=False, eligible=False)


def _not_eligible(entry_model_result: dict) -> EntryJudgmentOut:
    return EntryJudgmentOut(
        enabled=True, eligible=False,
        state=entry_model_result.get("state"), symbol=entry_model_result.get("symbol"),
        not_eligible_reason=(
            f"Entry Model state is {entry_model_result.get('state')!r}, not yet one of the states "
            "the Judge reviews (ENTRY_CONFIRMATION_DEVELOPING, ENTRY_CONFIRMED, PRECISION_AVAILABLE, "
            "ENTRY_READY)."
        ),
    )


def _from_judgment(judgment) -> EntryJudgmentOut:
    verdict = judgment.verdict
    return EntryJudgmentOut(
        enabled=True, eligible=True, status=judgment.status, error_category=judgment.error_category,
        candidate_key=judgment.candidate_key, direction=judgment.direction, state=judgment.state,
        symbol=judgment.symbol, evaluated_at=judgment.evaluated_at.isoformat(),
        candidate_created_at=judgment.candidate_created_at.isoformat(),
        is_reassessment=judgment.is_reassessment, llm_provider=judgment.llm_provider,
        llm_model=judgment.llm_model, prompt_version=judgment.prompt_version,
        verdict=(verdict.verdict if verdict else None), quality=(verdict.quality if verdict else None),
        supporting_evidence=(verdict.supporting_evidence if verdict else []),
        contradictions=(verdict.contradictions if verdict else []),
        missing_confirmations=(verdict.missing_confirmations if verdict else []),
        risk_flags=(verdict.risk_flags if verdict else []),
        reasoning_summary=(verdict.reasoning_summary if verdict else None),
        invalidation_conditions=(verdict.invalidation_conditions if verdict else []),
        evidence_references=(verdict.evidence_references if verdict else []),
    )


@router.get("/entry-model/judge", response_model=EntryJudgmentOut)
def get_entry_model_judge():
    if not config.ENTRY_JUDGE_ENABLED:
        return _disabled()

    try:
        entry_model_result = build_entry_model_result()
    except market_data.MarketDataError:
        # Same data-unavailable condition /api/entry-model itself 503s on -- here, a clear
        # not-eligible-right-now shape is more useful than a 503, since the Judge is advisory.
        return EntryJudgmentOut(enabled=True, eligible=False, not_eligible_reason="Market data unavailable.")

    judgment = judge_candidate(entry_model_result, v2_result=analysis_v2.build_payload())
    if judgment is None:
        return _not_eligible(entry_model_result)
    return _from_judgment(judgment)
