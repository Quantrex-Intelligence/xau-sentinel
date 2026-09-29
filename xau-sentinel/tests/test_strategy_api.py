"""API-level tests for /api/strategy/aplus. Same style as tests/test_api.py
and tests/test_ai_api.py: a TestClient bound to an isolated per-test DB,
proving the route is a thin pass-through over ai.strategy.evaluator plus
the one side effect it owns (non-duplicating A+ alerts).

Candle generation is fully mocked (via market_data.get_all_candles) rather
than relying on MODE=mock's real synthetic generator — the generator draws
a different-length RNG sequence per requested candle count, so its price at
`count=300` doesn't equal its price at other counts, which makes tests that
need a specific, known entry price flaky if left to real generation. Full
control here keeps these tests fast and exact, the same way
tests/test_strategy_evaluator.py controls analyze_structure/detect_sweeps/etc.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

import config
import ai.strategy.evaluator as evaluator_mod
from api.main import app
from journal import trades as trades_repo
from analysis.structure import StructureResult
from analysis.liquidity import LiquidityEvent
from analysis.sequence import SequenceResult
from mt5 import market_data
from tests.conftest import make_candles

ENTRY = 100.0


@pytest.fixture
def api_client(temp_db):
    with TestClient(app) as client:
        yield client


@pytest.fixture(autouse=True)
def _mock_candles(monkeypatch):
    """A small, fixed candle set whose last M5 close is exactly ENTRY —
    every test in this file can then reason about exact prices."""
    rows = [(ENTRY - 1 + i * 0.1, ENTRY - 0.7 + i * 0.1, ENTRY - 1.3 + i * 0.1, ENTRY - 0.9 + i * 0.1)
            for i in range(15)]
    # Anchored to the real clock (newest candle closed just now) so the feed
    # reads as live — the evaluator's Data Freshness gate (Stage 23A,
    # VAL-011) compares it against wall-clock `now` on this route.
    df = make_candles(rows, start=datetime.now(timezone.utc) - timedelta(minutes=5 * len(rows)))
    # Force the last candle's close to exactly ENTRY regardless of the loop above.
    df.loc[df.index[-1], "close"] = ENTRY
    candles = {"H4": df, "H1": df, "M15": df, "M5": df}
    monkeypatch.setattr(market_data, "get_all_candles", Mock(return_value=candles))


def _sr(state, last_mss=None, reason="reason"):
    return StructureResult(state=state, last_mss=last_mss, reason=reason)


def _sweep(kind, level_name, level_price, sweep_time):
    return LiquidityEvent(time=sweep_time, label=f"{level_name} swept", level_name=level_name,
                           level_price=level_price, kind=kind)


def _force_a_plus_buy(monkeypatch, minutes_ago=10, sweep_time=None):
    """Patches the module-level names evaluate_deterministic uses so a
    fresh call to /api/strategy/aplus deterministically returns a BUY A+.

    A real liquidity sweep is tied to one specific candle and does not
    shift on every re-poll, so callers that poll repeatedly for the SAME
    candidate must pass the SAME `sweep_time` each time (computing it once,
    outside the polling loop) rather than letting each call derive a fresh
    "now minus minutes_ago" that drifts by microseconds between polls."""
    sweep_time = sweep_time or (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago))
    monkeypatch.setattr(evaluator_mod, "analyze_structure", Mock(side_effect=[
        _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("PULLBACK", last_mss="bullish"),
    ]))
    monkeypatch.setattr(evaluator_mod, "compute_zones", Mock(return_value={
        "Previous Day Low": ENTRY - 5, "Previous Day High": ENTRY + 20,
    }))
    monkeypatch.setattr(evaluator_mod, "detect_sweeps", Mock(return_value=[
        _sweep("sweep_low", "Previous Day Low", ENTRY - 5, sweep_time),
    ]))
    monkeypatch.setattr(evaluator_mod, "detect_equal_levels", Mock(return_value=[]))
    monkeypatch.setattr(evaluator_mod, "evaluate_sequence", Mock(return_value=SequenceResult(
        sweep_index=3, mss_index=5, mss_level=ENTRY - 1, displacement_index=5, retracement_ok=True,
    )))
    monkeypatch.setattr(config, "AI_PROVIDER", "mock")


def test_aplus_endpoint_matches_direct_evaluator_call(api_client, monkeypatch):
    _force_a_plus_buy(monkeypatch)
    resp = api_client.get("/api/strategy/aplus")
    assert resp.status_code == 200
    body = resp.json()
    assert body["rating"] == "A+"
    assert body["direction"] == "BUY"
    assert body["missing_conditions"] == []
    assert body["fundednext"]["safety_level"] == "SAFE"
    assert body["entry"] == ENTRY
    assert body["stop_loss"] == round(ENTRY - 5 - 0.30, 2)


def test_aplus_endpoint_returns_503_on_market_data_error(api_client, monkeypatch):
    monkeypatch.setattr(market_data, "get_all_candles",
                         Mock(side_effect=market_data.MarketDataError("MT5 not connected")))
    resp = api_client.get("/api/strategy/aplus")
    assert resp.status_code == 503


def test_aplus_endpoint_logs_exactly_one_alert_for_an_a_plus_result(api_client, monkeypatch):
    _force_a_plus_buy(monkeypatch)
    resp = api_client.get("/api/strategy/aplus")
    assert resp.status_code == 200

    alerts = trades_repo.recent_alerts(limit=20)
    a_plus_alerts = alerts[alerts["level"] == "a_plus"]
    assert len(a_plus_alerts) == 1
    assert a_plus_alerts.iloc[0]["direction"] == "BUY"


def test_aplus_endpoint_never_duplicates_the_alert_on_repeated_polls(api_client, monkeypatch):
    """Do not spam repeated alerts for the same setup — repeated polling of
    the SAME candidate (same sweep -> same dedup key) must only ever alert
    once."""
    sweep_time = datetime.now(timezone.utc) - timedelta(minutes=10)
    for _ in range(5):
        _force_a_plus_buy(monkeypatch, sweep_time=sweep_time)  # re-arm the mocks, same candidate each time
        resp = api_client.get("/api/strategy/aplus")
        assert resp.status_code == 200

    alerts = trades_repo.recent_alerts(limit=20)
    a_plus_alerts = alerts[alerts["level"] == "a_plus"]
    assert len(a_plus_alerts) == 1


def test_aplus_endpoint_alerts_again_for_a_genuinely_new_candidate(api_client, monkeypatch):
    """A DIFFERENT sweep (new dedup key) is a new candidate and must alert
    again — dedup is per-candidate, not a global "already alerted once
    ever" latch."""
    _force_a_plus_buy(monkeypatch, minutes_ago=10)
    api_client.get("/api/strategy/aplus")

    _force_a_plus_buy(monkeypatch, minutes_ago=5)  # different sweep timestamp -> different dedup_key
    api_client.get("/api/strategy/aplus")

    alerts = trades_repo.recent_alerts(limit=20)
    a_plus_alerts = alerts[alerts["level"] == "a_plus"]
    assert len(a_plus_alerts) == 2


def test_aplus_endpoint_never_alerts_when_not_a_plus(api_client, monkeypatch):
    monkeypatch.setattr(evaluator_mod, "analyze_structure", Mock(side_effect=[
        _sr("RANGING"), _sr("RANGING"), _sr("RANGING"), _sr("RANGING"),
    ]))
    monkeypatch.setattr(evaluator_mod, "compute_zones", Mock(return_value={}))
    monkeypatch.setattr(evaluator_mod, "detect_sweeps", Mock(return_value=[]))
    monkeypatch.setattr(evaluator_mod, "detect_equal_levels", Mock(return_value=[]))
    monkeypatch.setattr(config, "AI_PROVIDER", "mock")

    resp = api_client.get("/api/strategy/aplus")
    assert resp.status_code == 200
    assert resp.json()["rating"] != "A+"

    alerts = trades_repo.recent_alerts(limit=20)
    assert len(alerts[alerts["level"] == "a_plus"]) == 0
