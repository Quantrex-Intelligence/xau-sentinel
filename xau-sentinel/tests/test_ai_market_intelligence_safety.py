"""Safety tests for Stage 9: ground rule 10's presence, no-fabrication on a
misconfigured/unavailable provider, and the tools' structural read-only
guarantee."""
import inspect

import config
from ai import prompts
from ai.context import AssembledContext
from ai.tools import market_intelligence_tools as mi_tools


def test_ground_rule_10_is_present_and_names_the_new_tools():
    prompt = prompts.build_system_prompt(AssembledContext(sections=[]))
    assert "10. Tools may return Market Intelligence" in prompt
    assert "get_macro_context" in prompt
    assert "never change a deterministic" in prompt


def test_ground_rule_10_forbids_treating_news_as_a_forecast():
    prompt = prompts.build_system_prompt(AssembledContext(sections=[]))
    assert "not a signal to act on" in prompt
    assert "never translate one into a trade instruction" in prompt


def test_ground_rule_10_names_the_explicit_quality_labels():
    prompt = prompts.build_system_prompt(AssembledContext(sections=[]))
    assert "LIVE/STALE/UNAVAILABLE/MOCK" in prompt
    assert "RELEVANT/NOT_RELEVANT/UNKNOWN" in prompt


def test_ground_rule_10_forbids_filling_missing_values_from_own_knowledge():
    prompt = prompts.build_system_prompt(AssembledContext(sections=[]))
    assert "never guessed at or" in prompt
    assert "filled in from your own general knowledge" in prompt


def test_unavailable_macro_provider_never_fabricates_a_value(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_MACRO_PROVIDER", "not-a-real-provider")
    result = mi_tools.get_macro_context({})
    assert result.data_available is False
    assert result.reason
    assert "macro" not in result.data
    assert "fed_funds_rate" not in str(result.data)


def test_market_intelligence_tools_module_never_calls_a_write_function():
    source = inspect.getsource(mi_tools)
    for banned in ("save_", "write_", "insert", "INSERT INTO", "conn.execute", "conn.commit"):
        assert banned not in source


def test_market_intelligence_provider_modules_never_call_a_write_function():
    from ai.market_intelligence.providers import mock as mock_mod
    from ai.market_intelligence import context as context_mod
    for module in (mock_mod, context_mod):
        source = inspect.getsource(module)
        for banned in ("INSERT INTO", "conn.execute", "conn.commit", "get_connection"):
            assert banned not in source
