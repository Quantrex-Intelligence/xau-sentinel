"""Tests for ai/assistant.py's orchestration: conversation persistence,
the safety override, and the "LLM never becomes the source of truth" rule
(context_used/sources always come from ai/context.py, never parsed out of
the model's own text)."""
from typing import List

import pytest

import config
from ai import assistant, prompts
from ai.providers.base import BaseProvider, ProviderConfigError, ProviderRequestError, ProviderResponse
from ai.schemas import AnswerCategory


class _RecordingProvider(BaseProvider):
    """A fake provider that records exactly what it was asked, so tests can
    assert on history replay without any network or SDK dependency."""
    name = "fake"
    model = "fake-model"

    def __init__(self, reply: str = "a helpful, safe answer"):
        self.reply = reply
        self.calls: List[dict] = []

    def chat(self, system: str, messages: List[dict]) -> ProviderResponse:
        self.calls.append({"system": system, "messages": messages})
        return ProviderResponse(text=self.reply, provider=self.name, model=self.model)


class _FailingProvider(BaseProvider):
    name = "fake"
    model = "fake-model"

    def chat(self, system: str, messages: List[dict]) -> ProviderResponse:
        raise ProviderRequestError("simulated network failure")


@pytest.fixture(autouse=True)
def _ai_table(temp_db):
    assistant.init_table()
    return temp_db


def _use_provider(monkeypatch, provider):
    monkeypatch.setattr(assistant, "get_provider", lambda: provider)


def test_chat_creates_a_conversation_id_when_none_given(monkeypatch):
    provider = _RecordingProvider()
    _use_provider(monkeypatch, provider)

    result = assistant.chat("What is the current market structure?")
    assert result.conversation_id
    assert len(result.conversation_id) > 0


def test_chat_replays_history_on_the_next_turn(monkeypatch):
    provider = _RecordingProvider()
    _use_provider(monkeypatch, provider)

    first = assistant.chat("First question", conversation_id="conv-1")
    assistant.chat("Second question", conversation_id="conv-1")

    assert len(provider.calls) == 2
    # The first turn had no prior history.
    assert provider.calls[0]["messages"] == [{"role": "user", "content": "First question"}]
    # The second turn must replay the first question AND its (saved) answer.
    second_messages = provider.calls[1]["messages"]
    assert {"role": "user", "content": "First question"} in second_messages
    assert {"role": "assistant", "content": first.answer} in second_messages
    assert second_messages[-1] == {"role": "user", "content": "Second question"}


def test_different_conversation_ids_never_share_history(monkeypatch):
    provider = _RecordingProvider()
    _use_provider(monkeypatch, provider)

    assistant.chat("Hello from conversation A", conversation_id="conv-a")
    assistant.chat("Hello from conversation B", conversation_id="conv-b")

    b_messages = provider.calls[1]["messages"]
    assert all("conversation A" not in m["content"] for m in b_messages)


def test_nothing_is_persisted_when_the_provider_fails(monkeypatch):
    _use_provider(monkeypatch, _FailingProvider())

    with pytest.raises(ProviderRequestError):
        assistant.chat("This will fail", conversation_id="conv-fail")

    assert assistant._load_history("conv-fail") == []


def test_config_error_propagates_and_nothing_is_persisted(monkeypatch):
    monkeypatch.setattr(config, "AI_PROVIDER", "anthropic")
    monkeypatch.setattr(config, "AI_API_KEY", "")

    with pytest.raises(ProviderConfigError):
        assistant.chat("Anything", conversation_id="conv-unconfigured")

    assert assistant._load_history("conv-unconfigured") == []


def test_safety_override_replaces_an_actionable_directive(monkeypatch):
    _use_provider(monkeypatch, _RecordingProvider(reply="You should BUY NOW at market."))

    result = assistant.chat("Should I enter?")

    assert "BUY NOW" not in result.answer
    assert result.answer == prompts.SAFETY_OVERRIDE_MESSAGE
    assert result.category == AnswerCategory.UNKNOWN


