"""Tests for ai/tools/memory_tools.py: search_memory/get_memory are pure
read wrappers over ai.memory — neither calls create/update/archive."""
from ai.memory import store
from ai.memory.models import MemoryCategory
from ai.tools import memory_tools


def test_search_memory_requires_a_query(temp_db):
    result = memory_tools.search_memory({"query": ""})
    assert result.data_available is False


def test_search_memory_returns_no_results_for_an_empty_store(temp_db):
    store.init_table()
    result = memory_tools.search_memory({"query": "anything"})
    assert result.data_available is True
    assert result.data["results"] == []


def test_search_memory_finds_a_relevant_record(temp_db):
    store.init_table()
    store.create_memory(MemoryCategory.TRADE_LESSON, "User repeatedly enters too early before retracement.")
    result = memory_tools.search_memory({"query": "why do I enter too early?"})
    assert result.data_available is True
    assert result.data["matched"] > 0


def test_get_memory_requires_a_memory_id(temp_db):
    result = memory_tools.get_memory({})
    assert result.data_available is False


def test_get_memory_unavailable_for_unknown_id(temp_db):
    store.init_table()
    result = memory_tools.get_memory({"memory_id": 999999})
    assert result.data_available is False


def test_get_memory_returns_the_record_including_archived_status(temp_db):
    store.init_table()
    record = store.create_memory(MemoryCategory.USER_PREFERENCE, "Prefers XAUUSD only.")
    store.archive_memory(record.id)

    result = memory_tools.get_memory({"memory_id": record.id})
    assert result.data_available is True
    assert result.data["memory"]["status"] == "ARCHIVED"


def test_memory_tools_module_never_calls_a_write_function():
    """search_memory/get_memory must only ever call ai.memory.store's
    read-only functions — this is also proven behaviorally in
    test_ai_memory_safety.py, but here we assert it structurally from the
    module's own source."""
    import inspect
    source = inspect.getsource(memory_tools)
    for banned in ("create_memory(", "update_memory(", "archive_memory("):
        assert banned not in source
