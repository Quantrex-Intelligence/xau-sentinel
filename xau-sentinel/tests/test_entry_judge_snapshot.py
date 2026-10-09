"""Tests for ai/entry_judge/snapshot.py -- eligibility, candidate identity, and the compact
evidence snapshot. Pure functions: no provider, no DB."""
import pandas as pd
import pytest

from ai.entry_judge import snapshot as snap
from research.entry_model_v2_oos import spec as oos_spec


def _result(**overrides):
    base = {
        "symbol": "XAUUSD", "as_of": "2026-10-08T12:00:00+00:00", "state": "NO_CONTEXT",
        "higher_timeframe": None, "intraday": None, "setup_15m": None, "confirmation_5m": None,
        "precision_1m": None, "entry_candidate": None, "confidence": None,
        "supporting_evidence": [], "contradicting_evidence": [], "invalidation": None,
        "next_condition": None,
    }
    base.update(overrides)
    return base


# --- eligibility -------------------------------------------------------------------------------

def test_eligible_states_match_the_frozen_oos_qualifying_states():
    # Deliberately duplicated (see snapshot.py's own comment) rather than imported -- this asserts
    # the duplicate hasn't drifted from research/entry_model_v2_oos/spec.py's frozen list.
    assert set(snap.ELIGIBLE_STATES) == set(oos_spec.QUALIFYING_STATES)


@pytest.mark.parametrize("state", snap.ELIGIBLE_STATES)
def test_each_eligible_state_is_eligible(state):
    assert snap.is_eligible(_result(state=state)) is True


@pytest.mark.parametrize("state", [
    "NO_CONTEXT", "HTF_LOCATION_IDENTIFIED", "HTF_CONTEXT_ALIGNED", "INTRADAY_BIAS_ESTABLISHED",
    "SETUP_DEVELOPING", "SETUP_CONFIRMED", "CONFLICTED", "INVALIDATED", "EXPIRED",
])
def test_ineligible_states_are_not_eligible(state):
    assert snap.is_eligible(_result(state=state)) is False


# --- working_direction -------------------------------------------------------------------------

def test_working_direction_reads_the_ungated_setup_15m_direction():
    result = _result(setup_15m={"setup_direction": "LONG"})
    assert snap.working_direction(result) == "LONG"


def test_working_direction_is_none_when_not_long_or_short():
    assert snap.working_direction(_result(setup_15m={"setup_direction": "NEUTRAL"})) is None
    assert snap.working_direction(_result(setup_15m={"setup_direction": "CONFLICTED"})) is None
    assert snap.working_direction(_result(setup_15m=None)) is None


# --- candidate_key -------------------------------------------------------------------------------

def test_candidate_key_prefers_the_earliest_evidence_timestamp_over_the_stop_price():
    # The evidence anchor must win even once a candidate (and its stop) exists -- see
    # candidate_key's own docstring for why: preferring the stop price here would make the key
    # change the moment confirmation completes, breaking identity continuity across states (the
    # exact bug this ordering was fixed to avoid).
    result = _result(
        setup_15m={"setup_direction": "LONG", "fvg": {"formed_at": "2026-10-08T11:00:00+00:00"}},
        entry_candidate={"stop": {"price": 2371.801}},
    )
    assert snap.candidate_key(result) == "LONG:evidence:2026-10-08T11:00:00+00:00"


def test_candidate_key_uses_fvg_formed_at_before_a_candidate_exists():
    result = _result(
        setup_15m={"setup_direction": "LONG", "fvg": {"formed_at": "2026-10-08T11:00:00+00:00"}},
        entry_candidate=None,
    )
    assert snap.candidate_key(result) == "LONG:evidence:2026-10-08T11:00:00+00:00"


