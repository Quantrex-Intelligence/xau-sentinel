"""Tests for ai/verification.py's judge_answer() -- the pure OK/VIOLATION
parsing logic, mirroring tests/test_prompt_safety_hardening.py's style for
the other deterministic/LLM-backstop checks."""
from typing import List

from ai.providers.base import BaseProvider, ProviderResponse
from ai.verification import judge_answer


class _RecordingProvider(BaseProvider):
    name = "fake"
    model = "fake-model"

    def __init__(self, reply: str):
        self.reply = reply
        self.calls: List[dict] = []

    def chat(self, system: str, messages: List[dict], tools=None) -> ProviderResponse:
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        return ProviderResponse(text=self.reply, provider=self.name, model=self.model)


def test_ok_verdict_is_not_a_violation():
    provider = _RecordingProvider("OK")

    verdict = judge_answer(provider, "What is the current bias?", "H1 structure: BULLISH", "Bias is bullish.")

    assert verdict.violated is False
    assert verdict.reason is None


def test_violation_verdict_is_parsed_with_its_reason():
    provider = _RecordingProvider("VIOLATION: cites the setup bias while answering an unrelated question")

    verdict = judge_answer(provider, "Should I gamble?", "Setup: DEVELOPING (SELL)", "...setup is flagging a sell bias...")

    assert verdict.violated is True
    assert verdict.reason == "cites the setup bias while answering an unrelated question"


def test_violation_with_no_colon_still_flags_as_violated():
    provider = _RecordingProvider("VIOLATION")

    verdict = judge_answer(provider, "q", "c", "a")

    assert verdict.violated is True
    assert verdict.reason == "VIOLATION"


def test_verdict_check_is_case_insensitive_and_trims_whitespace():
    provider = _RecordingProvider("  violation: lowercase  ")

    verdict = judge_answer(provider, "q", "c", "a")

    assert verdict.violated is True


def test_judge_call_never_offers_tools():
    provider = _RecordingProvider("OK")

    judge_answer(provider, "q", "c", "a")

    assert provider.calls[0]["tools"] is None


def test_judge_call_includes_question_context_and_draft_answer():
    provider = _RecordingProvider("OK")

    judge_answer(provider, "What is the bias?", "H1: BULLISH", "Bias leans bullish.")

    sent = provider.calls[0]["messages"][0]["content"]
    assert "What is the bias?" in sent
    assert "H1: BULLISH" in sent
    assert "Bias leans bullish." in sent
