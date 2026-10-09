"""Tests for ai/entry_judge/evaluator.py -- provider call handling, retries, schema validation,
prompt-injection backstop, and that every failure path is recorded, never fabricated."""
import json
import time

import pytest

import config
from ai.entry_judge import evaluator as ev
from ai.entry_judge.models import STATUS_FAILED, STATUS_OK
from ai.providers.base import BaseProvider, ProviderConfigError, ProviderRequestError, ProviderResponse, ProviderResponseError

ELIGIBLE_RESULT = {
    "symbol": "XAUUSD", "as_of": "2026-10-08T12:00:00+00:00", "state": "ENTRY_READY",
    "setup_15m": {"setup_direction": "LONG", "fvg": None, "supporting_evidence": [], "contradicting_evidence": []},
    "confirmation_5m": {"supporting_evidence": [], "contradicting_evidence": []},
    "higher_timeframe": None, "intraday": None, "precision_1m": None,
    "entry_candidate": {"stop": {"price": 100.0}}, "confidence": None,
    "supporting_evidence": [], "contradicting_evidence": [], "invalidation": None, "next_condition": None,
}

VALID_VERDICT_JSON = json.dumps({
    "verdict": "SUPPORTED", "quality": "HIGH", "supporting_evidence": ["x"], "contradictions": [],
    "missing_confirmations": [], "risk_flags": [], "reasoning_summary": "Evidence is consistent.",
    "invalidation_conditions": [], "evidence_references": ["M15"],
})


class _StubProvider(BaseProvider):
    name = "stub"
    model = "stub-model"

    def __init__(self, response=None, raises=None, fail_times=0):
        """Raises `raises` on the first `fail_times` calls, then returns `response`. If `response`
        is None, every call raises (fail_times just controls nothing in that case)."""
        self.response = response
        self.raises = raises
        self.fail_times = fail_times
        self.call_count = 0

    def chat(self, system, messages, tools=None):
        self.call_count += 1
        if self.raises is not None and self.call_count <= self.fail_times:
            raise self.raises
        if self.response is None:
            raise self.raises
        return self.response


@pytest.fixture(autouse=True)
def _default_retry_config(monkeypatch):
    monkeypatch.setattr(config, "ENTRY_JUDGE_MAX_RETRIES", 1)
    monkeypatch.setattr(config, "ENTRY_JUDGE_TIMEOUT_SECONDS", 5.0)


def _provider_response(text):
    return ProviderResponse(text=text, provider="stub", model="stub-model")


# --- candidate identity across state transitions (end to end through the real store) --------------

def test_the_same_setup_is_tracked_as_one_history_across_developing_and_confirmed(monkeypatch):
    # Confirmed finding this guards against: before the candidate_key fix, the same real-world
    # setup's stop-based key (once confirmed) never matched its earlier fvg-based key (while
    # developing), so judge_candidate() treated the CONFIRMED poll as a brand-new candidate instead
    # of a reassessment of the DEVELOPING one -- losing continuity in the append-only history.
    monkeypatch.setattr(ev, "get_provider", lambda: _StubProvider(response=_provider_response(VALID_VERDICT_JSON)))
    fvg = {"formed_at": "2026-10-09T10:00:00+00:00"}
    base = {
        "symbol": "XAUUSD", "as_of": "2026-10-09T10:05:00+00:00",
        "setup_15m": {"setup_direction": "LONG", "fvg": fvg, "supporting_evidence": [], "contradicting_evidence": []},
        "confirmation_5m": {"supporting_evidence": [], "contradicting_evidence": []},
        "higher_timeframe": None, "intraday": None, "precision_1m": None, "confidence": None,
        "supporting_evidence": [], "contradicting_evidence": [], "invalidation": None, "next_condition": None,
    }
    developing = dict(base, state="ENTRY_CONFIRMATION_DEVELOPING", entry_candidate=None)
    confirmed = dict(base, state="ENTRY_CONFIRMED", entry_candidate={"stop": {"price": 4095.0}})

    first = ev.judge_candidate(developing)
    second = ev.judge_candidate(confirmed)

    assert first.candidate_key == second.candidate_key
    assert first.is_reassessment is False
    assert second.is_reassessment is True
    assert second.candidate_created_at == first.candidate_created_at  # the "first seen" time carries forward


