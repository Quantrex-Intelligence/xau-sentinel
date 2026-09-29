"""Tests for ai/explanations/context.py — per-alert-type relevance gating
matches the Stage 15 plan's table exactly (e.g. RISK_STATUS_CHANGED never
calls the similarity engine, HIGH_IMPACT_EVENT_NEAR never calls risk),
deterministic facts read only real payload/trade fields (never fabricate
one), and a trade explanation never includes Market Intelligence."""
from unittest.mock import Mock

import pytest

from ai.explanations import context as ctx
from ai.monitoring.models import AlertEvent, AlertType, Severity

_TS = "2026-01-01T00:00:00+00:00"


def _alert(alert_type, payload=None, **overrides):
    defaults = dict(
        type=alert_type, severity=Severity.INFO, title="Title", message="Message",
        dedup_key="k", payload=payload or {}, symbol="XAUUSD", timestamp=_TS,
    )
    defaults.update(overrides)
    return AlertEvent(**defaults)


@pytest.fixture(autouse=True)
def _stub_evidence_sources(monkeypatch):
    """Stubs every underlying evidence source so tests assert purely on
    WHETHER each was called, not on live data."""
    calls = {"risk": 0, "mi": 0, "similarity": 0, "rag": 0, "memory": 0}

    def fake_settings():
        calls["risk"] += 1
        return {"account_type": "stellar_2step", "phase": "challenge", "consistency_enabled": False}

    def fake_compute_status(*a, **k):
        status = Mock()
        status.data_available = True
        status.safety_level = Mock(value="SAFE")
        status.daily_loss_used_pct = 10.0
        status.max_drawdown_used_pct = 5.0
        status.reason = "ok"
        return status

    def fake_build_mi_context():
        calls["mi"] += 1
        ctx_obj = Mock()
        ctx_obj.data_available = True
        return ctx_obj

    def fake_resolve_query_features(trade_id=None):
        calls["similarity"] += 1
        return None, None  # no features -> find_similar_setups never actually called

    def fake_retrieve(query):
        calls["rag"] += 1
        return []

    def fake_retrieve_memory(query):
        calls["memory"] += 1
        return []

    monkeypatch.setattr(ctx.settings_store, "get_settings", fake_settings)
    monkeypatch.setattr(ctx, "compute_status", fake_compute_status)
    monkeypatch.setattr(ctx.mi_context, "build_market_intelligence_context", fake_build_mi_context)
    monkeypatch.setattr(ctx.similarity_engine, "resolve_query_features", fake_resolve_query_features)
    monkeypatch.setattr(ctx.knowledge_retrieval, "retrieve", fake_retrieve)
    monkeypatch.setattr(ctx.memory_retrieval, "retrieve_memory", fake_retrieve_memory)
    return calls


# ---------------------------------------------------------------------------
# Per-alert-type relevance gating
# ---------------------------------------------------------------------------

def test_aplus_detected_gathers_every_source(_stub_evidence_sources):
    alert = _alert(AlertType.APLUS_SETUP_DETECTED, payload={"direction": "BUY"})
    ctx.gather_evidence_for_alert(alert)
    assert _stub_evidence_sources == {"risk": 1, "mi": 1, "similarity": 1, "rag": 1, "memory": 1}


def test_risk_status_changed_never_gathers_similarity_or_mi(_stub_evidence_sources):
    alert = _alert(AlertType.RISK_STATUS_CHANGED, payload={"previous_status": "SAFE", "current_status": "WARNING"})
    ctx.gather_evidence_for_alert(alert)
    assert _stub_evidence_sources["similarity"] == 0
    assert _stub_evidence_sources["mi"] == 0
    assert _stub_evidence_sources["risk"] == 1
    assert _stub_evidence_sources["rag"] == 1


def test_high_impact_event_near_never_gathers_risk_or_similarity(_stub_evidence_sources):
    alert = _alert(AlertType.HIGH_IMPACT_EVENT_NEAR, payload={"event": "US CPI"})
    ctx.gather_evidence_for_alert(alert)
    assert _stub_evidence_sources["risk"] == 0
    assert _stub_evidence_sources["similarity"] == 0
    assert _stub_evidence_sources["mi"] == 1
    assert _stub_evidence_sources["rag"] == 1
    assert _stub_evidence_sources["memory"] == 0


def test_mi_quality_changed_gathers_only_mi(_stub_evidence_sources):
    alert = _alert(AlertType.MARKET_INTELLIGENCE_QUALITY_CHANGED,
                    payload={"previous_quality": "AVAILABLE", "current_quality": "UNAVAILABLE"})
    ctx.gather_evidence_for_alert(alert)
    assert _stub_evidence_sources == {"risk": 0, "mi": 1, "similarity": 0, "rag": 0, "memory": 0}


