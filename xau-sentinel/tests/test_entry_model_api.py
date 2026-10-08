"""GET /api/entry-model: schema, success, no-premature-direction, MT5 unavailable,
determinism, read-only -- the API-route-level counterpart to tests/test_analysis_v2_api.py.
analysis/entry_model/hierarchy.py and friends already have thorough pure-logic coverage
(tests/test_entry_model_hierarchy.py); this file only tests the HTTP layer around them."""
import json
import re

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from ai import assistant
from analysis.entry_model import common as CM
from analysis.entry_model import confirmation_5m as C5
from analysis.entry_model import setup_15m as S15
from api.main import app
from journal import trades as trades_repo
from mt5 import market_data
from tests.test_structure import BEARISH_POINTS, BULLISH_POINTS
from tests.v2_fixtures import DOWN_TAIL, UP_TAIL, path_candles, trend_set

FORBIDDEN_TEXT = re.compile(r"probab|\bBUY\b(?!-side)|\bSELL\b(?!-side)|win rate", re.IGNORECASE)

TOP_LEVEL_KEYS = {
    "symbol", "direction", "state", "as_of", "disclaimer", "higher_timeframe", "intraday",
    "setup_15m", "confirmation_5m", "precision_1m", "entry_candidate", "confidence",
    "supporting_evidence", "contradicting_evidence", "invalidation", "next_condition",
}


@pytest.fixture
def client():
    return TestClient(app)


def _frames(direction="up"):
    """Mirrors tests/test_entry_model_hierarchy.py::_frames -- all six timeframes the route
    actually requests (M1/M5/M15/H1/H4/D1), so the route is exercised exactly like production."""
    fr = trend_set(direction)
    points, tail = (BULLISH_POINTS, UP_TAIL) if direction == "up" else (BEARISH_POINTS, DOWN_TAIL)
    fr["D1"] = path_candles(points, 10, 1440, tail)
    fr["M1"] = fr["M5"]
    return fr


def _serve(monkeypatch, frames):
    monkeypatch.setattr(market_data, "get_candles", lambda tf, count=300: frames[tf])


def _force_confirmed_long(monkeypatch):
    """The same monkeypatch trick test_entry_model_hierarchy.py uses to reach a fully-confirmed,
    tradeable LONG candidate deterministically, rather than depending on the trend fixture's own
    (incidental) evidence density."""
    def fake_evidence(df, zones, atr_series, price, areas, timeframe):
        return {
            "bullish": [
                {"kind": "LIQUIDITY_SWEEP", "evidence": CM.ev(timeframe, pd.Timestamp.now(tz="UTC"), "SWEEP_LOW", float(price) - 5, "x")},
                {"kind": "MSS_BOS", "evidence": CM.ev(timeframe, pd.Timestamp.now(tz="UTC"), "MSS_BOS_BULLISH", price, "x")},
            ],
            "bearish": [],
        }
    monkeypatch.setattr(S15, "gather_directional_evidence", fake_evidence)
    monkeypatch.setattr(C5, "gather_directional_evidence", fake_evidence)


# --- schema -----------------------------------------------------------------------------------

def test_response_exposes_every_required_top_level_section(client, monkeypatch):
    _serve(monkeypatch, _frames("up"))
    r = client.get("/api/entry-model")
    assert r.status_code == 200
    assert TOP_LEVEL_KEYS <= set(r.json())


def test_response_names_the_symbol(client, monkeypatch):
    _serve(monkeypatch, _frames("up"))
    assert client.get("/api/entry-model").json()["symbol"]


# --- no premature direction exposure (the gating fix, verified at the HTTP layer) -------------

CONFIRMED_STATES = ("ENTRY_CONFIRMED", "PRECISION_AVAILABLE", "ENTRY_READY")


def test_direction_is_never_exposed_before_5m_confirmation_is_actually_confirmed(client, monkeypatch):
    _serve(monkeypatch, _frames("up"))
    j = client.get("/api/entry-model").json()
    # CONFLICTED is a safety sentinel, always exposed regardless of confirmation status (see
    # hierarchy.py's own exposed_direction comment) -- it is not a "premature direction claim". A
    # concrete LONG/SHORT claim, in contrast, must never appear before the state genuinely reached
    # a confirmed rung.
    if j["direction"] in ("LONG", "SHORT"):
        assert j["state"] in CONFIRMED_STATES
    elif j["direction"] is None:
        assert j["state"] not in CONFIRMED_STATES