# --- not eligible -------------------------------------------------------------------------------

def test_returns_none_for_an_ineligible_state():
    result = dict(ELIGIBLE_RESULT, state="SETUP_DEVELOPING")
    assert ev.judge_candidate(result) is None


# --- happy path -----------------------------------------------------------------------------------

def test_valid_json_reply_produces_an_ok_judgment(monkeypatch):
    stub = _StubProvider(response=_provider_response(VALID_VERDICT_JSON))
    monkeypatch.setattr(ev, "get_provider", lambda: stub)
    judgment = ev.judge_candidate(ELIGIBLE_RESULT)
    assert judgment.status == STATUS_OK
    assert judgment.verdict.verdict == "SUPPORTED"
    assert judgment.verdict.quality == "HIGH"
    assert judgment.verdict.model_id == "stub-model"
    assert judgment.error_category is None


def test_a_markdown_fenced_reply_is_still_parsed():
    fenced = f"```json\n{VALID_VERDICT_JSON}\n```"
    import ai.entry_judge.evaluator as ev_mod
    assert json.loads(ev_mod._extract_json(fenced)) == json.loads(VALID_VERDICT_JSON)


# --- provider config error (never retried) -------------------------------------------------------

def test_provider_config_error_is_recorded_not_raised(monkeypatch):
    def boom():
        raise ProviderConfigError("no API key")
    monkeypatch.setattr(ev, "get_provider", boom)
    judgment = ev.judge_candidate(ELIGIBLE_RESULT)
    assert judgment.status == STATUS_FAILED
    assert judgment.error_category == "config"
    assert judgment.verdict is None


# --- provider request error: retried, then recorded on exhaustion --------------------------------

def test_request_error_is_retried_then_recorded_on_exhaustion(monkeypatch):
    stub = _StubProvider(raises=ProviderRequestError("network blip"), fail_times=99)
    monkeypatch.setattr(ev, "get_provider", lambda: stub)
    judgment = ev.judge_candidate(ELIGIBLE_RESULT)
    assert judgment.status == STATUS_FAILED
    assert judgment.error_category == "request_or_timeout"
    assert stub.call_count == config.ENTRY_JUDGE_MAX_RETRIES + 1  # initial attempt + retries


def test_request_error_succeeds_on_retry(monkeypatch):
    stub = _StubProvider(response=_provider_response(VALID_VERDICT_JSON), raises=ProviderRequestError("blip"), fail_times=1)
    monkeypatch.setattr(ev, "get_provider", lambda: stub)
    judgment = ev.judge_candidate(ELIGIBLE_RESULT)
    assert judgment.status == STATUS_OK
    assert stub.call_count == 2


# --- provider response error: NOT retried ---------------------------------------------------------

def test_response_error_is_not_retried(monkeypatch):
    stub = _StubProvider(raises=ProviderResponseError("empty content"))
    monkeypatch.setattr(ev, "get_provider", lambda: stub)
    judgment = ev.judge_candidate(ELIGIBLE_RESULT)
    assert judgment.status == STATUS_FAILED
    assert judgment.error_category == "response"
    assert stub.call_count == 1


# --- malformed / schema-invalid replies ------------------------------------------------------------

def test_non_json_reply_is_recorded_as_malformed(monkeypatch):
    stub = _StubProvider(response=_provider_response("I think this setup looks fine."))
    monkeypatch.setattr(ev, "get_provider", lambda: stub)
    judgment = ev.judge_candidate(ELIGIBLE_RESULT)
    assert judgment.status == STATUS_FAILED
    assert judgment.error_category == "malformed_response"
    assert judgment.verdict is None


def test_json_with_an_invalid_enum_value_is_recorded_as_schema_invalid(monkeypatch):
    bad = json.dumps({**json.loads(VALID_VERDICT_JSON), "verdict": "DEFINITELY_WINS"})
    stub = _StubProvider(response=_provider_response(bad))
    monkeypatch.setattr(ev, "get_provider", lambda: stub)
    judgment = ev.judge_candidate(ELIGIBLE_RESULT)
    assert judgment.status == STATUS_FAILED
    assert judgment.error_category == "schema_invalid"


