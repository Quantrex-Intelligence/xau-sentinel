"""Orchestrates one Entry Model V2 LLM Setup Judge evaluation: eligibility -> candidate identity ->
reevaluation-skip check -> provider call (bounded timeout + retry) -> schema validation -> append-
only persistence. Never raises -- every failure path is recorded as a StoredJudgment with
status="FAILED" and a specific error_category, never a fabricated verdict, matching the task's own
"never fabricate a verdict when the provider fails" requirement.

Shadow mode is structural here, not a convention: this module only ever reads an already-decided
hierarchy.evaluate() result and writes to its own table via ai.entry_judge.store. It has no import
path to analysis.entry_model.hierarchy, ai.strategy.rules, or research.entry_model_v2_oos -- it
cannot alter a trading decision because it never touches the object that holds one.
"""
import concurrent.futures
import json
from datetime import datetime, timezone
from typing import Optional

from pydantic import ValidationError

import config
from ai.entry_judge import snapshot as snap_mod
from ai.entry_judge import store
from ai.entry_judge.models import STATUS_FAILED, STATUS_OK, EntryJudgeVerdict, StoredJudgment
from ai.entry_judge.prompts import PROMPT_VERSION, SYSTEM_PROMPT, render_snapshot_for_judge
from ai.entry_judge.schemas import EntryJudgeVerdictOut
from ai.prompts import SAFETY_OVERRIDE_MESSAGE, contains_actionable_directive, contains_predictive_probability_claim
from ai.providers import get_provider
from ai.providers.base import BaseProvider, ProviderConfigError, ProviderRequestError, ProviderResponseError


def _call_with_timeout(provider: BaseProvider, system: str, messages: list, timeout_seconds: float):
    """BaseProvider.chat() has no native timeout parameter, so this wraps the call rather than
    modifying the shared provider classes. A timeout is reported as a ProviderRequestError so the
    retry loop below treats it exactly like any other request-level failure.

    Deliberately NOT a `with ThreadPoolExecutor(...) as pool:` block: that context manager's own
    __exit__ calls shutdown(wait=True) unconditionally, which blocks the caller until the
    already-submitted task actually finishes -- silently re-adding an unbounded wait right after
    future.result(timeout=...) correctly raised. Confirmed directly: wrapping a 2-second call with
    a 0.3s timeout still took ~2s end to end with the `with` form. shutdown(wait=False) here lets
    this function actually return within timeout_seconds; the orphaned background thread (Python
    cannot force-cancel a running thread) keeps running and is simply never waited on or read."""
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(provider.chat, system, messages)
        try:
            return future.result(timeout=timeout_seconds)
        except concurrent.futures.TimeoutError:
            raise ProviderRequestError(f"Judge provider call exceeded the {timeout_seconds}s timeout")
    finally:
        pool.shutdown(wait=False)


def _chat_with_retry(provider: BaseProvider, snapshot_dict: dict):
    """Retries only on ProviderRequestError (a transient/request-level failure, timeouts included)
    -- never on ProviderResponseError (the provider replied but unusably; retrying an unusable reply
    rarely helps and spends another call) and never on a parse/schema failure (a model-output
    problem, handled separately, after this returns)."""
    messages = [{"role": "user", "content": render_snapshot_for_judge(snapshot_dict)}]
    attempts = max(1, config.ENTRY_JUDGE_MAX_RETRIES + 1)
    last_exc: Optional[ProviderRequestError] = None
    for _ in range(attempts):
        try:
            return _call_with_timeout(provider, SYSTEM_PROMPT, messages, config.ENTRY_JUDGE_TIMEOUT_SECONDS)
        except ProviderRequestError as exc:
            last_exc = exc
    raise last_exc