def test_safety_override_does_not_trigger_on_a_plain_fact_restatement(monkeypatch):
    _use_provider(monkeypatch, _RecordingProvider(reply="Setup direction is BUY, per the setup engine."))

    result = assistant.chat("What does the setup engine say?")

    assert "Setup direction is BUY" in result.answer


def test_context_used_and_sources_come_from_context_builder_not_llm_text(monkeypatch):
    """The core Stage 3 rule: the LLM's prose must never be parsed to decide
    what context was used — an LLM that claims to have used the journal
    when it wasn't in scope must not be believed."""
    _use_provider(monkeypatch, _RecordingProvider(
        reply="I used the Journal and FundedNext Risk and Market Structure and everything else."
    ))

    result = assistant.chat("Question", context_scope=["market"])

    assert set(result.context_used) == {"Market Structure", "Setup"}
    assert "Journal" not in result.context_used
    assert "FundedNext Risk" not in result.context_used
    assert {s.label for s in result.sources} == {"Market Structure", "Setup"}


def test_default_scope_is_used_when_none_given(monkeypatch):
    _use_provider(monkeypatch, _RecordingProvider())
    result = assistant.chat("Question")
    assert set(result.context_used) == {"Market Structure", "Setup", "FundedNext Risk"}


def test_provider_and_model_are_reported_on_the_response(monkeypatch):
    _use_provider(monkeypatch, _RecordingProvider())
    result = assistant.chat("Question")
    assert result.provider == "fake"
    assert result.model == "fake-model"


def test_category_is_unknown_when_no_context_was_available(monkeypatch):
    _use_provider(monkeypatch, _RecordingProvider())
    result = assistant.chat("Question", context_scope=["journal"])  # no trades in temp_db -> unavailable
    assert result.category == AnswerCategory.UNKNOWN


def test_knowledge_used_is_empty_list_when_knowledge_base_has_no_relevant_result(monkeypatch):
    """Stage 5 regression: chat()'s existing behavior (answer, context_used,
    sources, category) must be completely unaffected when retrieval finds
    nothing — including when the knowledge tables don't exist at all yet
    (this test's temp_db never initializes them), which is what every test
    above this one in the file already exercises implicitly."""
    _use_provider(monkeypatch, _RecordingProvider(reply="a helpful, safe answer"))
    result = assistant.chat("Question")
    assert result.knowledge_used == []
    # Everything else about the response is exactly as it was pre-Stage-5.
    assert result.answer == "a helpful, safe answer"
    assert set(result.context_used) == {"Market Structure", "Setup", "FundedNext Risk"}


def test_knowledge_used_is_populated_when_a_relevant_document_exists(monkeypatch, temp_db):
    from ai.knowledge import store
    store.init_table()
    store.add_document(
        "test/strategy.md", "strategy_rules", "1.0", "Test Strategy Doc",
        "The reward to risk ratio must be at least three to one for an A+ rating.",
    )
    _use_provider(monkeypatch, _RecordingProvider())

    result = assistant.chat("what reward to risk ratio does the strategy require?")

    assert len(result.knowledge_used) > 0
    assert result.knowledge_used[0].source == "test/strategy.md"
    assert result.knowledge_used[0].category == "strategy_rules"
    # Unaffected by the addition — same as the empty-KB case above.
    assert set(result.context_used) == {"Market Structure", "Setup", "FundedNext Risk"}


def test_secret_api_key_never_leaks_into_the_response(monkeypatch):
    secret = "sk-test-super-secret-value-should-never-leak"
    monkeypatch.setattr(config, "AI_API_KEY", secret)
    _use_provider(monkeypatch, _RecordingProvider(reply="An ordinary answer."))

    result = assistant.chat("Question")

    assert secret not in result.answer
    assert secret not in str(result.model_dump())
