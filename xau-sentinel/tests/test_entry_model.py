"""Deterministic tests for the Intraday ICT Entry Model V1 (manual decision support)."""
import pathlib
import unittest.mock as mock

import pandas as pd
import pytest

import config
from analysis.entry_model import confidence as C
from analysis.entry_model import dataset as D
from analysis.entry_model import model as M
from analysis.entry_model.ote import compute_ote
from analysis.liquidity import LiquidityEvent
from analysis.v2.sequence import CONFIRMED, MarketSequence, SequenceStep
from tests.conftest import make_candles
from tests.test_sequence import DECLINE, FOLLOW, QUIET, RETRACE, SWING_HIGH
from tests.test_structure import BEARISH_POINTS, BULLISH_POINTS
from tests.v2_fixtures import DOWN_TAIL, UP_TAIL, path_candles, range_set, trend_set, with_forming_bar

NOW = pd.Timestamp("2026-10-05 12:00", tz="UTC")


def _frames(direction="up", d1=None):
    fr = trend_set(direction)
    points, tail = (BULLISH_POINTS, UP_TAIL) if direction == "up" else (BEARISH_POINTS, DOWN_TAIL)
    fr["D1"] = d1 if d1 is not None else path_candles(points, 10, 1440, tail)
    fr["M1"] = fr["M5"]  # M1 structure only feeds the 1M checklist item; not needed for these checks
    return fr


# --- Fixtures with a real sweep -> MSS -> displacement -> retracement, for the hardening tests ----
# One M15 candle (idx 30) sweeps 98.0, closes above the 101.2 swing high with a big body: the sweep,
# the structure shift and the displacement are all the SAME closed bar, matching what the raw-MT5
# validation found (see docs/entry-model-v1-plan.md). Built on the exact bars tests/test_sequence.py
# already proves against analysis.sequence.evaluate_sequence, so the chronology is independently known.
SWEEP_MSS_DISP = [(99.0, 102.0, 98.0, 101.9)]
SIMULTANEOUS_ROWS = QUIET + SWING_HIGH + DECLINE + SWEEP_MSS_DISP + FOLLOW + RETRACE
SIMULTANEOUS_SWEEP_IDX = len(QUIET) + len(SWING_HIGH) + len(DECLINE)  # == 30


def _simultaneous_m15():
    m15 = make_candles(SIMULTANEOUS_ROWS, tf_minutes=15)
    sweep_time = m15["time"].iloc[SIMULTANEOUS_SWEEP_IDX]
    sweep = LiquidityEvent(sweep_time, "Asian Low swept", "Asian Low", 98.8, "sweep_low")
    return m15, sweep


def _frames_with_sweep(m15):
    """A LONG-biased HTF context (trend_set) with `m15` substituted as the M15 frame, so a sweep
    injected into it drives the 15M setup-formation layer end to end."""
    fr = trend_set("up")
    fr["D1"] = path_candles(BULLISH_POINTS, 10, 1440, UP_TAIL)
    fr["M15"] = m15
    fr["M1"] = fr["M5"]
    return fr


def _evaluate_with_sweep(m15, sweep, now=NOW):
    fr = _frames_with_sweep(m15)
    with mock.patch.object(M, "detect_sweeps", lambda df, zones: [sweep]):
        return M.evaluate(fr, now)


# --- OTE arithmetic ------------------------------------------------------------------------------

def test_ote_long_band_is_the_0_62_to_0_79_retracement_of_the_up_impulse():
    o = compute_ote("LONG", impulse_low=100.0, impulse_high=110.0)
    assert o.band_high == pytest.approx(110 - 0.62 * 10)
    assert o.band_low == pytest.approx(110 - 0.79 * 10)


def test_ote_short_band_mirrors_the_long_band():
    s = compute_ote("SHORT", impulse_low=100.0, impulse_high=110.0)
    assert s.band_low == pytest.approx(100 + 0.62 * 10)
    assert s.band_high == pytest.approx(100 + 0.79 * 10)


