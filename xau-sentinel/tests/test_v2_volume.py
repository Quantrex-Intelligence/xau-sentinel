"""Analysis V2 increment 3: tick-volume features. Descriptive only, no lookahead."""
import numpy as np
import pandas as pd
import pytest

from analysis.v2.volume import (
    BASELINE_BARS, relative_volume, volume_at, volume_percentile, volume_state,
)


def _frame(volumes):
    return pd.DataFrame({"volume": np.asarray(volumes, dtype=float)})


def test_relative_volume_uses_prior_bars_only():
    vol = [100.0] * BASELINE_BARS + [500.0]
    rel = relative_volume(pd.Series(vol))
    # The spike does not inflate its own baseline: 500 / mean(prior 100s) = 5.
    assert rel.iloc[-1] == pytest.approx(5.0)


def test_relative_volume_is_nan_before_enough_history():
    rel = relative_volume(pd.Series([100.0] * (BASELINE_BARS - 1)))
    assert rel.isna().all()


def test_volume_percentile_is_trailing_and_inclusive():
    vol = pd.Series(np.arange(1, 101, dtype=float))  # 100 bars, rising
    pct = volume_percentile(vol, window=100)
    assert pct.iloc[-1] == pytest.approx(100.0)
    assert np.isnan(pct.iloc[98])


def test_volume_state_labels():
    assert volume_state(float("nan")) == "UNKNOWN"
    assert volume_state(2.0) == "EXPANSION"
    assert volume_state(0.5) == "CONTRACTION"
    assert volume_state(1.0) == "NORMAL"


def test_past_values_do_not_change_when_future_bars_arrive():
    rng = np.random.default_rng(11)
    vols = rng.integers(100, 1000, size=150).astype(float)
    short = _frame(vols[:120])
    long = _frame(vols)
    idx = [60, 90, 119]
    a = volume_at(short, idx)
    b = volume_at(long, idx)
    for i in idx:
        assert a[i]["relative_volume"] == pytest.approx(b[i]["relative_volume"], nan_ok=True)
        assert a[i]["volume_percentile"] == pytest.approx(b[i]["volume_percentile"], nan_ok=True)
        assert a[i]["mean_relative_3bar"] == pytest.approx(b[i]["mean_relative_3bar"], nan_ok=True)


def test_volume_at_skips_out_of_range_indices():
    out = volume_at(_frame(np.full(30, 100.0)), [-1, 5, 30, 99])
    assert set(out) == {5}


def test_output_has_no_direction_field():
    out = volume_at(_frame(np.full(130, 100.0)), [120])[120]
    assert set(out) == {"relative_volume", "volume_percentile", "state", "mean_relative_3bar"}
    assert "direction" not in out and "side" not in out


def test_displacement_style_spike_is_labelled_expansion():
    vols = [100.0] * 25 + [400.0]
    out = volume_at(_frame(vols), [25])[25]
    assert out["state"] == "EXPANSION"
    assert out["relative_volume"] == pytest.approx(4.0)