def test_candidate_key_is_stable_across_the_entire_state_lifecycle():
    # The confirmed finding this test guards against: the SAME real-world setup, observed at
    # ENTRY_CONFIRMATION_DEVELOPING (no entry_candidate yet), ENTRY_CONFIRMED, PRECISION_AVAILABLE
    # and ENTRY_READY (entry_candidate.stop now exists), must resolve to the SAME candidate_key at
    # every stage -- otherwise store.get_latest() can never find the earlier row once confirmation
    # completes, and a genuine reassessment gets misclassified as a brand-new candidate.
    fvg = {"formed_at": "2026-10-09T10:00:00+00:00"}
    base = {"setup_15m": {"setup_direction": "LONG", "fvg": fvg, "supporting_evidence": []},
           "confirmation_5m": {"supporting_evidence": []}}
    developing = _result(state="ENTRY_CONFIRMATION_DEVELOPING", entry_candidate=None, **base)
    confirmed = _result(state="ENTRY_CONFIRMED", entry_candidate={"stop": {"price": 4095.0}}, **base)
    precision = _result(state="PRECISION_AVAILABLE", entry_candidate={"stop": {"price": 4095.0}}, **base)
    ready = _result(state="ENTRY_READY", entry_candidate={"stop": {"price": 4095.0}}, **base)

    keys = [snap.candidate_key(r) for r in (developing, confirmed, precision, ready)]
    assert len(set(keys)) == 1, f"candidate_key changed across the lifecycle: {keys}"


def test_candidate_key_falls_back_to_earliest_supporting_evidence_timestamp():
    result = _result(
        setup_15m={
            "setup_direction": "SHORT", "fvg": None,
            "supporting_evidence": [{"timestamp": "2026-10-08T10:30:00+00:00"}, {"timestamp": "2026-10-08T10:15:00+00:00"}],
        },
        confirmation_5m={"supporting_evidence": [{"timestamp": "2026-10-08T10:45:00+00:00"}]},
        entry_candidate=None,
    )
    assert snap.candidate_key(result) == "SHORT:evidence:2026-10-08T10:15:00+00:00"


def test_candidate_key_is_none_when_direction_itself_has_not_resolved():
    assert snap.candidate_key(_result(setup_15m={"setup_direction": "NEUTRAL"})) is None


def test_candidate_key_stays_the_same_across_consecutive_polls_of_the_same_setup():
    # The exact scenario the dedup control depends on: two snapshots of the same real-world
    # candidate, same direction and stop, must produce the same key even if other fields (e.g.
    # as_of, confidence) differ between polls.
    r1 = _result(setup_15m={"setup_direction": "LONG"}, entry_candidate={"stop": {"price": 100.0}}, as_of="t1")
    r2 = _result(setup_15m={"setup_direction": "LONG"}, entry_candidate={"stop": {"price": 100.0}}, as_of="t2", confidence={"score": 70})
    assert snap.candidate_key(r1) == snap.candidate_key(r2)


def test_candidate_key_changes_when_the_stop_price_changes():
    r1 = _result(setup_15m={"setup_direction": "LONG"}, entry_candidate={"stop": {"price": 100.0}})
    r2 = _result(setup_15m={"setup_direction": "LONG"}, entry_candidate={"stop": {"price": 95.0}})
    assert snap.candidate_key(r1) != snap.candidate_key(r2)


# --- build_snapshot / fingerprint ----------------------------------------------------------------

def test_build_snapshot_never_fabricates_a_missing_entry_candidate():
    result = _result(state="ENTRY_CONFIRMATION_DEVELOPING", setup_15m={"setup_direction": "LONG"}, entry_candidate=None)
    snapshot = snap.build_snapshot(result)
    assert snapshot["entry_candidate"] is None


def test_build_snapshot_market_context_is_none_without_a_v2_result():
    snapshot = snap.build_snapshot(_result())
    assert snapshot["market_context"] is None


def test_fingerprint_is_stable_for_identical_snapshots():
    snapshot = snap.build_snapshot(_result(setup_15m={"setup_direction": "LONG"}))
    assert snap.fingerprint(snapshot) == snap.fingerprint(dict(snapshot))


def test_fingerprint_changes_when_material_evidence_changes():
    r1 = _result(setup_15m={"setup_direction": "LONG", "evidence_categories": ["FVG"]})
    r2 = _result(setup_15m={"setup_direction": "LONG", "evidence_categories": ["FVG", "DISPLACEMENT"]})
    assert snap.fingerprint(snap.build_snapshot(r1)) != snap.fingerprint(snap.build_snapshot(r2))


def test_candidate_created_at_parses_the_as_of_timestamp():
    result = _result(as_of="2026-10-08T12:00:00+00:00")
    assert snap.candidate_created_at(result) == pd.Timestamp("2026-10-08T12:00:00+00:00").to_pydatetime()
