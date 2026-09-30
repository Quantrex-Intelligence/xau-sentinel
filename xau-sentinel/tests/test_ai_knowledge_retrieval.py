"""Tests for ai/knowledge/retrieval.py: relevant retrieval, irrelevant
rejection, empty knowledge base, source attribution, category filtering,
and version handling."""
import pytest

from ai.knowledge import retrieval, store


@pytest.fixture(autouse=True)
def _knowledge_table(temp_db):
    return temp_db


def _seed_realistic_corpus():
    store.add_document(
        "ai/strategy/rules.py", "strategy_rules", "1.0", "Locked A+ Strategy Rules",
        "Reward to risk ratio must be at least the configured minimum, computed from the actual "
        "entry, stop-loss, and target. The stop-loss sits beyond the swept liquidity level by a "
        "configurable buffer. A minimum reward:risk of 1:3 is required for an A+ rating.",
    )
    store.add_document(
        "risk/rules.py", "fundednext_rules", "1.0", "FundedNext Risk Rules",
        "The daily loss limit resets at 00:00 server time. FundedNext measures both the daily "
        "loss limit and the maximum loss limit against equity, including open floating profit "
        "and loss. The maximum loss limit is a static floor computed from the initial balance.",
    )
    store.add_document(
        "analysis/structure.py", "methodology", "1.0", "Trading Methodology",
        "A liquidity sweep requires price to trade beyond a known level by a buffer and close "
        "back on the other side. A wick that merely grazes a level does not count as a sweep. "
        "Market structure shift means an actual shift just happened, not an established trend.",
    )


def test_relevant_query_returns_the_matching_document():
    _seed_realistic_corpus()
    results = retrieval.retrieve("what reward to risk ratio does the A+ strategy require?")
    assert len(results) > 0
    assert any(r.source == "ai/strategy/rules.py" for r in results)


def test_irrelevant_query_returns_no_results():
    _seed_realistic_corpus()
    results = retrieval.retrieve("what is the best recipe for chocolate chip cookies?")
    assert results == []


def test_empty_knowledge_base_returns_no_results_without_crashing():
    # No documents seeded at all.
    results = retrieval.retrieve("what does the A+ strategy require?")
    assert results == []


def test_blank_query_returns_no_results():
    _seed_realistic_corpus()
    assert retrieval.retrieve("") == []
    assert retrieval.retrieve("   ") == []


def test_source_attribution_fields_are_populated():
    _seed_realistic_corpus()
    results = retrieval.retrieve("how does the FundedNext daily loss limit reset?")
    assert len(results) > 0
    top = results[0]
    assert top.source == "risk/rules.py"
    assert top.category == "fundednext_rules"
    assert top.version == "1.0"
    assert top.title == "FundedNext Risk Rules"
    assert 0.0 <= top.similarity <= 1.0
    assert isinstance(top.text, str) and len(top.text) > 0


def test_category_filter_restricts_results():
    _seed_realistic_corpus()
    results = retrieval.retrieve("what are the rules?", categories=["fundednext_rules"])
    assert all(r.category == "fundednext_rules" for r in results)


def test_version_handling_only_returns_the_active_version():
    store.add_document("versioned/doc.md", "strategy_rules", "1.0", "Old Rules",
                        "reward risk ratio minimum requirement old wording")
    store.add_document("versioned/doc.md", "strategy_rules", "2.0", "New Rules",
                        "reward risk ratio minimum requirement new wording")

    results = retrieval.retrieve("reward risk ratio minimum requirement")
    versions_returned = {r.version for r in results if r.source == "versioned/doc.md"}
    assert versions_returned == {"2.0"}


def test_top_k_limits_result_count():
    _seed_realistic_corpus()
    results = retrieval.retrieve("strategy risk structure liquidity", top_k=1)
    assert len(results) <= 1


def test_results_are_sorted_by_similarity_descending():
    _seed_realistic_corpus()
    results = retrieval.retrieve("liquidity sweep and market structure shift definitions", top_k=5)
    similarities = [r.similarity for r in results]
    assert similarities == sorted(similarities, reverse=True)
