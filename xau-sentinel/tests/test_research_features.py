"""Research feature dataset: no f_* feature may depend on bars after its own bar."""
import pandas as pd

from backtest.research.features import build_rows


def _mock_frames():
    from mt5.market_data import _mock_candles
    return {"M5": _mock_candles("M5", 700), "M15": _mock_candles("M15", 320),
            "H1": _mock_candles("H1", 320), "H4": _mock_candles("H4", 320)}


def test_features_never_depend_on_future_bars():
    frames = _mock_frames()
    m5 = frames["M5"].reset_index(drop=True)
    cut = 330
    cutoff = m5["time"].iloc[cut - 1]
    full = build_rows(frames, 300, cut)
    truncated = {tf: df[df["time"] <= cutoff].reset_index(drop=True) for tf, df in frames.items()}
    partial = build_rows(truncated, 300, cut)

    full_by_index = {r["f_index"]: r for r in full if r["f_index"] < cut}
    partial_by_index = {r["f_index"]: r for r in partial if r["f_index"] < cut}
    assert set(full_by_index) == set(partial_by_index)
    assert full_by_index, "no rows compared; the test would be vacuous"
    for idx, row in full_by_index.items():
        for key, value in row.items():
            if not key.startswith("f_"):
                continue
            other = partial_by_index[idx][key]
            if isinstance(value, float) and pd.isna(value):
                assert pd.isna(other), (idx, key)
            else:
                assert other == value, (idx, key, value, other)


def test_outcome_columns_are_not_features():
    frames = _mock_frames()
    rows = build_rows(frames, 300, 320)
    assert rows
    assert all(k.startswith(("f_", "y_")) or k == "f_index" for k in rows[0])
    assert all(not k.startswith("f_y") for k in rows[0])
