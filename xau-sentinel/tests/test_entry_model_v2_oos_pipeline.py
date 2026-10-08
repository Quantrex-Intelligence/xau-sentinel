"""Regression tests for the Entry Model V2 OOS research infrastructure
(research/entry_model_v2_oos/*). These test the PLUMBING only -- temporal boundary enforcement,
model-fingerprint checking, funnel/candidate-extraction correctness on crafted synthetic frames --
and never claim any out-of-sample finding. No real MT5 data is used here.
"""
import pandas as pd
import pytest

from research.entry_model_v2_oos import boundary, pipeline, spec


# --- spec.py: the frozen hypothesis bound check ---------------------------------------------------

def test_in_hypothesis_group_matches_the_frozen_half_open_interval():
    assert spec.in_hypothesis_group(0.5) is True
    assert spec.in_hypothesis_group(0.999) is True
    assert spec.in_hypothesis_group(1.0) is False  # exclusive upper bound
    assert spec.in_hypothesis_group(0.49999) is False
    assert spec.in_hypothesis_group(None) is False


def test_model_fingerprint_is_deterministic_and_matches_the_frozen_value():
    # If this fails, analysis/entry_model/* or ai/strategy/rules.py has changed since the spec was
    # frozen -- that is a real signal (re-freeze deliberately), not a flaky test to retry.
    assert spec.compute_model_fingerprint() == spec.compute_model_fingerprint()
    assert spec.compute_model_fingerprint() == spec.FROZEN_MODEL_FINGERPRINT


# --- boundary.py: temporal guards ------------------------------------------------------------------

def test_sample_times_after_boundary_pass_silently():
    boundary.assert_sample_times_after_boundary(
        [spec.IS_DATA_END + pd.Timedelta(minutes=5), spec.IS_DATA_END + pd.Timedelta(days=1)]
    )  # no exception


def test_sample_time_at_the_boundary_itself_is_rejected():
    with pytest.raises(boundary.OOSBoundaryViolation):
        boundary.assert_sample_times_after_boundary([spec.IS_DATA_END])


def test_sample_time_before_the_boundary_is_rejected():
    with pytest.raises(boundary.OOSBoundaryViolation):
        boundary.assert_sample_times_after_boundary([spec.IS_DATA_END - pd.Timedelta(days=30)])


def test_one_bad_timestamp_among_many_good_ones_still_raises():
    with pytest.raises(boundary.OOSBoundaryViolation):
        boundary.assert_sample_times_after_boundary([
            spec.IS_DATA_END + pd.Timedelta(hours=1),
            spec.IS_DATA_END - pd.Timedelta(hours=1),  # the one offender
            spec.IS_DATA_END + pd.Timedelta(hours=2),
        ])


def test_existing_cached_is_data_end_itself_is_correctly_rejected_as_non_oos():
    # Demonstrates the guard against the actual IS data ceiling this research line hit: the cached
    # history's own last bar is AT spec.IS_DATA_END, not strictly after it, so it must be rejected.
    with pytest.raises(boundary.OOSBoundaryViolation):
        boundary.assert_sample_times_after_boundary([spec.IS_DATA_END])


def test_candidates_after_boundary_pass_silently():
    cands = [{"setup_id": "LONG:x", "first_asof": str(spec.IS_DATA_END + pd.Timedelta(days=1))}]
    result = boundary.assert_candidates_after_boundary(cands)
    assert result.n_violations == 0
    assert result.n_candidates == 1


def test_candidates_at_or_before_boundary_are_rejected_with_offending_ids_named():
    cands = [
        {"setup_id": "LONG:good", "first_asof": str(spec.IS_DATA_END + pd.Timedelta(days=1))},
        {"setup_id": "SHORT:bad", "first_asof": str(spec.IS_DATA_END)},
    ]
    with pytest.raises(boundary.OOSBoundaryViolation, match="SHORT:bad"):
        boundary.assert_candidates_after_boundary(cands)


def test_assert_model_unchanged_passes_against_the_live_frozen_files():
    assert boundary.assert_model_unchanged() == spec.FROZEN_MODEL_FINGERPRINT


def test_assert_model_unchanged_raises_if_the_fingerprint_is_tampered(monkeypatch):
    monkeypatch.setattr(spec, "FROZEN_MODEL_FINGERPRINT", "0" * 64)
    with pytest.raises(boundary.FrozenModelChanged):
        boundary.assert_model_unchanged()


# --- pipeline.py: funnel / extraction / hypothesis split on crafted synthetic records --------------