def test_setup_state_changed_gathers_every_source(_stub_evidence_sources):
    alert = _alert(AlertType.SETUP_STATE_CHANGED, payload={"previous_state": "NO SETUP", "current_state": "DEVELOPING"})
    ctx.gather_evidence_for_alert(alert)
    assert _stub_evidence_sources == {"risk": 1, "mi": 1, "similarity": 1, "rag": 1, "memory": 1}


# ---------------------------------------------------------------------------
# Deterministic facts — real fields only, never fabricated
# ---------------------------------------------------------------------------

def test_deterministic_facts_for_alert_reads_real_payload_fields():
    alert = _alert(AlertType.APLUS_SETUP_DETECTED, payload={
        "direction": "BUY", "entry": 3700.0, "stop_loss": 3690.0, "target": 3730.0, "rr": 3.0, "rating": "A+",
    })
    facts = ctx.deterministic_facts_for_alert(alert)
    joined = " | ".join(facts)
    assert "BUY" in joined
    assert "3700.0" in joined
    assert "A+" in joined


def test_deterministic_facts_for_alert_falls_back_to_message_when_payload_empty():
    alert = _alert(AlertType.APLUS_SETUP_DETECTED, payload={}, message="Something happened.")
    facts = ctx.deterministic_facts_for_alert(alert)
    assert facts == ["Something happened."]


def test_deterministic_facts_for_alert_never_invents_missing_fields():
    alert = _alert(AlertType.APLUS_SETUP_DETECTED, payload={"direction": "BUY"})
    facts = ctx.deterministic_facts_for_alert(alert)
    assert facts == ["Direction: BUY"]  # entry/stop_loss/target/rr/rating all absent -> no line for any of them
    assert all("None" not in f for f in facts)


def test_deterministic_facts_for_trade_reads_real_fields_only():
    trade = {
        "direction": "SELL", "entry": 3750.0, "stop_loss": 3760.0, "take_profit": 3700.0,
        "planned_rr": 5.0, "result": "WIN", "pnl": 500.0, "r_multiple": 5.0,
        "h1_bias": "BEARISH", "regime": "TRENDING", "liquidity": None, "mss": None, "displacement": None,
    }
    facts = ctx.deterministic_facts_for_trade(trade)
    joined = " | ".join(facts)
    assert "SELL" in joined
    assert "WIN" in joined
    assert "BEARISH" in joined
    assert all("None" not in f for f in facts)  # None fields excluded entirely, never printed as "None"


# ---------------------------------------------------------------------------
# Trade explanation never includes Market Intelligence
# ---------------------------------------------------------------------------

def test_trade_evidence_never_gathers_market_intelligence(_stub_evidence_sources):
    trade = {"direction": "BUY", "setup": "liquidity sweep", "result": "WIN"}
    ctx.gather_evidence_for_trade(5, trade)
    assert _stub_evidence_sources["mi"] == 0


def test_trade_evidence_gathers_similarity_with_the_trade_excluded(monkeypatch):
    captured = {}

    def fake_resolve(trade_id=None):
        captured["trade_id"] = trade_id
        return None, trade_id

    monkeypatch.setattr(ctx.similarity_engine, "resolve_query_features", fake_resolve)
    monkeypatch.setattr(ctx.knowledge_retrieval, "retrieve", lambda q: [])
    monkeypatch.setattr(ctx.memory_retrieval, "retrieve_memory", lambda q: [])

    ctx.gather_evidence_for_trade(42, {"direction": "BUY"})
    assert captured["trade_id"] == 42


# ---------------------------------------------------------------------------
# Renderers degrade gracefully, never fabricate
# ---------------------------------------------------------------------------

def test_render_risk_context_returns_empty_when_status_is_none():
    assert ctx.render_risk_context(None) == []


def test_render_risk_context_reports_unavailable_without_fabricating():
    status = Mock(data_available=False, reason="MT5 not connected")
    lines = ctx.render_risk_context(status)
    assert len(lines) == 1
    assert "unavailable" in lines[0].lower()
    assert "MT5 not connected" in lines[0]


def test_render_uncertainties_flags_every_ungathered_relevant_source():
    from ai.strategy.evidence import ContextualEvidence
    subject = ctx.SubjectEvidence(evidence=ContextualEvidence(), fundednext_status=None)
    rules = dict(risk=True, mi=True, similarity=True, rag=True, memory=True)
    items = ctx.render_uncertainties(subject, rules)
    assert len(items) == 5  # every gathered-but-empty source flagged


def test_build_sources_only_lists_genuinely_available_sources():
    from ai.strategy.evidence import ContextualEvidence
    subject = ctx.SubjectEvidence(evidence=ContextualEvidence(), fundednext_status=None)
    assert ctx.build_sources(subject) == []
