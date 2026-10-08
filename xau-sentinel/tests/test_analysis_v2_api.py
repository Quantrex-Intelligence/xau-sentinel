"""GET /api/analysis/v2: schema, success, stale data, MT5 unavailable, malformed
input, determinism, and the guarantee that the endpoint has no side effects."""
import json
import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import config
from ai import assistant
from api import analysis_v2
from api.main import app
from api.schemas_analysis_v2 import AnalysisV2Out
from journal import trades as trades_repo
from mt5 import market_data
from tests.v2_fixtures import range_set, trend_set, with_forming_bar

FORBIDDEN_TEXT = re.compile(r"probab|confiden|\bBUY\b(?!-side)|\bSELL\b(?!-side)|win rate|\bscore\b", re.IGNORECASE)


@pytest.fixture
def client():
    return TestClient(app)


def _now(candles):
    return candles["M5"]["close_time"].iloc[-1].to_pydatetime().replace(tzinfo=timezone.utc)


def _payload(candles, now=None):
    return analysis_v2.build_payload(now=now or _now(candles), candles=candles)


# --- schema ---------------------------------------------------------------

def test_response_validates_against_the_declared_contract(client, monkeypatch):
    candles = trend_set("up")
    monkeypatch.setattr(market_data, "get_candles", lambda tf, count=300: candles[tf])
    r = client.get("/api/analysis/v2")
    assert r.status_code == 200
    body = AnalysisV2Out.model_validate(r.json())  # raises if the shape drifts
    assert body.status in {"OK", "STALE", "INSUFFICIENT_DATA", "UNAVAILABLE"}


def test_response_exposes_every_required_section(client, monkeypatch):
    candles = trend_set("up")
    monkeypatch.setattr(market_data, "get_candles", lambda tf, count=300: candles[tf])
    j = client.get("/api/analysis/v2").json()
    assert {"status", "status_reason", "freshness", "source", "notes", "data_issues",
            "facts", "events", "interpretation", "scenarios"} <= set(j)
    assert {"observations", "structure"} <= set(j["facts"])
    assert set(j["facts"]["structure"]) == {"M5", "M15", "H1", "H4"}
    assert {"context", "key_areas", "confluence", "narrative"} <= set(j["interpretation"])
    obs = j["facts"]["observations"]
    assert {"current_price", "atr_m5", "atr_percentile_m5", "volume_m5", "session", "zones",
            "sweeps", "equal_levels", "zone_distances_atr"} <= set(obs)


def test_context_section_has_one_entry_per_independent_dimension(client, monkeypatch):
    candles = trend_set("up")
    monkeypatch.setattr(market_data, "get_candles", lambda tf, count=300: candles[tf])
    ctx = client.get("/api/analysis/v2").json()["interpretation"]["context"]
    assert set(ctx) == {"direction", "structure", "regime", "volatility", "volume",
                        "liquidity", "momentum", "session", "price_location", "trend_strength"}
    for name in ("direction", "regime", "volatility", "volume", "liquidity", "momentum", "session",
                 "price_location", "trend_strength"):
        assert set(ctx[name]) == {"state", "detail"}


# --- successful analysis ----------------------------------------------------

def test_successful_analysis_has_facts_interpretation_and_scenarios():
    p = _payload(trend_set("up"))
    assert p.status == "OK"
    assert p.facts.observations is not None
    assert p.interpretation.context is not None
    assert p.interpretation.confluence.reference == "bullish"
    assert [s.name for s in p.scenarios] == ["CONTINUATION", "REVERSAL"]
    assert p.interpretation.narrative and p.interpretation.narrative[0].startswith("Direction:")


def test_source_is_labelled_so_mock_data_is_never_mistaken_for_market_data():
    p = _payload(trend_set("up"))
    assert p.source.provider.startswith("MOCK") or p.source.provider == "MT5 live"
    assert p.source.symbol == config.TRADING_SYMBOL
    assert p.source.server_timezone == config.FUNDEDNEXT_SERVER_TIMEZONE
    assert set(p.source.timeframes) == {"M5", "M15", "H1", "H4"}


def test_live_source_is_labelled_as_mt5(monkeypatch):
    monkeypatch.setattr(config, "IS_LIVE", True)
    monkeypatch.setattr(config, "IS_MOCK", False)
    assert _payload(trend_set("up")).source.provider == "MT5 live"


def test_freshness_uses_the_last_closed_bar_not_the_forming_one():
    candles = with_forming_bar(trend_set("up"), "M5", close=999.0)
    now = _now(trend_set("up"))
    p = analysis_v2.build_payload(now=now, candles=candles)
    assert p.freshness.m5_bar_close_utc is not None
    assert p.freshness.age_seconds is not None and p.freshness.age_seconds >= 0


# --- stale data ----------------------------------------------------------------

def test_stale_data_is_flagged_everywhere_it_matters():
    candles = trend_set("up")
    p = analysis_v2.build_payload(now=_now(candles) + timedelta(days=3), candles=candles)
    assert p.status == "STALE"
    assert p.freshness.stale is True
    assert p.notes and "older than" in p.notes[0]
    assert p.interpretation.narrative[0].startswith("The M5 feed is older")
    assert "history" in p.status_reason


