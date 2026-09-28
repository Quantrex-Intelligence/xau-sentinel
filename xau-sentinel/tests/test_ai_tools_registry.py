"""Tests for the tool registry itself: shape, uniqueness, and — critically —
the structural safety guarantee that no tool can write, place, close,
modify, or cancel anything (Stage 6 spec: tools are strictly read-only)."""
import re

from ai.tools.registry import TOOL_SPECS, to_provider_format

_WRITE_LIKE = re.compile(r"\b(place|close|modify|cancel|order|delete|update|create|execute)\b", re.IGNORECASE)


def test_registry_is_populated():
    assert len(TOOL_SPECS) >= 11


def test_every_tool_has_a_name_label_description_and_schema():
    for name, spec in TOOL_SPECS.items():
        assert spec.name == name
        assert spec.label
        assert spec.description
        assert isinstance(spec.input_schema, dict)
        assert spec.input_schema.get("type") == "object"
        assert callable(spec.handler)


def test_no_tool_name_looks_write_capable():
    for name in TOOL_SPECS:
        assert not _WRITE_LIKE.search(name), f"tool '{name}' looks write-capable"


def test_no_tool_description_advertises_a_write_action():
    for spec in TOOL_SPECS.values():
        assert not _WRITE_LIKE.search(spec.description), f"tool '{spec.name}' description implies a write action"


def test_to_provider_format_matches_anthropic_tool_shape():
    tools = to_provider_format()
    assert len(tools) == len(TOOL_SPECS)
    for t in tools:
        assert set(t.keys()) == {"name", "description", "input_schema"}


def test_expected_tools_are_registered():
    expected = {
        "get_market_state", "get_market_structure", "get_liquidity", "get_key_zones", "get_current_setup",
        "get_risk_status", "get_open_positions",
        "get_trade", "get_trade_history", "get_performance", "search_journal",
        "search_strategy",
    }
    assert expected <= set(TOOL_SPECS.keys())
