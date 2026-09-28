"""Tests for ai/assistant.py's Stage 6 tool-calling loop: sequential tool
execution, round-limit enforcement, deterministic tool-result authority
(the safety net still catches a directive produced AFTER a tool call),
conversation continuity (tool round trips are never persisted as history),
and the mock provider's real single-hop demo."""
from typing import List

import pytest

import config
from ai import assistant, prompts
from ai.providers.base import BaseProvider, ProviderResponse, ToolCall
from ai.providers.mock_provider import MockProvider


class _ScriptedProvider(BaseProvider):
    """Returns pre-programmed responses in order, recording every call it
    receives — precise, deterministic control over a multi-round exchange,
    with no real network/SDK dependency."""
    name = "fake"
    model = "fake-model"

    def __init__(self, responses: List[ProviderResponse]):
        self.responses = list(responses)
        self.calls: List[dict] = []

    def chat(self, system, messages, tools=None) -> ProviderResponse:
        self.calls.append({"system": system, "messages": [dict(m) for m in messages], "tools": tools})
        return self.responses.pop(0)


class _RecordingProvider(BaseProvider):
    name = "fake"
    model = "fake-model"

    def __init__(self, reply: str = "a helpful, safe answer"):
        self.reply = reply

    def chat(self, system, messages, tools=None) -> ProviderResponse:
        return ProviderResponse(text=self.reply, provider=self.name, model=self.model)


@pytest.fixture(autouse=True)
def _ai_table(temp_db):
    assistant.init_table()
    return temp_db


def _use_provider(monkeypatch, provider):
    monkeypatch.setattr(assistant, "get_provider", lambda: provider)


def _tool_use_response(*calls: ToolCall) -> ProviderResponse:
    return ProviderResponse(text="", provider="fake", model="fake-model",
                             tool_calls=list(calls), raw_content=list(calls))


def _text_response(text: str) -> ProviderResponse:
    return ProviderResponse(text=text, provider="fake", model="fake-model")


def test_tool_call_is_executed_and_result_is_fed_back(monkeypatch):
    provider = _ScriptedProvider([
        _tool_use_response(ToolCall(id="call-1", name="get_market_state", arguments={})),
        _text_response("Here is the current price based on the tool result."),
    ])
    _use_provider(monkeypatch, provider)

    result = assistant.chat("What's the current price?")

    assert result.answer == "Here is the current price based on the tool result."
    assert len(result.tools_used) == 1
    assert result.tools_used[0].name == "get_market_state"
    assert result.tools_used[0].label == "Market State"
    assert len(provider.calls) == 2
    second_messages = provider.calls[1]["messages"]
    assert any(m.get("role") == "tool_result" and m.get("tool_call_id") == "call-1" for m in second_messages)
    # The forced/plain final call still offers tools (it wasn't a round-cap forced call).
    assert provider.calls[1]["tools"] is not None


def test_round_limit_is_enforced_and_a_final_text_answer_is_forced(monkeypatch):
    always_tool_call = [
        _tool_use_response(ToolCall(id=f"call-{i}", name="get_market_state", arguments={}))
        for i in range(config.AI_TOOL_MAX_ROUNDS)
    ]
    provider = _ScriptedProvider(always_tool_call + [_text_response("Final forced answer.")])
    _use_provider(monkeypatch, provider)

    result = assistant.chat("Keep calling tools forever")

    assert result.answer == "Final forced answer."
    assert len(provider.calls) == config.AI_TOOL_MAX_ROUNDS + 1
    assert provider.calls[-1]["tools"] is None  # the forced final call offers no tools
    assert len(result.tools_used) == config.AI_TOOL_MAX_ROUNDS


def test_multiple_tool_calls_in_a_single_round_are_all_executed(monkeypatch):
    provider = _ScriptedProvider([
        _tool_use_response(
            ToolCall(id="c1", name="get_market_state", arguments={}),
            ToolCall(id="c2", name="get_risk_status", arguments={}),
        ),
        _text_response("Combined answer."),
    ])
    _use_provider(monkeypatch, provider)

    result = assistant.chat("Give me price and risk together")

    assert len(result.tools_used) == 2
    assert {t.name for t in result.tools_used} == {"get_market_state", "get_risk_status"}
    second_messages = provider.calls[1]["messages"]
    tool_result_ids = {m["tool_call_id"] for m in second_messages if m.get("role") == "tool_result"}
    assert tool_result_ids == {"c1", "c2"}


