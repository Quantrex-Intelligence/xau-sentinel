"""Tests for ai/knowledge/store.py: persistence, versioning/deactivation,
and listing. Uses temp_db (isolated per-test SQLite file, from conftest.py)
so no test ever touches the developer's real database."""
import pytest

from ai.knowledge import store


@pytest.fixture(autouse=True)
def _knowledge_table(temp_db):
    return temp_db


def test_add_document_persists_chunks_with_embeddings():
    doc_id = store.add_document(
        source="test/doc.md", category="system_docs", version="1.0", title="Test Doc",
        content="This is a short test document about liquidity sweeps and market structure.",
    )
    assert doc_id > 0

    chunks = store.get_active_chunks()
    assert len(chunks) >= 1
    assert chunks[0]["document_id"] == doc_id
    assert chunks[0]["source"] == "test/doc.md"
    assert chunks[0]["category"] == "system_docs"
    assert chunks[0]["version"] == "1.0"
    assert isinstance(chunks[0]["embedding"], list)
    assert len(chunks[0]["embedding"]) > 0


def test_listing_documents_returns_metadata():
    store.add_document("test/a.md", "methodology", "1.0", "Doc A", "content about BOS and MSS")
    docs = store.list_documents()
    assert len(docs) == 1
    assert docs[0].source == "test/a.md"
    assert docs[0].category == "methodology"
    assert docs[0].version == "1.0"
    assert docs[0].title == "Doc A"
    assert docs[0].is_active is True


def test_empty_content_stores_a_document_with_zero_chunks():
    doc_id = store.add_document("test/empty.md", "user_notes", "1.0", "Empty", "   ")
    assert store.list_documents()[0].source == "test/empty.md"
    chunks = [c for c in store.get_active_chunks() if c["document_id"] == doc_id]
    assert chunks == []


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------

def test_re_adding_the_same_source_deactivates_the_prior_version():
    v1_id = store.add_document("test/versioned.md", "strategy_rules", "1.0", "Rules v1", "old content")
    v2_id = store.add_document("test/versioned.md", "strategy_rules", "2.0", "Rules v2", "new content")

    active = store.list_documents(active_only=True)
    assert len(active) == 1
    assert active[0].id == v2_id
    assert active[0].version == "2.0"

    all_docs = {d.id: d for d in store.list_documents(active_only=False)}
    assert all_docs[v1_id].is_active is False
    assert all_docs[v2_id].is_active is True


def test_only_active_version_chunks_are_returned_for_retrieval():
    store.add_document("test/versioned.md", "strategy_rules", "1.0", "Rules v1", "old wording about risk")
    store.add_document("test/versioned.md", "strategy_rules", "2.0", "Rules v2", "new wording about risk")

    chunks = store.get_active_chunks()
    assert len(chunks) == 1
    assert chunks[0]["version"] == "2.0"
    assert "new wording" in chunks[0]["text"]


def test_different_sources_do_not_deactivate_each_other():
    store.add_document("test/a.md", "system_docs", "1.0", "A", "content a")
    store.add_document("test/b.md", "system_docs", "1.0", "B", "content b")
    active = store.list_documents()
    assert {d.source for d in active} == {"test/a.md", "test/b.md"}


# ---------------------------------------------------------------------------
# Category filtering (used by retrieval to scope a search)
# ---------------------------------------------------------------------------

def test_get_active_chunks_can_filter_by_category():
    store.add_document("test/a.md", "strategy_rules", "1.0", "A", "strategy content")
    store.add_document("test/b.md", "fundednext_rules", "1.0", "B", "risk content")

    only_strategy = store.get_active_chunks(categories=["strategy_rules"])
    assert len(only_strategy) == 1
    assert only_strategy[0]["category"] == "strategy_rules"


def test_count_documents_reflects_active_only_by_default():
    store.add_document("test/a.md", "system_docs", "1.0", "A", "content")
    store.add_document("test/a.md", "system_docs", "2.0", "A v2", "content v2")
    assert store.count_documents() == 1  # only the active version
    assert store.count_documents(active_only=False) == 2  # both versions exist