def _extract_json(text: str) -> str:
    """Strips a markdown code fence if the model wrapped its reply in one despite being told not
    to. Otherwise returns the text unchanged."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return text


def judge_candidate(entry_model_result: dict, v2_result=None) -> Optional[StoredJudgment]:
    """Returns None when the current Entry Model state isn't one of the eligible states (the
    caller/route should report "not eligible yet", never an error). Otherwise always returns a
    StoredJudgment -- either the cached one for an unchanged candidate, or a freshly saved one."""
    if not snap_mod.is_eligible(entry_model_result):
        return None

    candidate_key = snap_mod.candidate_key(entry_model_result) or (
        f"UNKNOWN:asof:{entry_model_result.get('as_of')}"
    )
    snapshot_dict = snap_mod.build_snapshot(entry_model_result, v2_result)
    fingerprint = snap_mod.fingerprint(snapshot_dict)

    existing = store.get_latest(candidate_key)
    if existing is not None and existing.snapshot_fingerprint == fingerprint:
        return existing  # unchanged candidate: no new LLM call, no new row (the dedup control)

    candidate_created = existing.candidate_created_at if existing is not None else snap_mod.candidate_created_at(entry_model_result)
    base = dict(
        candidate_key=candidate_key, direction=snap_mod.working_direction(entry_model_result) or "UNKNOWN",
        state=entry_model_result.get("state", ""), symbol=entry_model_result.get("symbol", ""),
        snapshot_fingerprint=fingerprint, snapshot=snapshot_dict, candidate_created_at=candidate_created,
        evaluated_at=datetime.now(timezone.utc), prompt_version=PROMPT_VERSION,
        is_reassessment=existing is not None,
    )

    try:
        provider = get_provider()
    except ProviderConfigError:
        return store.save(StoredJudgment(status=STATUS_FAILED, error_category="config", **base))

    try:
        response = _chat_with_retry(provider, snapshot_dict)
    except ProviderRequestError:
        return store.save(StoredJudgment(
            status=STATUS_FAILED, error_category="request_or_timeout",
            llm_provider=provider.name, llm_model=provider.model, **base,
        ))
    except ProviderResponseError:
        return store.save(StoredJudgment(
            status=STATUS_FAILED, error_category="response",
            llm_provider=provider.name, llm_model=provider.model, **base,
        ))
    except Exception:  # noqa: BLE001 - deliberately broader than attach_llm_explanation()'s catch:
        # nothing here may ever bubble into a live decision path, unlike that best-effort enrichment.
        return store.save(StoredJudgment(
            status=STATUS_FAILED, error_category="unexpected",
            llm_provider=provider.name, llm_model=provider.model, **base,
        ))

    try:
        parsed_dict = json.loads(_extract_json(response.text))
    except (ValueError, TypeError):
        return store.save(StoredJudgment(
            status=STATUS_FAILED, error_category="malformed_response",
            llm_provider=response.provider, llm_model=response.model, **base,
        ))

    try:
        parsed = EntryJudgeVerdictOut.model_validate(parsed_dict)
    except ValidationError:
        return store.save(StoredJudgment(
            status=STATUS_FAILED, error_category="schema_invalid",
            llm_provider=response.provider, llm_model=response.model, **base,
        ))

    reasoning = parsed.reasoning_summary
    if contains_actionable_directive(reasoning) or contains_predictive_probability_claim(reasoning):
        reasoning = SAFETY_OVERRIDE_MESSAGE

    verdict = EntryJudgeVerdict(
        verdict=parsed.verdict.value, quality=parsed.quality.value,
        supporting_evidence=parsed.supporting_evidence, contradictions=parsed.contradictions,
        missing_confirmations=parsed.missing_confirmations, risk_flags=parsed.risk_flags,
        reasoning_summary=reasoning, invalidation_conditions=parsed.invalidation_conditions,
        evidence_references=parsed.evidence_references, model_id=response.model, prompt_version=PROMPT_VERSION,
    )
    return store.save(StoredJudgment(
        status=STATUS_OK, error_category=None, llm_provider=response.provider, llm_model=response.model,
        verdict=verdict, **base,
    ))