def test_unknown_tool_call_degrades_without_crashing_the_turn(monkeypatch):
    provider = _ScriptedProvider([
        _tool_use_response(ToolCall(id="c1", name="not_a_real_tool", arguments={})),
        _text_response("I could not retrieve that."),
    ])
    _use_provider(monkeypatch, provider)

    result = assistant.chat("Call a bogus tool")

    assert result.answer == "I could not retrieve that."
    assert result.tools_used[0].data_available is False


def test_tool_round_trip_messages_are_not_persisted_to_history(monkeypatch):
    provider = _ScriptedProvider([
        _tool_use_response(ToolCall(id="c1", name="get_market_state", arguments={})),
        _text_response("Answer using tool data."),
    ])
    _use_provider(monkeypatch, provider)

    assistant.chat("First question needing a tool", conversation_id="conv-tools")
    history = assistant._load_history("conv-tools")

    assert history == [
        {"role": "user", "content": "First question needing a tool"},
        {"role": "assistant", "content": "Answer using tool data."},
    ]


def test_tools_used_is_empty_list_when_no_tool_is_called(monkeypatch):
    """Backward-compatibility guarantee: a provider that never returns
    tool_calls (every pre-Stage-6 provider/test double) produces the exact
    same tools_used=[] as before tool calling existed."""
    _use_provider(monkeypatch, _RecordingProvider())
    result = assistant.chat("Plain question needing no tool")
    assert result.tools_used == []


def test_safety_override_still_catches_a_directive_produced_after_tool_use(monkeypatch):
    """Deterministic authority: even after a real tool round trip, the
    unconditional final-answer safety net (ai/prompts.py) still applies —
    a tool result is FACT-tier evidence, never license to skip the filter."""
    provider = _ScriptedProvider([
        _tool_use_response(ToolCall(id="c1", name="get_current_setup", arguments={})),
        _text_response("You should BUY NOW based on the setup."),
    ])
    _use_provider(monkeypatch, provider)

    result = assistant.chat("Should I enter based on the setup?")

    assert "BUY NOW" not in result.answer
    assert result.answer == prompts.SAFETY_OVERRIDE_MESSAGE


def test_context_used_unaffected_by_a_tool_calling_turn(monkeypatch):
    """RAG + tools together: the deterministic context_used/sources
    reporting (ai/context.py) is completely independent of whether the
    model also called a tool this turn."""
    provider = _ScriptedProvider([
        _tool_use_response(ToolCall(id="c1", name="get_market_state", arguments={})),
        _text_response("Answer."),
    ])
    _use_provider(monkeypatch, provider)

    result = assistant.chat("Question", context_scope=["market"])

    assert set(result.context_used) == {"Market Structure", "Setup"}


def test_mock_provider_demonstrates_a_real_single_hop_tool_round_trip(monkeypatch):
    """The mock provider's keyword heuristic offers a real, visible demo of
    the tool-calling loop with zero scripting — no real API key needed."""
    _use_provider(monkeypatch, MockProvider())

    result = assistant.chat("Why is this setup only developing?")

    assert len(result.tools_used) == 1
    assert result.tools_used[0].name == "get_current_setup"
    assert "MOCK PROVIDER" in result.answer


def test_mock_provider_answers_directly_when_no_keyword_matches(monkeypatch):
    _use_provider(monkeypatch, MockProvider())
    result = assistant.chat("hello there")
    assert result.tools_used == []


def test_mock_provider_scripted_tool_calls_drive_a_deterministic_sequence(monkeypatch):
    provider = MockProvider(scripted_tool_calls=[
        [ToolCall(id="c1", name="get_risk_status", arguments={})],
    ])
    _use_provider(monkeypatch, provider)

    result = assistant.chat("Any message")

    assert len(result.tools_used) == 1
    assert result.tools_used[0].name == "get_risk_status"
    assert "MOCK PROVIDER" in result.answer