def test_direction_is_exposed_once_5m_confirmation_is_forced_to_confirmed(client, monkeypatch):
    _serve(monkeypatch, _frames("up"))
    _force_confirmed_long(monkeypatch)
    j = client.get("/api/entry-model").json()
    assert j["confirmation_5m"]["confirmation_status"] == "CONFIRMED"
    assert j["direction"] == "LONG"
    assert j["state"] in ("ENTRY_CONFIRMED", "PRECISION_AVAILABLE", "ENTRY_READY")


# --- MT5 unavailable --------------------------------------------------------------------------

def test_mt5_unavailable_returns_a_clear_503_not_a_crash(client, monkeypatch):
    def down(tf, count=300):
        raise market_data.MarketDataError("MT5 not connected")

    monkeypatch.setattr(market_data, "get_candles", down)
    r = client.get("/api/entry-model")
    assert r.status_code == 503
    assert "MT5 not connected" in r.json()["detail"]


# --- missing/partial data ----------------------------------------------------------------------

def test_insufficient_history_reports_no_context_not_an_error(client, monkeypatch):
    frames = _frames("up")
    frames["D1"] = frames["D1"].iloc[:2]  # far below MIN_BARS
    _serve(monkeypatch, frames)
    j = client.get("/api/entry-model").json()
    assert j["state"] == "NO_CONTEXT"
    assert j["direction"] is None
    assert j["entry_candidate"] is None


# --- determinism -------------------------------------------------------------------------------

def test_identical_market_data_gives_byte_identical_json(client, monkeypatch):
    _serve(monkeypatch, _frames("up"))
    a = client.get("/api/entry-model").json()
    b = client.get("/api/entry-model").json()
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_response_is_valid_json_with_no_nan_or_infinity(client, monkeypatch):
    _serve(monkeypatch, _frames("up"))
    r = client.get("/api/entry-model")
    assert "NaN" not in r.text and "Infinity" not in r.text
    json.loads(r.text)  # strict parse


# --- forbidden content and side effects ---------------------------------------------------------

def test_response_text_contains_no_probability_or_trade_instruction(client, monkeypatch):
    _serve(monkeypatch, _frames("up"))
    _force_confirmed_long(monkeypatch)
    r = client.get("/api/entry-model")
    body = r.json()
    body.pop("disclaimer", None)
    # confidence.note is the same kind of self-disclaiming text as the top-level disclaimer (e.g.
    # "Not a probability and not calibrated against outcomes.") -- excluded for the same reason
    # test_analysis_v2_api.py excludes its own "disclaimer" key.
    if body.get("confidence"):
        body["confidence"].pop("note", None)
    assert not FORBIDDEN_TEXT.search(json.dumps(body))


def test_endpoint_is_read_only_get_only(client):
    operations = app.openapi()["paths"]["/api/entry-model"]
    assert set(operations) == {"get"}


def test_endpoint_writes_nothing_to_the_journal(client, monkeypatch):
    _serve(monkeypatch, _frames("up"))

    def forbidden(*args, **kwargs):
        raise AssertionError("entry-model endpoint must not write trading state")

    for name in ("create_trade", "close_trade", "save_trade", "update_trade", "delete_trade"):
        if hasattr(trades_repo, name):
            monkeypatch.setattr(trades_repo, name, forbidden)
    before = len(trades_repo.list_trades()) if hasattr(trades_repo, "list_trades") else None
    assert client.get("/api/entry-model").status_code == 200
    after = len(trades_repo.list_trades()) if hasattr(trades_repo, "list_trades") else None
    assert before == after


def test_endpoint_never_calls_the_llm(client, monkeypatch):
    _serve(monkeypatch, _frames("up"))

    def llm_called(*args, **kwargs):
        raise AssertionError("entry-model endpoint must not call an LLM")

    monkeypatch.setattr(assistant, "get_provider", llm_called)
    assert client.get("/api/entry-model").status_code == 200