def test_ote_overlap_states_full_partial_none():
    # The LONG band for 100..110 is 102.1 to 103.8.
    assert compute_ote("LONG", 100, 110, 102.5, 103.5).overlap == "FULL"
    assert compute_ote("LONG", 100, 110, 103.0, 104.0).overlap == "PARTIAL"
    assert compute_ote("LONG", 100, 110, 109.0, 110.0).overlap == "NONE"


def test_ote_rejects_an_impulse_with_no_range():
    with pytest.raises(ValueError):
        compute_ote("LONG", 110, 110)


# --- Setup Confidence ----------------------------------------------------------------------------

def test_confidence_is_deterministic_and_every_point_has_a_named_reason():
    passed = ["htf_1d_bias", "liquidity_sweep", "mss", "displacement"]
    reasons = {n: f"because {n}" for n in passed}
    a = C.score(passed, reasons, [])
    b = C.score(passed, reasons, [])
    assert a == b
    assert {e["name"] for e in a["positive"]} == set(passed)
    assert all(e["reason"] == f"because {e['name']}" for e in a["positive"])


def test_confidence_group_caps_stop_correlated_evidence_being_double_counted():
    htf = ["htf_1d_bias", "htf_4h_bias", "h1_context_aligned"]  # 10 + 10 + 5 = 25, the group cap
    out = C.score(htf, {}, [])
    assert out["score"] == C.GROUP_CAP["htf"]
    struct = C.score(["mss", "displacement"], {}, [])
    assert sum(e["points"] for e in struct["positive"] if e["group"] == "structure") <= C.GROUP_CAP["structure"]


def test_contradictions_subtract_and_are_listed_not_hidden():
    base = C.score(["htf_1d_bias", "htf_4h_bias", "liquidity_sweep"], {}, [])
    with_one = C.score(["htf_1d_bias", "htf_4h_bias", "liquidity_sweep"], {}, ["1H bearish"])
    assert with_one["score"] == base["score"] - C.CONTRADICTION_PENALTY
    assert with_one["negative"][0]["reason"] == "1H bearish"


def test_contradiction_penalty_is_capped_and_score_stays_in_range():
    many = ["x"] * 10
    out = C.score([], {}, many)
    assert out["score"] == 0
    assert sum(e["points"] for e in out["negative"]) == -C.CONTRADICTION_PENALTY * 10  # listed in full
    full = C.score(list(C.WEIGHTS), {}, [])
    assert 0 <= full["score"] <= 100


def test_confidence_is_labelled_heuristic_and_never_a_probability():
    out = C.score(["htf_1d_bias"], {}, [])
    assert out["type"] == "HEURISTIC"
    assert "probability" in out["note"].lower() and "not" in out["note"].lower()
    assert "probability" not in out["label"].lower()
    assert C.label_for(30) == "EARLY" and C.label_for(50) == "DEVELOPING"
    assert C.label_for(70) == "WELL_SUPPORTED" and C.label_for(90) == "STRONG_EVIDENCE"


def test_unknown_confidence_item_is_rejected():
    with pytest.raises(KeyError):
        C.score(["made_up_item"], {}, [])


# --- Entry model on synthetic market context ----------------------------------------------------

def test_aligned_bullish_context_without_a_sweep_waits_for_the_sweep():
    out = M.evaluate(_frames("up"), NOW)
    assert out["direction"] == "LONG"
    assert out["state"] == "HTF_ALIGNED"
    assert out["next_condition"]["text"].startswith("sell-side")
    assert out["entry"]["status"] == "WAITING" and out["entry"]["price"] is None
    assert out["entry"]["price"] is None and out["stop"] is None  # no plan before the entry confirmation


def test_aligned_bearish_context_is_the_mirror_and_waits_for_a_buy_side_sweep():
    out = M.evaluate(_frames("down"), NOW)
    assert out["direction"] == "SHORT"
    assert out["state"] == "HTF_ALIGNED"
    assert out["next_condition"]["text"].startswith("buy-side")


