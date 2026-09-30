"""Tests for ai/tools/knowledge_tools.py::search_strategy — a thin exposure
of ai.knowledge.retrieval.retrieve() (Stage 5, unchanged) as an explicitly
callable tool, alongside the always-on per-turn retrieval."""
from ai.knowledge import store
from ai.tools import knowledge_tools


def test_search_strategy_requires_a_query():
    result = knowledge_tools.search_strategy({"query": ""})
    assert result.data_available is False


def test_search_strategy_returns_no_results_for_an_empty_knowledge_base(temp_db):
    result = knowledge_tools.search_strategy({"query": "reward to risk ratio"})
    assert result.data_available is True
    assert result.data["results"] == []


def test_search_strategy_finds_a_seeded_relevant_document(temp_db):
    store.add_document(
        "test/strategy.md", "strategy_rules", "1.0", "Test Strategy Doc",
        "The reward to risk ratio must be at least three to one for an A+ rating.",
    )
    result = knowledge_tools.search_strategy({"query": "what reward to risk ratio does the strategy require?"})
    assert result.data_available is True
    assert result.data["matched"] > 0
    assert result.data["results"][0]["source"] == "test/strategy.md"