def _rec(state, direction=None, setup_direction=None, confirmation_status="CONFIRMED",
        htf_context="BULLISH", intraday_bias="BULLISH", compatible=True, setup_status="SETUP_CONFIRMED",
        asof="2026-11-01T00:00:00+00:00", stop=None, target=None, rr=None, confidence=55):
    """Builds a minimal synthetic hierarchy.evaluate()-shaped record -- just enough of the real shape
    for funnel()/extract_candidates()/split_hypothesis_vs_comparison() to exercise their own logic,
    without running the real model at all."""
    entry_candidate = None
    if stop is not None or target is not None:
        entry_candidate = {
            "direction": setup_direction, "entry": 100.0,
            "stop": None if stop is None else {"price": stop, "basis": "test"},
            "target": None if target is None else {"price": target, "basis": "test"},
            "rr": rr,
        }
    return {
        "direction": direction, "state": state, "asof": asof,
        "higher_timeframe": {"htf_context": htf_context},
        "intraday": {"intraday_bias": intraday_bias, "compatible_with_htf": compatible},
        "setup_15m": {"setup_direction": setup_direction, "setup_status": setup_status},
        "confirmation_5m": {"confirmation_status": confirmation_status},
        "precision_1m": {"precision_status": "NOT_APPLICABLE"},
        "entry_candidate": entry_candidate,
        "confidence": {"score": confidence},
    }


def test_funnel_counts_are_monotonically_non_increasing_down_the_ladder():
    records = [
        _rec("NO_CONTEXT", htf_context="NEUTRAL"),
        _rec("HTF_CONTEXT_ALIGNED", intraday_bias="NEUTRAL"),
        _rec("ENTRY_CONFIRMATION_DEVELOPING", setup_direction="LONG", confirmation_status="DEVELOPING"),
        _rec("ENTRY_READY", direction="LONG", setup_direction="LONG", stop=99.0, target=101.0, rr=0.8),
    ]
    rows = pipeline.funnel(records)
    counts = [r["n"] for r in rows]
    assert counts[0] == len(records)
    assert all(counts[i] >= counts[i + 1] for i in range(len(counts) - 1))
    assert rows[-1]["n"] == 1  # only the ENTRY_READY row has both stop and target


def test_extract_candidates_groups_consecutive_rows_sharing_direction_and_stop():
    # Two consecutive ENTRY_READY rows with the same direction and the same stop price (the
    # structural anchor persisting) are one candidate, matching the in-sample study's own
    # definition. A stop transitioning from None (pre-confirmation) to a real price is itself a
    # change in the grouping key by design -- see
    # test_extract_candidates_treats_a_newly_appearing_stop_as_a_new_group below.
    records = [
        _rec("ENTRY_READY", direction="LONG", setup_direction="LONG", confirmation_status="CONFIRMED",
            stop=99.0, target=101.0, rr=0.67, asof="2026-11-01T00:10:00+00:00"),
        _rec("ENTRY_READY", direction="LONG", setup_direction="LONG", confirmation_status="CONFIRMED",
            stop=99.0, target=101.0, rr=0.67, asof="2026-11-01T00:15:00+00:00"),
    ]
    cands = pipeline.extract_candidates(records)
    assert len(cands) == 1
    c = cands[0]
    assert c["n_observations"] == 2
    assert c["direction"] == "LONG"
    assert c["first_asof"] == "2026-11-01T00:10:00+00:00"
    assert c["last_asof"] == "2026-11-01T00:15:00+00:00"
    assert c["tradeable"] is True
    assert c["best_state"] == "ENTRY_READY"


def test_extract_candidates_treats_a_newly_appearing_stop_as_a_new_group():
    # A setup's own identity, under this methodology, is only stable once it has a stop price. Rows
    # observed before a stop exists (DEVELOPING, stop=None) are therefore their own funnel entry,
    # separate from the later row where confirmation produces a real stop -- not silently merged
    # forward. This matches the in-sample study, where some candidates never progress past
    # DEVELOPING and are counted as their own (untradeable) entries rather than discarded.
    records = [
        _rec("ENTRY_CONFIRMATION_DEVELOPING", setup_direction="LONG", confirmation_status="DEVELOPING",
            asof="2026-11-01T00:00:00+00:00"),
        _rec("ENTRY_READY", direction="LONG", setup_direction="LONG", confirmation_status="CONFIRMED",
            stop=99.0, target=101.0, rr=0.67, asof="2026-11-01T00:10:00+00:00"),
    ]
    cands = pipeline.extract_candidates(records)
    assert len(cands) == 2
    assert cands[0]["tradeable"] is False
    assert cands[1]["tradeable"] is True


def test_extract_candidates_does_not_collapse_developing_rows_of_different_underlying_direction():
    # The bug this test guards against: grouping by the EXPOSED (gated) direction instead of the
    # working setup_15m direction would merge these into one group, since both rows' exposed
    # direction is None at ENTRY_CONFIRMATION_DEVELOPING.
    records = [
        _rec("ENTRY_CONFIRMATION_DEVELOPING", setup_direction="LONG", confirmation_status="DEVELOPING",
            asof="2026-11-01T00:00:00+00:00"),
        _rec("ENTRY_CONFIRMATION_DEVELOPING", setup_direction="SHORT", confirmation_status="DEVELOPING",
            asof="2026-11-01T00:05:00+00:00"),
    ]
    cands = pipeline.extract_candidates(records)
    assert len(cands) == 2
    assert {c["direction"] for c in cands} == {"LONG", "SHORT"}