def test_disagreeing_daily_and_four_hour_context_is_no_setup():
    down_d1 = path_candles(BEARISH_POINTS, 10, 1440, DOWN_TAIL)
    out = M.evaluate(_frames("up", d1=down_d1), NOW)
    assert out["direction"] is None
    assert out["state"] == "NO_SETUP"
    assert out["setup_confidence"] is None


def test_range_context_is_no_setup():
    fr = range_set()
    fr["D1"] = fr["H4"]
    out = M.evaluate(fr, NOW)
    assert out["state"] == "NO_SETUP"


def test_insufficient_history_is_reported_not_guessed():
    fr = _frames("up")
    fr["M15"] = fr["M15"].iloc[:5]
    out = M.evaluate(fr, NOW)
    assert out["state"] == "INSUFFICIENT_DATA"
    assert out["direction"] is None


def test_forming_candle_never_changes_the_result():
    base = _frames("up")
    forming = dict(base)
    forming["M5"] = with_forming_bar(base, "M5")["M5"]
    forming["M15"] = with_forming_bar(base, "M15")["M15"]
    assert M.evaluate(base, NOW) == M.evaluate(forming, NOW)


def test_checklist_carries_status_timeframe_and_reason_for_every_item():
    out = M.evaluate(_frames("up"), NOW)
    allowed = {"PASS", "FAIL", "WAITING", "NOT_APPLICABLE", "INVALIDATED", "PARTIAL"}
    assert out["checklist"]
    for item in out["checklist"]:
        assert item["status"] in allowed
        assert item["timeframe"] and item["reason"]


def test_timeframe_roles_are_the_ones_the_spec_names():
    assert M.ROLE_TF == {"1d": "D1", "4h": "H4", "1h": "H1", "15m": "M15", "5m": "M5", "1m": "M1"}


def test_the_disclaimer_says_manual_and_not_a_signal():
    assert "Manual decision support" in M.DISCLAIMER and "Not a signal" in M.DISCLAIMER


# --- Entry Model's own sweep-validity window (bar count, independent of A+) ---------------------

def test_sweep_within_the_entry_model_window_records_age_in_bars_and_minutes():
    m15, sweep = _simultaneous_m15()
    out = _evaluate_with_sweep(m15, sweep)
    assert out["state"] != "EXPIRED"
    assert out["liquidity"]["sweep"]["age_bars"] == 2
    assert out["liquidity"]["sweep"]["age_minutes"] == 2 * 15


def test_sweep_older_than_the_entry_model_window_expires_independent_of_wall_clock_and_of_a_plus():
    # Padding bars push the sweep to 9 M15 bars old (> ENTRY_MODEL_SWEEP_MAX_BARS=8), but `now` is
    # only 35 minutes after the sweep -- well inside the 60-minute A+ window. The old wall-clock
    # check would not have expired this; the bar-count check must, because it is this model's own.
    padded = SIMULTANEOUS_ROWS + [(100.8, 100.9, 100.7, 100.8)] * 7
    m15 = make_candles(padded, tf_minutes=15)
    sweep_time = m15["time"].iloc[SIMULTANEOUS_SWEEP_IDX]
    sweep = LiquidityEvent(sweep_time, "Asian Low swept", "Asian Low", 98.8, "sweep_low")
    close_now = sweep_time + pd.Timedelta(minutes=35)
    assert close_now - sweep_time < pd.Timedelta(minutes=config.AI_STRATEGY_SWEEP_WINDOW_MINUTES)

    out = _evaluate_with_sweep(m15, sweep, now=close_now)
    assert out["state"] == "EXPIRED"
    assert out["liquidity"]["sweep"]["age_bars"] == 9
    assert "9 M15 bars old" in out["invalidation"]["text"]
    assert out["setup_record"]["outcome_status"] == "EXPIRED_BEFORE_ENTRY"
    # No outcome is ever fabricated, even on an EXPIRED record.
    for field_name in D.OUTCOME_FIELDS:
        assert out["setup_record"][field_name] is None


