"""Tests for ai/tools/executor.py: a tool call can degrade, but it can never
crash the turn, never fabricate data, and an unknown tool or missing
required argument must come back as a structured, data_available=False
result rather than an exception."""
from ai.tools import registry
from ai.tools.executor import execute
from ai.tools.schemas import ToolResult


def test_unknown_tool_returns_structured_error():
    result = execute("this_tool_does_not_exist", {})
    assert result["data_available"] is False
    assert "this_tool_does_not_exist" in result["reason"]


def test_missing_required_argument_returns_structured_error():
    result = execute("get_trade", {})  # trade_id is required
    assert result["data_available"] is False
    assert "trade_id" in result["reason"]


def test_handler_exception_is_caught_and_never_propagates(monkeypatch):
    def _boom(_args):
        raise RuntimeError("simulated tool failure")

    monkeypatch.setattr(registry.TOOL_SPECS["get_market_state"], "handler", _boom)
    result = execute("get_market_state", {})
    assert result["data_available"] is False
    assert "simulated tool failure" in result["reason"]


def test_successful_handler_result_is_serialized_to_a_plain_dict(monkeypatch):
    def _fake(_args):
        return ToolResult(data_available=True, timestamp="2026-01-01T00:00:00+00:00",
                           source="test", data={"foo": "bar"})

    monkeypatch.setattr(registry.TOOL_SPECS["get_market_state"], "handler", _fake)
    result = execute("get_market_state", {})
    assert result == {
        "data_available": True, "timestamp": "2026-01-01T00:00:00+00:00", "source": "test", "foo": "bar",
    }


def test_execute_treats_none_arguments_as_empty_dict():
    result = execute("get_market_state", None)
    assert "data_available" in result  # never raises on None args
