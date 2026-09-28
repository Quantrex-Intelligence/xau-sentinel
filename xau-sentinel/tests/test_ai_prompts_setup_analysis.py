"""Tests for ai/prompts.py's ground rule 11 (Stage 10) — the chat-path
guidance for a full setup/market analysis request. This is prompt text
only (no new tool, no new code path in ai/assistant.py), so these tests
check its presence/wording the same way every other stage's ground rule
has been tested."""
from ai import prompts
from ai.context import AssembledContext


def test_ground_rule_11_names_the_expected_sections():
    prompt = prompts.build_system_prompt(AssembledContext(sections=[]))
    assert "11. When asked for a full setup or market analysis" in prompt
    for section in ("Technical", "Strategy", "Market Intelligence", "Historical Context", "Risk", "AI"):
        assert section in prompt


def test_ground_rule_11_instructs_against_padding_irrelevant_sections():
    prompt = prompts.build_system_prompt(AssembledContext(sections=[]))
    assert "rather than padding it" in prompt
    assert "never call every tool" in prompt.lower()