def test_extract_candidates_starts_a_new_group_when_stop_price_changes():
    records = [
        _rec("ENTRY_READY", direction="LONG", setup_direction="LONG", stop=99.0, target=101.0, rr=0.67,
            asof="2026-11-01T00:00:00+00:00"),
        _rec("ENTRY_READY", direction="LONG", setup_direction="LONG", stop=97.0, target=101.0, rr=0.5,
            asof="2026-11-01T00:05:00+00:00"),
    ]
    cands = pipeline.extract_candidates(records)
    assert len(cands) == 2  # different stop -> a different structural anchor -> a new candidate


def test_extract_candidates_excludes_non_qualifying_states():
    records = [_rec("HTF_CONTEXT_ALIGNED"), _rec("CONFLICTED", setup_direction="LONG")]
    assert pipeline.extract_candidates(records) == []


def test_split_hypothesis_vs_comparison_uses_spec_bounds_only():
    cands = [
        {"setup_id": "a", "rr": 0.6}, {"setup_id": "b", "rr": 1.4},
        {"setup_id": "c", "rr": None}, {"setup_id": "d", "rr": 0.5},
    ]
    split = pipeline.split_hypothesis_vs_comparison(cands)
    assert {c["setup_id"] for c in split["hypothesis_group"]} == {"a", "d"}
    assert {c["setup_id"] for c in split["comparison_group"]} == {"b", "c"}


def test_label_candidate_outcome_returns_untradeable_status_without_touching_price_data():
    cand = {"tradeable": False}
    assert pipeline.label_candidate_outcome(cand, pd.DataFrame()) == {"outcome_status": "UNTRADEABLE_INCOMPLETE"}


def test_label_candidate_outcome_reuses_the_frozen_outcome_module_for_a_tradeable_candidate():
    cand = {"tradeable": True, "direction": "LONG", "entry": 100.0, "stop": 98.0, "target": 106.0,
           "first_asof": "2026-11-01T00:00:00+00:00"}
    m5 = pd.DataFrame({
        "time": pd.date_range("2026-11-01 00:05", periods=3, freq="5min", tz="UTC"),
        "high": [101, 103, 106.5], "low": [99.5, 100, 105], "close": [100.5, 102, 106],
    })
    out = pipeline.label_candidate_outcome(cand, m5)
    assert out["outcome_status"] == "TARGET_HIT"
    assert out["outcome_r"] == 3.0  # risk 2.0, reward 6.0


def test_run_evaluation_samples_enforces_the_oos_boundary_by_default():
    with pytest.raises(boundary.OOSBoundaryViolation):
        pipeline.run_evaluation_samples({}, [spec.IS_DATA_END - pd.Timedelta(days=1)])


def test_build_sample_times_excludes_a_bar_whose_close_time_leaks_past_the_boundary_but_whose_own_time_does_not():
    # Regression test for a real boundary leak found while demonstrating this guard against the
    # actual cached IS data: the IS dataset's own last M5 bar has time == spec.IS_DATA_END but
    # close_time == spec.IS_DATA_END + 5 minutes. Filtering on close_time alone would have let that
    # already-known IS bar back in as a false "OOS" sample. build_sample_times must filter on the
    # bar's own `time` field instead.
    from research.entry_model_v2_oos.run_oos_evaluation import build_sample_times

    last_is_bar_time = spec.IS_DATA_END
    first_true_oos_bar_time = spec.IS_DATA_END + pd.Timedelta(minutes=5)
    m5 = pd.DataFrame({
        "time": [last_is_bar_time, first_true_oos_bar_time],
        "close_time": [last_is_bar_time + pd.Timedelta(minutes=5), first_true_oos_bar_time + pd.Timedelta(minutes=5)],
        "is_closed": [True, True],
    })
    times = build_sample_times({"M5": m5}, sample_every=1)
    assert len(times) == 1
    assert times[0] == first_true_oos_bar_time + pd.Timedelta(minutes=5)


def test_build_sample_times_returns_empty_for_data_that_never_goes_past_the_boundary():
    from research.entry_model_v2_oos.run_oos_evaluation import build_sample_times

    m5 = pd.DataFrame({
        "time": [spec.IS_DATA_END - pd.Timedelta(minutes=5), spec.IS_DATA_END],
        "close_time": [spec.IS_DATA_END, spec.IS_DATA_END + pd.Timedelta(minutes=5)],
        "is_closed": [True, True],
    })
    assert build_sample_times({"M5": m5}, sample_every=1) == []


def test_run_evaluation_samples_can_skip_the_boundary_check_only_when_explicitly_asked():
    # Used only by tests that want to exercise evaluation mechanics on pre-boundary synthetic times
    # without that being mistaken for a real OOS run. make_frames_at with empty raw data makes every
    # frame None, so hierarchy.evaluate() short-circuits to NO_CONTEXT -- this only checks that the
    # boundary bypass itself works, not any model behaviour.
    import analysis.entry_model.hierarchy as hierarchy
    records = pipeline.run_evaluation_samples(
        {}, [spec.IS_DATA_END - pd.Timedelta(days=1)], enforce_oos_boundary=False
    )
    assert len(records) == 1
    assert records[0]["state"] == "NO_CONTEXT"
