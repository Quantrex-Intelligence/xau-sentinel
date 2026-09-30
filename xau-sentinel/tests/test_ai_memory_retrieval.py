"""Tests for ai/memory/retrieval.py: threshold/top-K behavior (same shape
as Stage 5's knowledge retrieval), archived memories never surfacing, and
conflicting/multiple relevant memories both being returned rather than
deduplicated."""
from ai.memory import store
from ai.memory.models import MemoryCategory
from ai.memory import retrieval


def test_retrieve_memory_returns_empty_for_a_blank_query(temp_db):
    assert retrieval.retrieve_memory("") == []
    assert retrieval.retrieve_memory("   ") == []


def test_retrieve_memory_returns_empty_when_no_memory_exists(temp_db):
    assert retrieval.retrieve_memory("early entries") == []


def test_retrieve_memory_finds_a_relevant_record(temp_db):
    store.create_memory(MemoryCategory.TRADE_LESSON,
                         "User repeatedly enters too early before the retracement completes.")
    results = retrieval.retrieve_memory("why do I enter too early?")
    assert len(results) > 0
    assert "early" in results[0].content.lower()


def test_retrieve_memory_never_surfaces_an_archived_record(temp_db):
    record = store.create_memory(MemoryCategory.TRADE_LESSON,
                                  "User repeatedly enters too early before the retracement completes.")
    store.archive_memory(record.id)
    results = retrieval.retrieve_memory("why do I enter too early?")
    assert results == []


def test_retrieve_memory_returns_unrelated_off_topic_query_empty(temp_db):
    store.create_memory(MemoryCategory.TRADE_LESSON,
                         "User repeatedly enters too early before the retracement completes.")
    results = retrieval.retrieve_memory("what is the capital of France?")
    assert results == []


def test_retrieve_memory_respects_category_filter(temp_db):
    store.create_memory(MemoryCategory.TRADE_LESSON, "Early entry lesson about retracements.")
    store.create_memory(MemoryCategory.USER_PREFERENCE, "Prefers trading the retracement into London open.")
    only_lessons = retrieval.retrieve_memory("retracement", categories=["TRADE_LESSON"])
    assert all(r.category == MemoryCategory.TRADE_LESSON for r in only_lessons)


def test_retrieve_memory_returns_conflicting_memories_both_not_deduplicated(temp_db):
    """Two memories that disagree must both come back, ranked by
    similarity — retrieval never picks a winner (see ai/prompts.py ground
    rule 8: surface a conflict, don't silently reconcile it)."""
    store.create_memory(MemoryCategory.STRATEGY_MEMORY,
                         "User confirmed the stop-loss buffer should be 0.30 above the swept level.")
    store.create_memory(MemoryCategory.STRATEGY_MEMORY,
                         "User confirmed the stop-loss buffer should be 0.50 above the swept level.")
    results = retrieval.retrieve_memory("what stop-loss buffer did I confirm?")
    assert len(results) == 2


def test_retrieve_memory_respects_top_k(temp_db, monkeypatch):
    import config
    monkeypatch.setattr(config, "AI_MEMORY_TOP_K", 1)
    store.create_memory(MemoryCategory.TRADE_LESSON, "Early entry lesson number one about retracements.")
    store.create_memory(MemoryCategory.TRADE_LESSON, "Early entry lesson number two about retracements.")
    results = retrieval.retrieve_memory("early entry retracement lesson")
    assert len(results) <= 1
