"""API-level tests for /api/ai/*. Same style as tests/test_api.py: a
TestClient bound to an isolated per-test DB, proving the route is a thin,
faithful pass-through over ai/assistant.py — plus the HTTP-status mapping
for each failure mode and a hard check that a configured secret never
appears anywhere in a response body."""
import pytest
from fastapi.testclient import TestClient

import config
from ai import assistant
from ai.providers.base import BaseProvider, ProviderConfigError, ProviderRequestError, ProviderResponse
from api.main import app


@pytest.fixture
def api_client(temp_db):
    with TestClient(app) as client:
        yield client


@pytest.fixture(autouse=True)
def _mock_ai_provider(monkeypatch):
    """API tests default to the offline mock provider so they never depend
    on network access or a real key — individual tests override this where
    they specifically want to exercise a failure path."""
    monkeypatch.setattr(config, "AI_PROVIDER", "mock")


def test_config_endpoint_reports_configured_for_mock_provider(api_client):
    resp = api_client.get("/api/ai/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is True
    assert body["provider"] == "mock"


def test_config_endpoint_reports_not_configured_without_a_key(api_client, monkeypatch):
    monkeypatch.setattr(config, "AI_PROVIDER", "anthropic")
    monkeypatch.setattr(config, "AI_API_KEY", "")

    resp = api_client.get("/api/ai/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["configured"] is False
    assert body["model"] is None
    assert "AI_API_KEY" in body["reason"]


def test_chat_endpoint_returns_answer_in_mock_mode(api_client):
    resp = api_client.post("/api/ai/chat", json={"message": "What is the current market structure?"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["answer"]
    assert body["conversation_id"]
    assert set(body["context_used"]) == {"Market Structure", "Setup", "FundedNext Risk"}
    assert body["provider"] == "mock"
    assert all(s["label"] in body["context_used"] or not s["available"] for s in body["sources"])


def test_chat_endpoint_rejects_empty_message(api_client):
    resp = api_client.post("/api/ai/chat", json={"message": "   "})
    assert resp.status_code == 400


def test_chat_endpoint_returns_503_when_unconfigured(api_client, monkeypatch):
    monkeypatch.setattr(config, "AI_PROVIDER", "anthropic")
    monkeypatch.setattr(config, "AI_API_KEY", "")

    resp = api_client.post("/api/ai/chat", json={"message": "hello"})
    assert resp.status_code == 503
    assert "not configured" in resp.json()["detail"].lower()


def test_chat_endpoint_returns_502_on_provider_request_failure(api_client, monkeypatch):
    class _FailingProvider(BaseProvider):
        name = "fake"
        model = "fake-model"

        def chat(self, system, messages, tools=None):
            raise ProviderRequestError("upstream timed out")

    monkeypatch.setattr(assistant, "get_provider", lambda: _FailingProvider())

    resp = api_client.post("/api/ai/chat", json={"message": "hello"})
    assert resp.status_code == 502
    assert "upstream timed out" in resp.json()["detail"]


def test_chat_endpoint_maintains_conversation_across_requests(api_client):
    first = api_client.post("/api/ai/chat", json={"message": "First question"}).json()
    second = api_client.post(
        "/api/ai/chat",
        json={"message": "Second question", "conversation_id": first["conversation_id"]},
    ).json()

    assert second["conversation_id"] == first["conversation_id"]
    # The mock provider echoes the last user message it was given — proves
    # history round-tripped through the DB and back into the next request.
    assert "Second question" in second["answer"]


def test_chat_endpoint_journal_context_included_only_when_requested(api_client):
    api_client.post("/api/journal/trades", json={
        "trade_date": "2026-01-05", "trade_time": "09:00:00", "direction": "BUY",
        "entry": 100.0, "stop_loss": 95.0, "take_profit": 110.0, "planned_rr": 2.0, "setup": "Sweep+MSS",
    })

    default_resp = api_client.post("/api/ai/chat", json={"message": "Summarize"}).json()
    assert "Journal" not in default_resp["context_used"]

    with_journal = api_client.post(
        "/api/ai/chat", json={"message": "Summarize my trades", "context_scope": ["journal"]}
    ).json()
    assert with_journal["context_used"] == ["Journal"]
    assert any(s["label"] == "Journal" and s["available"] for s in with_journal["sources"])


def test_chat_endpoint_explains_a_trade_using_only_captured_entry_context(api_client):
    created = api_client.post("/api/journal/trades", json={
        "trade_date": "2026-01-05", "trade_time": "09:00:00", "direction": "BUY",
        "entry": 100.0, "stop_loss": 95.0, "take_profit": 110.0, "planned_rr": 2.0, "setup": "Sweep+MSS",
    }).json()

    resp = api_client.post("/api/ai/chat", json={
        "message": "Explain this trade.", "trade_id": created["id"],
        "context_scope": ["market", "risk", "journal"],  # must be ignored when trade_id is set
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["context_used"] == ["Trade Context (captured at entry)"]


def test_api_key_never_appears_in_any_ai_response_body(api_client, monkeypatch):
    secret = "sk-super-secret-should-never-leak-anywhere"
    monkeypatch.setattr(config, "AI_API_KEY", secret)

    config_resp = api_client.get("/api/ai/config")
    chat_resp = api_client.post("/api/ai/chat", json={"message": "hello"})

    assert secret not in config_resp.text
    assert secret not in chat_resp.text


# ---------------------------------------------------------------------------
# Stage 5: knowledge/RAG integration
# ---------------------------------------------------------------------------

def test_knowledge_documents_endpoint_lists_the_seeded_corpus(api_client):
    """api_client's TestClient triggers the real app lifespan, which seeds
    the knowledge base the same way the running app does — proving the
    seed step is actually wired into startup, not just unit-tested."""
    resp = api_client.get("/api/ai/knowledge/documents")
    assert resp.status_code == 200
    docs = resp.json()
    assert len(docs) > 0
    categories = {d["category"] for d in docs}
    assert "strategy_rules" in categories
    assert "fundednext_rules" in categories


def test_chat_response_includes_knowledge_used_field(api_client):
    resp = api_client.post("/api/ai/chat", json={
        "message": "what reward to risk ratio does the A+ strategy require?",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert "knowledge_used" in body
    assert len(body["knowledge_used"]) > 0
    assert body["knowledge_used"][0]["source"]
    assert body["knowledge_used"][0]["category"]


def test_chat_response_knowledge_used_is_empty_for_an_off_topic_message(api_client):
    resp = api_client.post("/api/ai/chat", json={"message": "what is the capital of France?"})
    assert resp.status_code == 200
    assert resp.json()["knowledge_used"] == []


# ---------------------------------------------------------------------------
# Stage 6: AI tool calling
# ---------------------------------------------------------------------------

def test_tools_endpoint_lists_the_registered_tools(api_client):
    resp = api_client.get("/api/ai/tools")
    assert resp.status_code == 200
    tools = resp.json()
    assert len(tools) >= 11
    names = {t["name"] for t in tools}
    assert "get_market_state" in names
    assert "get_risk_status" in names
    assert "search_journal" in names
    for t in tools:
        assert t["label"]
        assert t["description"]


def test_chat_response_includes_tools_used_field(api_client):
    resp = api_client.post("/api/ai/chat", json={"message": "What is the current market structure?"})
    assert resp.status_code == 200
    assert "tools_used" in resp.json()


def test_chat_response_tools_used_is_empty_when_mock_provider_offers_no_matching_tool(api_client):
    resp = api_client.post("/api/ai/chat", json={"message": "hello there"})
    assert resp.status_code == 200
    assert resp.json()["tools_used"] == []


def test_chat_response_tools_used_populated_for_a_setup_question_in_mock_mode(api_client):
    resp = api_client.post("/api/ai/chat", json={"message": "Why is this setup only developing?"})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["tools_used"]) == 1
    assert body["tools_used"][0]["name"] == "get_current_setup"


def test_add_user_note_endpoint_persists_and_is_listed(api_client):
    resp = api_client.post("/api/ai/knowledge/notes", json={
        "title": "My personal playbook note",
        "content": "I always wait for London session liquidity before entering.",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["category"] == "user_notes"
    assert body["is_active"] is True

    docs = api_client.get("/api/ai/knowledge/documents").json()
    assert any(d["title"] == "My personal playbook note" for d in docs)