def test_entry_model_sweep_window_never_reads_the_a_plus_setting(monkeypatch):
    m15, sweep = _simultaneous_m15()  # 2 M15 bars old
    # Shrinking the A+ setting to near-zero must change nothing here: this model never reads it.
    monkeypatch.setattr(config, "AI_STRATEGY_SWEEP_WINDOW_MINUTES", 0)
    out = _evaluate_with_sweep(m15, sweep)
    assert out["state"] != "EXPIRED"
    # Its own setting is what actually governs it.
    monkeypatch.setattr(config, "ENTRY_MODEL_SWEEP_MAX_BARS", 1)
    out = _evaluate_with_sweep(m15, sweep)
    assert out["state"] == "EXPIRED"


# --- Simultaneous sweep, structure shift and displacement ----------------------------------------

def test_simultaneous_sweep_mss_and_displacement_is_explicit_in_the_output():
    m15, sweep = _simultaneous_m15()
    out = _evaluate_with_sweep(m15, sweep)
    assert out["sequence"]["ordering"] == "SIMULTANEOUS"
    assert out["sequence"]["chronology_ok"] is True
    assert out["sequence"]["sweep_is_mss_bar"] is True
    assert out["sequence"]["sweep_is_displacement_bar"] is True
    # Both the structure-shift and displacement checklist items are already PASS on the sweep bar.
    by_name = {c["name"]: c for c in out["checklist"]}
    assert by_name["MSS"]["status"] == "PASS" and by_name["Displacement"]["status"] == "PASS"


def test_invalidated_state_still_reports_sequence_ordering():
    # A later bar closes back below the swept low: invalidated, per analysis.sequence's own rule.
    broken = SIMULTANEOUS_ROWS + [(100.8, 100.9, 97.4, 97.5)]
    m15 = make_candles(broken, tf_minutes=15)
    sweep_time = m15["time"].iloc[SIMULTANEOUS_SWEEP_IDX]
    sweep = LiquidityEvent(sweep_time, "Asian Low swept", "Asian Low", 98.8, "sweep_low")
    out = _evaluate_with_sweep(m15, sweep)
    assert out["state"] == "INVALIDATED"
    assert out["sequence"] is not None  # previously missing on this path entirely
    assert out["sequence"]["ordering"] == "SIMULTANEOUS"
    assert out["setup_record"]["outcome_status"] == "INVALIDATED_BEFORE_ENTRY"


# --- 1M confirmation: a specific closed bar, never a vague current-state reading -----------------

def _m1_with_mss(steps=80):
    """Bearish structure, then a sharp bullish reversal: a bullish MSS appears on one specific
    closed M1 bar, at a known time, the same primitive (structure_transitions) already used for
    bar-tied M5/M15/H1/H4 events in Analysis V2."""
    return path_candles(BEARISH_POINTS + [100, 130], steps, 1, [130, 130, 130, 130])


def test_m1_confirmation_cites_the_specific_closed_bar_not_a_vague_state():
    m1 = _m1_with_mss(steps=24)
    conf = M._m1_confirmation(m1, "LONG", pd.Timestamp("2026-01-05 00:00", tz="UTC"))
    assert conf is not None
    assert conf["event_type"] == "MSS"
    assert conf["direction"] == "bullish"
    assert conf["closed_bar"] is True
    assert conf["time_utc"] == "2026-01-05T02:38:00+00:00"
    assert isinstance(conf["bar_index"], int) and m1["time"].iloc[conf["bar_index"]] == pd.Timestamp(conf["time_utc"])
    assert isinstance(conf["price"], float)


def test_m1_confirmation_waits_when_the_only_mss_is_before_the_5m_confirmation_bar():
    m1 = _m1_with_mss()
    conf = M._m1_confirmation(m1, "LONG", pd.Timestamp("2026-01-06 00:00", tz="UTC"))
    assert conf is None  # the MSS happened, but before the cutoff -- not valid confirmation evidence


def test_m1_confirmation_requires_a_direction_match():
    m1 = _m1_with_mss()  # only a bullish MSS exists
    assert M._m1_confirmation(m1, "SHORT", pd.Timestamp("2026-01-05 00:00", tz="UTC")) is None


