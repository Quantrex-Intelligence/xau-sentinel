"""The V2-backed primary A+ path: default source, regression against the legacy path on
representative fixtures, explicit failure with no silent fallback, the FundedNext gate
unchanged, no LLM in the deterministic step, and monitoring left on the legacy path."""
from datetime import timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai.strategy import evaluator as legacy_eval
from ai.v2_strategy import primary
from ai.v2_strategy.primary import V2UnavailableError, evaluate_primary
from api.main import app
from mt5 import market_data
from risk.models import AccountType, FundedNextStatus, Phase, SafetyLevel
from tests.v2_fixtures import range_set, trend_set

FN_SAFE = FundedNextStatus(account_type=AccountType.STELLAR_2STEP, phase=Phase.CHALLENGE, mode="mock",
                           data_available=True, safety_level=SafetyLevel.SAFE, daily_loss_used_pct=10.0)
FN_UNSAFE = FundedNextStatus(account_type=AccountType.STELLAR_2STEP, phase=Phase.CHALLENGE, mode="mock",
                             data_available=True, safety_level=SafetyLevel.WARNING, daily_loss_used_pct=10.0)


def _now(candles):
    return candles["M5"]["close_time"].iloc[-1].to_pydatetime().replace(tzinfo=timezone.utc)


def _dump(e):
    return e.model_dump(exclude={"evaluated_at"})


# --- regression: primary equals legacy on representative fixtures ---------------------

@pytest.mark.parametrize("make", [lambda: trend_set("up"), lambda: trend_set("down"), range_set])
def test_primary_decision_equals_legacy_decision_on_representative_fixtures(make):
    candles = make()
    now = _now(candles)
    legacy = legacy_eval.evaluate_deterministic(candles, FN_SAFE, now=now)
    v2 = evaluate_primary(candles, FN_SAFE, now)
    assert _dump(v2) == _dump(legacy)


def test_primary_equals_legacy_when_the_fundednext_gate_blocks():
    candles = trend_set("up")
    now = _now(candles)
    assert _dump(evaluate_primary(candles, FN_UNSAFE, now)) == \
        _dump(legacy_eval.evaluate_deterministic(candles, FN_UNSAFE, now=now))
    assert evaluate_primary(candles, FN_UNSAFE, now).rating.value != "A+"


# --- explicit failure, no silent fallback -----------------------------------------------

def test_insufficient_v2_data_raises_and_never_uses_the_legacy_calculation(monkeypatch):
    def legacy_must_not_run(*a, **k):
        raise AssertionError("the legacy calculation must not run as a fallback")

    monkeypatch.setattr(legacy_eval, "evaluate_deterministic", legacy_must_not_run)
    short = trend_set("up")
    short["M5"] = short["M5"].iloc[:40]
    with pytest.raises(V2UnavailableError):
        evaluate_primary(short, FN_SAFE, _now(trend_set("up")))


def test_empty_candles_raise_rather_than_guess():
    from datetime import datetime
    with pytest.raises(V2UnavailableError):
        evaluate_primary({}, FN_SAFE, datetime(2026, 1, 5, tzinfo=timezone.utc))


def test_stale_data_is_reported_explicitly_as_not_a_plus():
    candles = trend_set("up")
    stale_now = _now(candles) + timedelta(days=3)
    ev = evaluate_primary(candles, FN_SAFE, stale_now)
    assert ev.rating.value != "A+"
    legacy = legacy_eval.evaluate_deterministic(candles, FN_SAFE, now=stale_now)
    assert _dump(ev) == _dump(legacy)  # the same explicit outcome the legacy path gives


# --- the route ------------------------------------------------------------------------------

def test_route_defaults_to_the_v2_primary_path(monkeypatch):
    called = {"primary": 0, "legacy": 0}

    from ai.strategy.schemas import FundedNextGateOut, StrategyEvaluationOut
    stub = StrategyEvaluationOut(
        rating=legacy_eval.Rating.DEVELOPING, evaluated_at="2026-01-05T00:00:00+00:00",
        fundednext=FundedNextGateOut(data_available=False, max_daily_loss_used_pct_allowed=50.0, reason="stub"),
    )

    def primary_stub():
        called["primary"] += 1
        return stub

    def legacy_stub():
        called["legacy"] += 1
        return stub

    from api.routes import strategy as route
    monkeypatch.setattr(route, "evaluate_current_setup_primary", primary_stub)
    monkeypatch.setattr(route, "evaluate_current_setup", legacy_stub)
    client = TestClient(app)
    assert client.get("/api/strategy/aplus").status_code == 200
    assert called == {"primary": 1, "legacy": 0}
    assert client.get("/api/strategy/aplus?source=legacy").status_code == 200
    assert called == {"primary": 1, "legacy": 1}


def test_route_returns_503_with_the_reason_when_v2_cannot_evaluate(monkeypatch):
    from api.routes import strategy as route

    def v2_down():
        raise V2UnavailableError("V2 status INSUFFICIENT_DATA: H1: insufficient closed history")

    monkeypatch.setattr(route, "evaluate_current_setup_primary", v2_down)
    resp = TestClient(app).get("/api/strategy/aplus")
    assert resp.status_code == 503
    assert "V2 analysis unavailable" in resp.json()["detail"]


def test_route_returns_503_when_mt5_is_unavailable(monkeypatch):
    from api.routes import strategy as route

    def mt5_down():
        raise market_data.MarketDataError("MT5 not connected")

    monkeypatch.setattr(route, "evaluate_current_setup_primary", mt5_down)
    assert TestClient(app).get("/api/strategy/aplus").status_code == 503


# --- no LLM in the deterministic step; monitoring stays on the legacy path ----------------

def test_the_deterministic_primary_step_never_calls_an_llm(monkeypatch):
    def llm_must_not_run(*a, **k):
        raise AssertionError("no LLM call in the deterministic primary path")

    monkeypatch.setattr(legacy_eval, "get_provider", llm_must_not_run)
    candles = trend_set("up")
    assert evaluate_primary(candles, FN_SAFE, _now(candles)).rating is not None


def test_monitoring_is_still_on_the_legacy_path():
    source = Path(__file__).resolve().parent.parent / "ai" / "monitoring" / "engine.py"
    text = source.read_text(encoding="utf-8")
    assert "from ai.strategy.evaluator import evaluate_deterministic" in text
    assert "v2_strategy" not in text and "analysis.v2" not in text
