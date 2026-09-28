"""A deterministic, offline provider — no network call, no API key, no
external dependency. Selected with AI_PROVIDER=mock, and used directly by
the test suite so the ai/ layer can be exercised without depending on
network access or a real credential.

Its answers are template text built only from what it was given (the last
user message, and whether a context block is present) — never a
fabrication, and never claiming to be a real model's output (the text says
"[MOCK PROVIDER]" up front, same spirit as the rest of the app never
presenting mock data as live).

Stage 6, strictly additive: chat() called with no `tools` (or an empty
list) is byte-for-byte identical to the pre-Stage-6 behavior above — every
Stage 3/4/5 test and E2E checklist that never passes `tools` keeps passing
unmodified. When `tools` IS passed, this provider can either:
  - follow an explicit `scripted_tool_calls` sequence given at construction,
    for precise, deterministic multi-round test control, or
  - fall back to a simple keyword heuristic over the last user message, for
    a real, visible single-hop tool-call demo in mock mode with no scripting
    needed (e.g. "why is this setup only developing?" -> get_current_setup).
The heuristic is deliberately simple substring matching, not semantic
understanding — a known limitation of the mock provider, not of tool
calling itself (a real provider chooses tools with the model's own
judgment).
"""
import re
from typing import Dict, List, Optional

from ai.providers.base import BaseProvider, ProviderResponse, ToolCall

MODEL_NAME = "mock-deterministic-v1"

# Keyword -> tool name, checked in this order (first match wins). Only
# tools that need no more than an optional query/id are offered here;
# get_trade is reachable via scripted_tool_calls in tests, or when the
# message names a specific trade number.
_TOOL_KEYWORDS: Dict[str, List[str]] = {
    "get_current_setup": ["setup", "developing", "checklist"],
    "get_market_structure": ["structure", "bos", "mss", "bullish", "bearish"],
    "get_liquidity": ["liquidity", "sweep", "equal high", "equal low"],
    "get_key_zones": ["zone", "level"],
    "get_risk_status": ["risk", "drawdown", "daily loss", "safety", "violation"],
    "get_open_positions": ["open position", "position"],
    "get_performance": ["performance", "win rate", "profit factor"],
    "get_trade_history": ["trade history", "recent trades", "past trades"],
    "search_journal": ["journal", "my notes", "mistake"],
    "search_strategy": ["strategy", "a+ ", "a plus", "rule"],
    "get_market_state": ["price", "spread", "session", "market state"],
}

_TRADE_ID_PATTERN = re.compile(r"trade\s*#?\s*(\d+)", re.IGNORECASE)


class MockProvider(BaseProvider):
    name = "mock"
    model = MODEL_NAME

    def __init__(self, scripted_tool_calls: Optional[List[List[ToolCall]]] = None):
        # An explicit sequence of tool-call batches, one per round, for
        # deterministic multi-round test control. None (the default) means
        # "use the keyword heuristic instead" — untouched for every caller
        # that never passes this.
        self._scripted = list(scripted_tool_calls) if scripted_tool_calls is not None else None
        self._round = 0

    def chat(self, system: str, messages: List[dict], tools: Optional[List[dict]] = None) -> ProviderResponse:
        last_user = next(
            (m["content"] for m in reversed(messages)
             if m.get("role") == "user" and isinstance(m.get("content"), str)),
            "",
        )
        has_context = "CONTEXT" in system

        if not tools:
            return _plain_text_response(last_user, has_context)

        if self._scripted is not None:
            return self._scripted_response(last_user)

        if any(m.get("role") == "tool_result" for m in messages):
            return _final_response_after_tools(last_user, messages)

        return _maybe_request_tool(last_user, tools, has_context)

    def _scripted_response(self, last_user: str) -> ProviderResponse:
        if self._round < len(self._scripted):
            calls = self._scripted[self._round]
            self._round += 1
            if calls:
                return ProviderResponse(text="", provider=self.name, model=MODEL_NAME,
                                         tool_calls=calls, raw_content=calls)
        return _final_response_after_tools(last_user, [])


def _plain_text_response(last_user: str, has_context: bool) -> ProviderResponse:
    text = (
        "[MOCK PROVIDER — offline, deterministic, no API key used]\n"
        f"You asked: {last_user}\n\n"
        + (
            "I reviewed the context block in the system prompt above and would normally "
            "answer from it alone."
            if has_context
            else "No context block was supplied."
        )
        + " This is a template response — set AI_PROVIDER=anthropic and AI_API_KEY for real answers."
    )
    return ProviderResponse(text=text, provider="mock", model=MODEL_NAME)


def _final_response_after_tools(last_user: str, messages: List[dict]) -> ProviderResponse:
    results = [m["content"] for m in messages if m.get("role") == "tool_result"]
    text = (
        "[MOCK PROVIDER — offline, deterministic, no API key used]\n"
        f"You asked: {last_user}\n\n"
        f"Based on the tool result(s) retrieved above ({len(results)} tool call(s)), here is a "
        "template answer grounded in that data. "
        "This is a template response — set AI_PROVIDER=anthropic and AI_API_KEY for real answers."
    )
    return ProviderResponse(text=text, provider="mock", model=MODEL_NAME)


def _maybe_request_tool(last_user: str, tools: List[dict], has_context: bool) -> ProviderResponse:
    available = {t["name"] for t in tools}
    tool_name = _match_tool(last_user, available)
    if tool_name is None:
        return _plain_text_response(last_user, has_context)
    call = ToolCall(id="mock-call-1", name=tool_name, arguments=_build_arguments(tool_name, last_user))
    return ProviderResponse(text="", provider="mock", model=MODEL_NAME, tool_calls=[call], raw_content=[call])


def _match_tool(message: str, available: set) -> Optional[str]:
    lowered = message.lower()
    for tool_name, keywords in _TOOL_KEYWORDS.items():
        if tool_name in available and any(kw in lowered for kw in keywords):
            return tool_name
    return None


def _build_arguments(tool_name: str, message: str) -> dict:
    if tool_name in ("search_journal", "search_strategy"):
        return {"query": message}
    if tool_name == "get_trade":
        match = _TRADE_ID_PATTERN.search(message)
        return {"trade_id": int(match.group(1))} if match else {}
    return {}