def test_m1_confirmation_needs_enough_history_or_waits_rather_than_guessing():
    short_m1 = _m1_with_mss().iloc[:25].reset_index(drop=True)
    assert M._m1_confirmation(short_m1, "LONG", pd.Timestamp("2026-01-05", tz="UTC")) is None
    assert M._m1_confirmation(None, "LONG", pd.Timestamp("2026-01-05", tz="UTC")) is None
    assert M._m1_confirmation(_m1_with_mss(), "LONG", None) is None


def test_1m_confirmation_is_never_consulted_before_5m_confirmation(monkeypatch):
    # Even if a bar-tied M1 MSS exists, it must not count until the 5M confirmation itself is PASS --
    # 1M must never override or pre-empt 1H/5M, only confirm after them.
    called = []
    monkeypatch.setattr(M, "_m1_confirmation", lambda *a, **k: called.append(1) or {"time_utc": "x"})
    m15, sweep = _simultaneous_m15()  # reaches RETRACEMENT_WAITING; 5M confirmation is WAITING here
    out = _evaluate_with_sweep(m15, sweep)
    assert out["timeframes"]["5m"]["confirmed"] is False
    assert out["m1_confirmation"] is None
    assert not called


def test_entry_ready_requires_a_real_bar_tied_1m_event_end_to_end():
    """Full chain: HTF aligned, sweep == MSS == displacement bar, FVG retraced, a (synthetic) 5M
    structure shift after the retest, and a real, bar-tied M1 MSS after that 5M bar. Only the M5
    sequence is substituted (to avoid hand-building a second, independently-timed M5 fixture); the
    M15 sequence and the M1 confirmation are the real primitives."""
    m15, sweep = _simultaneous_m15()
    fr = _frames_with_sweep(m15)
    fr["M1"] = _m1_with_mss(steps=80)  # real bullish MSS at 2026-01-05 08:46

    confirm_time = pd.Timestamp("2026-01-05 08:15", tz="UTC")  # after the FVG retest (08:00)
    fake_seq = MarketSequence(
        direction="bullish", sweep=sweep,
        steps=(SequenceStep("STRUCTURE_SHIFT", CONFIRMED, confirm_time, None, "fake 5m MSS"),
               SequenceStep("DISPLACEMENT", CONFIRMED, confirm_time, None, "fake")),
        stage="STRUCTURE_SHIFT", is_complete=False, invalidated=False, invalidation_reason="",
        superseded_by=None, chronology_ok=True, evidence=None,
    )
    real_build_sequences = M.build_sequences

    def fake_build_sequences(df, sweeps):
        return real_build_sequences(df, sweeps) if len(df) == len(m15) else [fake_seq]

    with mock.patch.object(M, "detect_sweeps", lambda df, zones: [sweep]), \
         mock.patch.object(M, "build_sequences", fake_build_sequences):
        out = M.evaluate(fr, NOW)

    assert out["state"] == "ENTRY_READY"
    assert out["timeframes"]["5m"]["confirmed"] is True
    m1c = out["m1_confirmation"]
    assert m1c == {"time_utc": "2026-01-05T08:46:00+00:00", "bar_index": 526, "direction": "bullish",
                   "event_type": "MSS", "price": m1c["price"], "closed_bar": True, "detail": m1c["detail"]}
    assert out["entry"]["status"] == "PLANNED" and out["entry"]["price"] is not None
    assert out["setup_record"]["confirm_1m_time_utc"] == m1c["time_utc"]


# --- Outcome-dataset foundation -------------------------------------------------------------------

def test_no_setup_record_before_a_sweep_exists():
    assert M.evaluate(_frames("up"), NOW)["setup_record"] is None  # HTF_ALIGNED: no sweep yet
    down_d1 = path_candles(BEARISH_POINTS, 10, 1440, DOWN_TAIL)
    assert M.evaluate(_frames("up", d1=down_d1), NOW)["setup_record"] is None  # NO_SETUP