def test_json_missing_a_required_field_is_recorded_as_schema_invalid(monkeypatch):
    bad_dict = json.loads(VALID_VERDICT_JSON)
    del bad_dict["quality"]
    stub = _StubProvider(response=_provider_response(json.dumps(bad_dict)))
    monkeypatch.setattr(ev, "get_provider", lambda: stub)
    judgment = ev.judge_candidate(ELIGIBLE_RESULT)
    assert judgment.status == STATUS_FAILED
    assert judgment.error_category == "schema_invalid"


# --- timeout must actually bound real wall-clock latency, not just future.result() ----------------

def test_a_hanging_provider_call_does_not_block_past_the_configured_timeout(monkeypatch):
    # Regression test: an earlier implementation wrapped the provider call in
    # `with ThreadPoolExecutor(...) as pool:`, whose own __exit__ calls shutdown(wait=True)
    # unconditionally -- this silently re-added an unbounded wait for the hung call to actually
    # finish, right after future.result(timeout=...) had already (correctly) raised. Confirmed
    # directly: that form took ~2s end-to-end against a 0.3s timeout. The fix uses
    # shutdown(wait=False) so the function returns promptly instead.
    monkeypatch.setattr(config, "ENTRY_JUDGE_TIMEOUT_SECONDS", 0.2)
    monkeypatch.setattr(config, "ENTRY_JUDGE_MAX_RETRIES", 0)

    class _HangingProvider(BaseProvider):
        name, model = "hangs", "x"
        def chat(self, system, messages, tools=None):
            time.sleep(2.0)
            return _provider_response(VALID_VERDICT_JSON)

    monkeypatch.setattr(ev, "get_provider", lambda: _HangingProvider())
    start = time.monotonic()
    judgment = ev.judge_candidate(ELIGIBLE_RESULT)
    elapsed = time.monotonic() - start

    assert judgment.status == STATUS_FAILED
    assert judgment.error_category == "request_or_timeout"
    assert elapsed < 1.0, f"took {elapsed:.2f}s -- the configured 0.2s timeout did not bound real latency"


# --- unexpected exception is never allowed to escape ------------------------------------------------

def test_an_unexpected_exception_from_the_provider_is_recorded_not_raised(monkeypatch):
    class _Explodes(BaseProvider):
        name, model = "explodes", "x"
        def chat(self, system, messages, tools=None):
            raise RuntimeError("something nobody expected")
    monkeypatch.setattr(ev, "get_provider", lambda: _Explodes())
    judgment = ev.judge_candidate(ELIGIBLE_RESULT)
    assert judgment.status == STATUS_FAILED
    assert judgment.error_category == "unexpected"


# --- prompt-injection / safety backstop ---------------------------------------------------------

def test_an_actionable_directive_in_reasoning_summary_is_overridden(monkeypatch):
    payload = json.loads(VALID_VERDICT_JSON)
    payload["reasoning_summary"] = "You should buy now, this is a guaranteed winner."
    stub = _StubProvider(response=_provider_response(json.dumps(payload)))
    monkeypatch.setattr(ev, "get_provider", lambda: stub)
    judgment = ev.judge_candidate(ELIGIBLE_RESULT)
    assert judgment.status == STATUS_OK  # the structured verdict still stands
    assert "won't turn this into a trade instruction" in judgment.verdict.reasoning_summary


def test_a_probability_claim_in_reasoning_summary_is_overridden(monkeypatch):
    payload = json.loads(VALID_VERDICT_JSON)
    payload["reasoning_summary"] = "There is a 85% chance this trade wins."
    stub = _StubProvider(response=_provider_response(json.dumps(payload)))
    monkeypatch.setattr(ev, "get_provider", lambda: stub)
    judgment = ev.judge_candidate(ELIGIBLE_RESULT)
    assert judgment.status == STATUS_OK
    assert "85%" not in judgment.verdict.reasoning_summary