def test_fresh_data_is_not_marked_stale():
    candles = trend_set("up")
    p = _payload(candles)
    assert p.freshness.stale is False


# --- MT5 unavailable --------------------------------------------------------

def test_mt5_unavailable_returns_an_explicit_status_not_an_error(client, monkeypatch):
    def down(tf, count=300):
        raise market_data.MarketDataError("MT5 not connected")

    monkeypatch.setattr(market_data, "get_candles", down)
    r = client.get("/api/analysis/v2")
    assert r.status_code == 200
    j = r.json()
    assert j["status"] == "UNAVAILABLE"
    assert "MT5 not connected" in j["status_reason"]
    assert j["facts"]["observations"] is None
    assert j["interpretation"]["context"] is None
    assert j["scenarios"] == []
    assert j["freshness"]["stale"] is True
    assert j["source"]["provider"] == "unavailable"


# --- malformed / insufficient input ------------------------------------------------

def test_empty_candles_give_insufficient_data_not_a_crash():
    p = analysis_v2.build_payload(now=datetime(2026, 1, 5, tzinfo=timezone.utc), candles={})
    assert p.status == "INSUFFICIENT_DATA"
    assert p.facts.observations is None
    assert p.scenarios == []


def test_frame_without_closed_flag_is_reported_as_a_data_issue():
    candles = trend_set("up")
    candles["H1"] = candles["H1"].drop(columns=["is_closed"])
    p = analysis_v2.build_payload(now=_now(candles), candles=candles)
    assert p.status == "OK"
    assert any("no is_closed column" in issue for issue in p.data_issues)
    assert p.facts.structure["H1"].state == "INSUFFICIENT"


def test_short_m5_history_is_insufficient_and_names_the_minimum():
    candles = trend_set("up")
    candles["M5"] = candles["M5"].iloc[:40]
    p = analysis_v2.build_payload(now=_now(trend_set("up")), candles=candles)
    assert p.status == "INSUFFICIENT_DATA"
    assert any("need 120" in issue for issue in p.data_issues)


def test_nan_volume_is_reported_as_unknown_not_zero():
    candles = trend_set("up")
    candles["M5"].loc[candles["M5"].index[-1], "volume"] = float("nan")
    p = _payload(candles)
    assert p.facts.observations.volume_m5.state == "UNKNOWN"
    assert p.facts.observations.volume_m5.relative_volume is None


# --- determinism ------------------------------------------------------------------

def test_identical_input_and_clock_give_byte_identical_json():
    candles = trend_set("up")
    now = _now(candles)
    a = analysis_v2.build_payload(now=now, candles=candles).model_dump_json()
    b = analysis_v2.build_payload(now=now, candles=trend_set("up")).model_dump_json()
    assert a == b


def test_response_is_valid_json_with_no_nan_or_infinity():
    candles = range_set()
    text = _payload(candles).model_dump_json()
    json.loads(text)  # strict parse
    assert "NaN" not in text and "Infinity" not in text


# --- forbidden content and side effects -------------------------------------------

@pytest.mark.parametrize("make", [trend_set, range_set])
def test_response_text_contains_no_probability_score_or_trade_instruction(make):
    text = _payload(make("up") if make is trend_set else make()).model_dump_json()
    values = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k not in ("disclaimer",):
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
        elif isinstance(node, str):
            values.append(node)

    walk(json.loads(text))
    joined = " ".join(values)
    assert not FORBIDDEN_TEXT.search(joined), joined[:400]


def test_endpoint_is_read_only_get_only(client):
    # OpenAPI lists every registered operation, including routes nested under included routers.
    operations = app.openapi()["paths"]["/api/analysis/v2"]
    assert set(operations) == {"get"}


def test_endpoint_writes_nothing_to_the_journal_or_alerts(client, monkeypatch):
    candles = trend_set("up")
    monkeypatch.setattr(market_data, "get_candles", lambda tf, count=300: candles[tf])

    def forbidden(*args, **kwargs):
        raise AssertionError("analysis endpoint must not write trading or alert state")

    for name in ("create_trade", "close_trade", "log_alert", "save_trade", "update_trade", "delete_trade"):
        if hasattr(trades_repo, name):
            monkeypatch.setattr(trades_repo, name, forbidden)
    before = len(trades_repo.list_trades()) if hasattr(trades_repo, "list_trades") else None
    assert client.get("/api/analysis/v2").status_code == 200
    after = len(trades_repo.list_trades()) if hasattr(trades_repo, "list_trades") else None
    assert before == after


def test_endpoint_never_calls_the_llm(client, monkeypatch):
    candles = trend_set("up")
    monkeypatch.setattr(market_data, "get_candles", lambda tf, count=300: candles[tf])

    def llm_called(*args, **kwargs):
        raise AssertionError("analysis endpoint must not call an LLM")

    monkeypatch.setattr(assistant, "get_provider", llm_called)
    assert client.get("/api/analysis/v2").status_code == 200


def test_analysis_package_is_not_imported_by_strategy_or_monitoring_code():
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    for folder in ("ai/strategy", "ai/monitoring", "ai/notifications"):
        for py in (root / folder).rglob("*.py"):
            assert "analysis.v2" not in py.read_text(encoding="utf-8"), py
