"""Deterministic tests for the Entry Model V1 outcome-labeling stage (analysis/entry_model/outcome.py).

This is the research stage that follows the dataset foundation: it never changes a setup's own
facts, only adds what happened to price afterwards, against the setup's own plan."""
import pandas as pd
import pytest

from analysis.entry_model import outcome as O

ENTRY, STOP, TARGET = 100.0, 98.0, 106.0  # LONG: risk 2.0, reward 6.0 -> 3R target
RECORD_TIME = "2026-01-05T00:00:00+00:00"


def _record(direction="LONG", entry=ENTRY, stop=STOP, target=TARGET, outcome_status="PENDING"):
    return {
        "direction": direction,
        "entry": None if entry is None else {"price": entry},
        "stop": None if stop is None else {"price": stop},
        "targets": [] if target is None else [{"price": target}],
        "record_time_utc": RECORD_TIME,
        "outcome_status": outcome_status,
    }


def _bars(rows, start="2026-01-05 00:05", tf_minutes=5):
    times = pd.date_range(start, periods=len(rows), freq=f"{tf_minutes}min", tz="UTC")
    df = pd.DataFrame(rows, columns=["high", "low", "close"])
    df["time"] = times
    return df


# --- No plan yet: nothing to label, nothing fabricated -------------------------------------------

def test_no_plan_yet_keeps_the_record_s_existing_lifecycle_status():
    # EXPIRED_BEFORE_ENTRY/INVALIDATED_BEFORE_ENTRY/PENDING already describe this setup; labeling
    # must not override that with a generic "no plan" status when one was already set.
    rec = _record(entry=None, stop=None, target=None, outcome_status="EXPIRED_BEFORE_ENTRY")
    out = O.label_outcome(rec, _bars([(101, 99, 100)]))
    assert out == {"outcome_status": "EXPIRED_BEFORE_ENTRY"}
    for key in ("mfe", "mae", "outcome_r", "target_hit", "stop_hit"):
        assert key not in out  # not fabricated, not even as None -- this record was never touched


def test_no_plan_and_no_prior_status_falls_back_to_no_plan_to_label():
    rec = _record(entry=None, stop=None, target=None, outcome_status=None)
    out = O.label_outcome(rec, _bars([(101, 99, 100)]))
    assert out == {"outcome_status": O.NO_PLAN}


def test_missing_or_empty_price_history_is_pending_not_fabricated():
    rec = _record()
    assert O.label_outcome(rec, None)["outcome_status"] == "PENDING"
    assert O.label_outcome(rec, _bars([]))["outcome_status"] == "PENDING"


# --- Target hit first ------------------------------------------------------------------------------

def test_long_target_hit_before_stop_computes_the_planned_r():
    path = _bars([(101, 99.5, 100.5), (103, 100, 102), (106.5, 105, 106)])  # bar 3 touches the 106 target
    out = O.label_outcome(_record(), path)
    assert out["outcome_status"] == O.TARGET_HIT
    assert out["target_hit"] is True and out["stop_hit"] is False
    assert out["outcome_r"] == pytest.approx(3.0)  # reward 6.0 / risk 2.0
    assert out["expired"] is False
    assert out["time_to_target"] is not None and out["time_to_invalidation"] is None


def test_short_direction_is_the_exact_mirror():
    rec = _record(direction="SHORT", entry=100.0, stop=102.0, target=94.0)  # risk 2, reward 6 -> 3R
    path = _bars([(100.5, 97, 98), (99, 93.5, 94)])
    out = O.label_outcome(rec, path)
    assert out["outcome_status"] == O.TARGET_HIT
    assert out["outcome_r"] == pytest.approx(3.0)


# --- Stop hit first ---------------------------------------------------------------------------------

def test_long_stop_hit_before_target_is_minus_one_r_never_a_partial_loss():
    path = _bars([(101, 99.5, 100.5), (100, 97.5, 98.5)])  # bar 2 touches the 98.0 stop
    out = O.label_outcome(_record(), path)
    assert out["outcome_status"] == O.STOP_HIT
    assert out["stop_hit"] is True and out["target_hit"] is False
    assert out["outcome_r"] == -1.0
    assert out["time_to_invalidation"] is not None and out["time_to_target"] is None


def test_both_touched_on_the_same_bar_resolves_to_the_stop_conservatively():
    path = _bars([(107.0, 97.0, 100.0)])  # one wild bar: wicks through both the stop and the target
    out = O.label_outcome(_record(), path)
    assert out["outcome_status"] == O.STOP_HIT
    assert out["stop_hit"] is True and out["target_hit"] is False
    assert out["outcome_r"] == -1.0


# --- MFE/MAE tracked every bar, independent of the eventual outcome -------------------------------

def test_mfe_and_mae_track_the_best_and_worst_excursion_before_resolution():
    # Runs up 3 (favorable), back down 1 below entry (adverse), then hits target.
    path = _bars([(103.0, 100.0, 102.0), (100.0, 99.0, 99.5), (106.5, 105.0, 106.0)])
    out = O.label_outcome(_record(), path)
    assert out["mfe"] == pytest.approx(6.5)  # the high of the target-hit bar, 106.5 - 100
    assert out["mae"] == pytest.approx(1.0)  # entry 100 - low 99
    assert out["maximum_favorable_r"] == pytest.approx(3.25)  # 6.5 / risk 2.0
    assert out["maximum_adverse_r"] == pytest.approx(0.5)


# --- Still open: price history runs out before either level is touched ---------------------------

def test_still_open_when_the_path_runs_out_without_a_touch():
    path = _bars([(101, 99.5, 100.5), (102, 100.5, 101.5)])
    out = O.label_outcome(_record(), path)
    assert out["outcome_status"] == O.STILL_OPEN
    assert out["expired"] is True
    assert out["target_hit"] is False and out["stop_hit"] is False
    assert out["outcome_r"] is None  # no fabricated number for an undetermined outcome


def test_max_bars_limits_how_far_the_replay_looks_without_changing_the_setup_facts():
    path = _bars([(101, 99.5, 100.5)] * 3 + [(106.5, 105, 106)])  # target only touched on bar 4
    limited = O.label_outcome(_record(), path, max_bars=3)
    full = O.label_outcome(_record(), path, max_bars=None)
    assert limited["outcome_status"] == O.STILL_OPEN
    assert full["outcome_status"] == O.TARGET_HIT


# --- Determinism and repeatability ------------------------------------------------------------------

def test_labeling_the_same_record_and_path_twice_is_identical():
    path = _bars([(101, 99.5, 100.5), (103, 100, 102), (106.5, 105, 106)])
    rec = _record()
    assert O.label_outcome(rec, path) == O.label_outcome(rec, path)


def test_labeling_never_mutates_the_input_record():
    rec = _record()
    before = dict(rec)
    O.label_outcome(rec, _bars([(101, 99.5, 100.5)]))
    assert rec == before
