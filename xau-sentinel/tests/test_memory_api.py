"""API-level tests for /api/ai/memory/* — CRUD routes, the lifecycle
(create/read/update/archive, no delete route exists), and proof that a
client cannot set `source` via the create payload."""
import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture
def api_client(temp_db):
    with TestClient(app) as client:
        yield client


def test_list_memories_starts_empty(api_client):
    resp = api_client.get("/api/ai/memory")
    assert resp.status_code == 200
    assert resp.json() == []


def test_create_memory_persists_and_is_listed(api_client):
    resp = api_client.post("/api/ai/memory", json={
        "category": "TRADE_LESSON", "content": "Entered too early before the retracement.",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "user_confirmed"
    assert body["status"] == "ACTIVE"

    listed = api_client.get("/api/ai/memory").json()
    assert any(m["id"] == body["id"] for m in listed)


def test_create_memory_ignores_a_client_supplied_source_field(api_client):
    """MemoryCreateIn has no `source` field — extra fields are ignored by
    Pydantic's default config, and the server always writes
    'user_confirmed' regardless of what a crafted request body includes."""
    resp = api_client.post("/api/ai/memory", json={
        "category": "TRADE_LESSON", "content": "Trying to fake the source.", "source": "assistant_auto",
    })
    assert resp.status_code == 200
    assert resp.json()["source"] == "user_confirmed"


def test_create_memory_rejects_an_unknown_category(api_client):
    resp = api_client.post("/api/ai/memory", json={"category": "NOT_A_REAL_CATEGORY", "content": "x"})
    assert resp.status_code == 422  # pydantic enum validation


def test_get_memory_returns_404_for_unknown_id(api_client):
    resp = api_client.get("/api/ai/memory/999999")
    assert resp.status_code == 404


def test_get_memory_returns_the_created_record(api_client):
    created = api_client.post("/api/ai/memory", json={
        "category": "USER_PREFERENCE", "content": "Prefers London session.",
    }).json()
    resp = api_client.get(f"/api/ai/memory/{created['id']}")
    assert resp.status_code == 200
    assert resp.json()["content"] == "Prefers London session."


def test_update_memory_changes_content(api_client):
    created = api_client.post("/api/ai/memory", json={
        "category": "STRATEGY_MEMORY", "content": "Original.",
    }).json()
    resp = api_client.patch(f"/api/ai/memory/{created['id']}", json={"content": "Revised."})
    assert resp.status_code == 200
    assert resp.json()["content"] == "Revised."


def test_update_memory_returns_404_for_unknown_id(api_client):
    resp = api_client.patch("/api/ai/memory/999999", json={"content": "x"})
    assert resp.status_code == 404


def test_archive_memory_excludes_it_from_default_listing(api_client):
    created = api_client.post("/api/ai/memory", json={
        "category": "PATTERN_OBSERVATION", "content": "Recurring late entries on Fridays.",
    }).json()

    archive_resp = api_client.post(f"/api/ai/memory/{created['id']}/archive")
    assert archive_resp.status_code == 200
    assert archive_resp.json()["status"] == "ARCHIVED"

    default_listing = api_client.get("/api/ai/memory").json()
    assert not any(m["id"] == created["id"] for m in default_listing)

    full_listing = api_client.get("/api/ai/memory", params={"include_archived": True}).json()
    assert any(m["id"] == created["id"] for m in full_listing)


def test_archive_memory_returns_404_for_unknown_id(api_client):
    resp = api_client.post("/api/ai/memory/999999/archive")
    assert resp.status_code == 404


def test_list_memories_filters_by_category(api_client):
    api_client.post("/api/ai/memory", json={"category": "TRADE_LESSON", "content": "A lesson."})
    api_client.post("/api/ai/memory", json={"category": "USER_PREFERENCE", "content": "A preference."})

    resp = api_client.get("/api/ai/memory", params={"category": "TRADE_LESSON"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["category"] == "TRADE_LESSON"


def test_no_delete_route_exists(api_client):
    created = api_client.post("/api/ai/memory", json={"category": "TRADE_LESSON", "content": "x"}).json()
    resp = api_client.delete(f"/api/ai/memory/{created['id']}")
    assert resp.status_code == 405  # method not allowed — no DELETE route registered


# ---------------------------------------------------------------------------
# Chat integration: memory_used field
# ---------------------------------------------------------------------------

def test_chat_response_includes_memory_used_field(api_client, monkeypatch):
    import config
    monkeypatch.setattr(config, "AI_PROVIDER", "mock")
    resp = api_client.post("/api/ai/chat", json={"message": "hello"})
    assert resp.status_code == 200
    assert "memory_used" in resp.json()


def test_chat_response_memory_used_reflects_a_saved_memory(api_client, monkeypatch):
    import config
    monkeypatch.setattr(config, "AI_PROVIDER", "mock")
    api_client.post("/api/ai/memory", json={
        "category": "TRADE_LESSON",
        "content": "User repeatedly enters too early before the retracement completes.",
    })
    resp = api_client.post("/api/ai/chat", json={"message": "why do I enter too early?"})
    assert resp.status_code == 200
    assert len(resp.json()["memory_used"]) > 0
