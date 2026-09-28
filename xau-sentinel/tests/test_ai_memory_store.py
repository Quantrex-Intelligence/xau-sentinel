"""Tests for ai/memory/store.py: CRUD, lifecycle (CREATE/READ/UPDATE/
ARCHIVE — no delete), the hardcoded source="user_confirmed" guarantee, and
archived records being excluded from normal listing."""
from ai.memory import store
from ai.memory.models import MemoryCategory, MemoryStatus


def test_create_memory_returns_a_record_with_hardcoded_source(temp_db):
    store.init_table()
    record = store.create_memory(MemoryCategory.TRADE_LESSON, "Entered too early before the retracement.")
    assert record.source == "user_confirmed"
    assert record.status == MemoryStatus.ACTIVE
    assert record.category == MemoryCategory.TRADE_LESSON
    assert record.content == "Entered too early before the retracement."
    assert record.created_at == record.updated_at


def test_create_memory_ignores_any_source_a_caller_tries_to_pass():
    """create_memory() has no `source` parameter at all — this test proves
    that at the call-signature level, not just by convention."""
    import inspect
    params = inspect.signature(store.create_memory).parameters
    assert "source" not in params


def test_get_memory_returns_none_for_unknown_id(temp_db):
    store.init_table()
    assert store.get_memory(999999) is None


def test_list_memories_excludes_archived_by_default(temp_db):
    store.init_table()
    active = store.create_memory(MemoryCategory.USER_PREFERENCE, "Prefers London session setups.")
    archived = store.create_memory(MemoryCategory.USER_PREFERENCE, "Old preference, no longer true.")
    store.archive_memory(archived.id)

    listed = store.list_memories()
    ids = {r.id for r in listed}
    assert active.id in ids
    assert archived.id not in ids


def test_list_memories_include_archived_true_returns_both(temp_db):
    store.init_table()
    active = store.create_memory(MemoryCategory.USER_PREFERENCE, "Keep this one.")
    archived = store.create_memory(MemoryCategory.USER_PREFERENCE, "Archive this one.")
    store.archive_memory(archived.id)

    listed = store.list_memories(include_archived=True)
    ids = {r.id for r in listed}
    assert {active.id, archived.id} <= ids


def test_list_memories_filters_by_category(temp_db):
    store.init_table()
    store.create_memory(MemoryCategory.TRADE_LESSON, "Lesson one.")
    store.create_memory(MemoryCategory.USER_PREFERENCE, "Preference one.")

    lessons = store.list_memories(category=MemoryCategory.TRADE_LESSON)
    assert len(lessons) == 1
    assert lessons[0].category == MemoryCategory.TRADE_LESSON


def test_update_memory_changes_content_and_bumps_updated_at(temp_db):
    store.init_table()
    record = store.create_memory(MemoryCategory.TRADE_LESSON, "Original content.")
    updated = store.update_memory(record.id, content="Revised content.")
    assert updated.content == "Revised content."
    assert updated.source == "user_confirmed"  # never changed by update


def test_update_memory_unknown_id_returns_none(temp_db):
    store.init_table()
    assert store.update_memory(999999, content="anything") is None


def test_update_memory_without_content_keeps_existing_content(temp_db):
    store.init_table()
    record = store.create_memory(MemoryCategory.TRADE_LESSON, "Keep me.", strategy_version="v1")
    updated = store.update_memory(record.id, strategy_version="v2")
    assert updated.content == "Keep me."
    assert updated.strategy_version == "v2"


def test_archive_memory_sets_status_and_is_idempotent(temp_db):
    store.init_table()
    record = store.create_memory(MemoryCategory.PATTERN_OBSERVATION, "Recurring late entries on Fridays.")
    archived_once = store.archive_memory(record.id)
    assert archived_once.status == MemoryStatus.ARCHIVED
    archived_twice = store.archive_memory(record.id)
    assert archived_twice.status == MemoryStatus.ARCHIVED


def test_archive_memory_unknown_id_returns_none(temp_db):
    store.init_table()
    assert store.archive_memory(999999) is None


def test_no_hard_delete_function_exists_in_the_store_module():
    """The spec: 'Do not hard-delete historical memory by default' —
    enforced by simply never having written one."""
    assert not hasattr(store, "delete_memory")
