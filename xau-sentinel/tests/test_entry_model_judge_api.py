"""GET /api/entry-model/judge: disabled flag, not-eligible states, eligible end-to-end with a
stubbed provider, read-only, never mutates /api/entry-model's own response, never leaks a key."""
import json

import pytest
from fastapi.testclient import TestClient

import config
from ai.entry_judge import evaluator as ev
from ai.providers.base import BaseProvider, ProviderResponse
from api.main import app
from mt5 import market_data
from tests.test_structure import BEARISH_POINTS, BULLISH_POINTS
from tests.v2_fixtures import DOWN_TAIL, UP_TAIL, path_candles, trend_set

VALID_VERDICT_JSON = json.dumps({
    "verdict": "SUPPORTED", "quality": "HIGH", "supporting_evidence": ["x"], "contradictions": [],
    "missing_confirmations": [], "risk_flags": [], "reasoning_summary": "Evidence is consistent.",
    "invalidation_conditions": [], "evidence_references": ["M15"],
})


class _StubProvider(BaseProvider):
    name, model = "stub", "stub-model"
    def chat(self, system, messages, tools=None):
        return ProviderResponse(text=VALID_VERDICT_JSON, provider="stub", model="stub-model")


@pytest.fixture
def client():
    return TestClient(app)


def _frames(direction="up"):
    fr = trend_set(direction)
    points, tail = (BULLISH_POINTS, UP_TAIL) if direction == "up" else (BEARISH_POINTS, DOWN_TAIL)
    fr["D1"] = path_candles(points, 10, 1440, tail)
    fr["M1"] = fr["M5"]
    return fr


def _serve(monkeypatch, frames):
    monkeypatch.setattr(market_data, "get_candles", lambda tf, count=300: frames[tf])


def _force_confirmed_long(monkeypatch):
    import analysis.entry_model.common as CM
    import analysis.entry_model.setup_15m as S15
    import analysis.entry_model.confirmation_5m as C5
    import pandas as pd

    # A fixed timestamp, not wall-clock now: repeated evaluate() calls against byte-identical
    # candle data must produce a byte-identical snapshot, exactly like the real engine would on
    # unchanged input -- a non-deterministic mock here would wrongly make the dedup-skip test look
    # like a real evaluator bug.
    fixed_now = pd.Timestamp("2026-10-08T12:00:00", tz="UTC")

    def fake_evidence(df, zones, atr_series, price, areas, timeframe):
        return {
            "bullish": [
                {"kind": "LIQUIDITY_SWEEP", "evidence": CM.ev(timeframe, fixed_now, "SWEEP_LOW", float(price) - 5, "x")},
                {"kind": "MSS_BOS", "evidence": CM.ev(timeframe, fixed_now, "MSS_BOS_BULLISH", price, "x")},
            ],
            "bearish": [],
        }
    monkeypatch.setattr(S15, "gather_directional_evidence", fake_evidence)
    monkeypatch.setattr(C5, "gather_directional_evidence", fake_evidence)


# --- disabled ------------------------------------------------------------------------------------

def test_disabled_returns_a_clear_shape_without_calling_a_provider(client, monkeypatch):
    monkeypatch.setattr(config, "ENTRY_JUDGE_ENABLED", False)

    def boom():
        raise AssertionError("judge must not call a provider when disabled")
    monkeypatch.setattr(ev, "get_provider", boom)

    r = client.get("/api/entry-model/judge")
    assert r.status_code == 200
    j = r.json()
    assert j["enabled"] is False
    assert j["eligible"] is False


# --- not eligible ---------------------------------------------------------------------------------

def test_not_eligible_state_reports_a_clear_reason_not_an_error(client, monkeypatch):
    _serve(monkeypatch, _frames("up"))
    r = client.get("/api/entry-model/judge")
    assert r.status_code == 200
    j = r.json()
    assert j["enabled"] is True
    if j["eligible"] is False:
        assert j["not_eligible_reason"]
        assert j["verdict"] is None


# --- eligible, full round trip ----------------------------------------------------------------------

def test_eligible_candidate_returns_a_verdict_end_to_end(client, monkeypatch):
    _serve(monkeypatch, _frames("up"))
    _force_confirmed_long(monkeypatch)
    monkeypatch.setattr(ev, "get_provider", lambda: _StubProvider())

    r = client.get("/api/entry-model/judge")
    assert r.status_code == 200
    j = r.json()
    assert j["enabled"] is True
    assert j["eligible"] is True
    assert j["status"] == "OK"
    assert j["verdict"] == "SUPPORTED"
    assert j["quality"] == "HIGH"
    assert "SHADOW MODE" in j["disclaimer"].upper()


def test_a_second_poll_of_the_unchanged_candidate_does_not_call_the_provider_again(client, monkeypatch):
    _serve(monkeypatch, _frames("up"))
    _force_confirmed_long(monkeypatch)
    calls = {"n": 0}

    class _CountingStub(_StubProvider):
        def chat(self, system, messages, tools=None):
            calls["n"] += 1
            return super().chat(system, messages, tools)

    monkeypatch.setattr(ev, "get_provider", lambda: _CountingStub())
    client.get("/api/entry-model/judge")
    client.get("/api/entry-model/judge")
    assert calls["n"] == 1


# --- read-only / isolation -----------------------------------------------------------------------

def test_endpoint_is_read_only_get_only(client):
    operations = app.openapi()["paths"]["/api/entry-model/judge"]
    assert set(operations) == {"get"}


def test_calling_the_judge_never_changes_what_api_entry_model_itself_returns(client, monkeypatch):
    _serve(monkeypatch, _frames("up"))
    _force_confirmed_long(monkeypatch)
    monkeypatch.setattr(ev, "get_provider", lambda: _StubProvider())

    before = client.get("/api/entry-model").json()
    client.get("/api/entry-model/judge")
    after = client.get("/api/entry-model").json()
    assert before["direction"] == after["direction"]
    assert before["state"] == after["state"]
    assert before["entry_candidate"] == after["entry_candidate"]


def test_response_never_leaks_an_api_key(client, monkeypatch):
    monkeypatch.setattr(config, "AI_API_KEY", "sk-super-secret-key-value")
    _serve(monkeypatch, _frames("up"))
    r = client.get("/api/entry-model/judge")
    assert "sk-super-secret-key-value" not in r.text


def test_mt5_unavailable_reports_not_eligible_not_a_crash(client, monkeypatch):
    def down(tf, count=300):
        raise market_data.MarketDataError("MT5 not connected")
    monkeypatch.setattr(market_data, "get_candles", down)
    r = client.get("/api/entry-model/judge")
    assert r.status_code == 200
    assert r.json()["eligible"] is False