def test_setup_record_carries_identity_provenance_and_an_unfabricated_pending_outcome():
    m15, sweep = _simultaneous_m15()
    out = _evaluate_with_sweep(m15, sweep)
    rec = out["setup_record"]
    assert rec is not None
    assert rec["setup_id"] == f"LONG:{sweep.time.isoformat()}"
    assert rec["direction"] == "LONG"
    assert rec["sweep_time_utc"] == sweep.time.isoformat()
    assert rec["mss_time_utc"] == sweep.time.isoformat()  # simultaneous: same bar
    assert rec["event_ordering"]["mss_vs_displacement"] == "SIMULTANEOUS"
    assert rec["evidence_log"] == out["checklist"]  # the engine's own observations, not a restatement
    assert rec["timeframes"] == out["timeframes"]
    assert rec["market_conditions"]["regime"]["regime"]
    assert rec["market_conditions"]["session"] in ("Asian", "London", "New York", "Off-session")
    # Outcome fields: a lifecycle label only, never a fabricated trading result.
    assert rec["outcome_status"] == "PENDING"
    for field_name in D.OUTCOME_FIELDS:
        assert rec[field_name] is None


def test_setup_record_setup_id_is_stable_across_repeated_evaluations():
    m15, sweep = _simultaneous_m15()
    out_a = _evaluate_with_sweep(m15, sweep, now=NOW)
    out_b = _evaluate_with_sweep(m15, sweep, now=NOW + pd.Timedelta(minutes=5))
    assert out_a["setup_record"]["setup_id"] == out_b["setup_record"]["setup_id"]


def test_dedupe_setup_records_keeps_the_latest_per_setup_id_in_first_seen_order():
    a1 = {"setup_id": "LONG:t1", "generated_at_utc": "2026-01-01T00:00:00+00:00", "v": 1}
    a2 = {"setup_id": "LONG:t1", "generated_at_utc": "2026-01-01T00:05:00+00:00", "v": 2}
    b1 = {"setup_id": "SHORT:t2", "generated_at_utc": "2026-01-01T00:01:00+00:00", "v": 3}
    out = D.dedupe_setup_records([a1, b1, a2])
    assert [r["setup_id"] for r in out] == ["LONG:t1", "SHORT:t2"]  # first-seen order
    assert out[0]["v"] == 2  # the latest record for LONG:t1


# --- Safety: no execution, no LLM in the decision path -----------------------------------------

def test_entry_model_source_has_no_llm_or_order_dependency():
    root = pathlib.Path(M.__file__).parent
    banned = ("ai.providers", "ai.prompts", "anthropic", "groq", "openai", "place_order", "order_send",
              "trade_execution", "execute_trade")
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, f"{path.name} references {token}"


# --- Read-only route --------------------------------------------------------------------------
# NOTE: api/routes/entry_model.py calls `analysis.entry_model.evaluate`, which now resolves to the
# Top-Down Multi-Timeframe Entry Model (hierarchy.py), not V1's model.py -- that is the explicit,
# authorized redesign (see docs/entry-model-v2-hierarchy.md). This route-level test asserts the
# route wires its real, current response through correctly; it is intentionally decoupled from
# V1's own exact output shape, which the tests above (calling M.evaluate directly) still cover.

def test_route_returns_a_result_from_closed_candles(monkeypatch):
    from api.routes import entry_model as route
    from mt5 import market_data

    frames = _frames("up")
    frames["M1"] = frames["M5"]

    def fake(timeframe, count):
        return frames[timeframe]

    monkeypatch.setattr(market_data, "get_candles", fake)
    out = route.get_entry_model()
    assert out["symbol"] == "XAUUSD"
    assert out["direction"] in ("LONG", "SHORT", "CONFLICTED", None)
    assert "Manual decision support" in out["disclaimer"]


def test_route_maps_mt5_outage_to_503(monkeypatch):
    from fastapi import HTTPException
    from api.routes import entry_model as route
    from mt5 import market_data

    def down(timeframe, count):
        raise market_data.MarketDataError("MT5 not connected")

    monkeypatch.setattr(market_data, "get_candles", down)
    with pytest.raises(HTTPException) as exc:
        route.get_entry_model()
    assert exc.value.status_code == 503