def test_rag_memory_tools_and_similarity_work_together_in_one_turn(monkeypatch, temp_db):
    """Stage 8 integration: RAG (Stage 5), memory (Stage 7), a market tool
    (Stage 6), and find_similar_setups (Stage 8) can all contribute to a
    single turn without interfering with each other's reporting."""
    from ai.knowledge import store as knowledge_store
    from ai.memory import store as memory_store
    from ai.memory.models import MemoryCategory

    knowledge_store.init_table()
    knowledge_store.add_document(
        "test/strategy.md", "strategy_rules", "1.0", "Test Strategy Doc",
        "The reward to risk ratio must be at least three to one for an A+ rating.",
    )
    memory_store.init_table()
    memory_store.create_memory(
        MemoryCategory.TRADE_LESSON, "User repeatedly enters too early before the retracement completes.",
    )

    provider = _ScriptedProvider([
        _tool_use_response(
            ToolCall(id="c1", name="get_current_setup", arguments={}),
            ToolCall(id="c2", name="find_similar_setups", arguments={"min_similarity": 0.0}),
        ),
        _text_response("Combined answer using tools, RAG, and memory."),
    ])
    _use_provider(monkeypatch, provider)

    result = assistant.chat(
        "why do I enter too early, and what reward to risk ratio does the strategy require?"
    )

    assert result.answer == "Combined answer using tools, RAG, and memory."
    tool_names = {t.name for t in result.tools_used}
    assert tool_names == {"get_current_setup", "find_similar_setups"}
    assert len(result.knowledge_used) > 0
    assert len(result.memory_used) > 0
    assert set(result.context_used) == {"Market Structure", "Setup", "FundedNext Risk"}


def test_market_intelligence_tool_works_alongside_every_other_evidence_source(monkeypatch, temp_db):
    """Stage 9 integration: get_macro_context (new) contributes alongside
    RAG, memory, and a market tool in one turn without interfering with any
    of their reporting."""
    from ai.knowledge import store as knowledge_store
    from ai.memory import store as memory_store
    from ai.memory.models import MemoryCategory

    knowledge_store.init_table()
    knowledge_store.add_document(
        "test/strategy.md", "strategy_rules", "1.0", "Test Strategy Doc",
        "The reward to risk ratio must be at least three to one for an A+ rating.",
    )
    memory_store.init_table()
    memory_store.create_memory(
        MemoryCategory.TRADE_LESSON, "User repeatedly enters too early before the retracement completes.",
    )

    provider = _ScriptedProvider([
        _tool_use_response(
            ToolCall(id="c1", name="get_current_setup", arguments={}),
            ToolCall(id="c2", name="get_macro_context", arguments={}),
        ),
        _text_response("Combined answer using market intelligence alongside everything else."),
    ])
    _use_provider(monkeypatch, provider)

    result = assistant.chat(
        "why do I enter too early, and what reward to risk ratio does the strategy require?"
    )

    assert result.answer == "Combined answer using market intelligence alongside everything else."
    tool_names = {t.name for t in result.tools_used}
    assert tool_names == {"get_current_setup", "get_macro_context"}
    assert len(result.knowledge_used) > 0
    assert len(result.memory_used) > 0
    assert set(result.context_used) == {"Market Structure", "Setup", "FundedNext Risk"}


def test_full_setup_analysis_uses_several_tools_within_the_round_limit(monkeypatch, temp_db):
    """Stage 10: a "Analyze XAUUSD"-style request can call a sequence of
    several existing tools (never a new one) and still complete comfortably
    within AI_TOOL_MAX_ROUNDS — proves the round-limit protection from
    Stage 6 is untouched and still governs this richer request."""
    provider = _ScriptedProvider([
        _tool_use_response(ToolCall(id="c1", name="get_market_structure", arguments={})),
        _tool_use_response(ToolCall(id="c2", name="get_current_setup", arguments={})),
        _tool_use_response(ToolCall(id="c3", name="get_risk_status", arguments={})),
        _text_response(
            "Technical: H1 structure supports the bias. Strategy: setup is DEVELOPING, missing "
            "retracement. Risk: FundedNext is SAFE. AI Interpretation: evidence is broadly supportive."
        ),
    ])
    _use_provider(monkeypatch, provider)

    result = assistant.chat("Analyze XAUUSD — why is this setup developing?")

    assert len(provider.calls) <= config.AI_TOOL_MAX_ROUNDS + 1  # existing bound still governs
    tool_names = {t.name for t in result.tools_used}
    assert tool_names == {"get_market_structure", "get_current_setup", "get_risk_status"}
    assert "AI Interpretation" in result.answer
