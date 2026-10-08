"""V2 discovery: hypothesis registration, baselines, bootstrap, selection, test gating."""
import numpy as np
import pandas as pd

from backtest.research import discovery_v2 as dv
from backtest.research.v2_features import SEQ_TYPES, TRIGGER_DIRECTION


def test_hypotheses_are_registered_as_sequence_by_context():
    hyps = dv.build_hypotheses()
    assert len(hyps) == len(SEQ_TYPES) * len(dv.CONTEXTS) == 32
    assert len({h.name for h in hyps}) == 32
    assert all(h.direction == TRIGGER_DIRECTION[h.sequence] for h in hyps)


def _toy(n=400, seed=1):
    rng = np.random.default_rng(seed)
    idx = np.arange(300, 300 + n)
    df = pd.DataFrame({
        "f_index": idx,
        "f_session": rng.choice(["ASIAN", "LONDON", "NY", "OFF"], size=n),
        "f_h1_dir": rng.choice([1, -1], size=n),
        "f_dist_pdl_atr": rng.uniform(-2, 2, n), "f_dist_h1_sl_atr": rng.uniform(-2, 2, n),
        "f_dist_h4_sl_atr": rng.uniform(-2, 2, n), "f_dist_pdh_atr": rng.uniform(-2, 2, n),
        "f_dist_h1_sh_atr": rng.uniform(-2, 2, n), "f_dist_h4_sh_atr": rng.uniform(-2, 2, n),
    })
    for seq in SEQ_TYPES:
        df[f"trig_{seq}"] = (rng.uniform(size=n) < 0.2).astype(int)
    for key in ("buy", "sell"):
        df[f"y_{key}_exp_2r"] = rng.choice([2.0, -1.0, 0.0], size=n)
        df[f"y_{key}_fwd_ret_48"] = rng.normal(0, 1, n)
        df[f"y_{key}_mfe_r"] = rng.uniform(0, 3, n)
        df[f"y_{key}_mae_r"] = rng.uniform(0, 3, n)
        for k in (1, 2, 3):
            df[f"y_{key}_hit_{k}r"] = rng.choice(["win", "loss", "timeout"], size=n)
    return df


def test_context_masks_respect_trade_direction():
    df = _toy()
    h_al = next(h for h in dv.build_hypotheses() if h.sequence == "LOW_R1" and h.context == "h1_aligned")
    m = dv._context_mask(df, h_al)
    assert (df.loc[m, "f_h1_dir"] == 1).all()  # BUY trade, aligned means H1 bullish
    h_ag = next(h for h in dv.build_hypotheses() if h.sequence == "LOW_R1" and h.context == "h1_against")
    assert (df.loc[dv._context_mask(df, h_ag), "f_h1_dir"] == -1).all()


def test_baseline_is_matched_by_session_and_direction():
    df = _toy()
    base = dv.baseline_map(df, "BUY")
    expected = df.groupby("f_session")["y_buy_exp_2r"].mean().to_dict()
    for s, v in expected.items():
        assert abs(base[s] - v) < 1e-12


def test_bootstrap_interval_is_reproducible_and_brackets_the_mean():
    x = np.random.default_rng(0).normal(0.5, 1, 300)
    lo1, hi1 = dv._bootstrap_ci(x)
    lo2, hi2 = dv._bootstrap_ci(x)
    assert (lo1, hi1) == (lo2, hi2)
    assert lo1 < x.mean() < hi1


def test_effect_is_expectancy_minus_matched_baseline():
    df = _toy()
    h = next(h for h in dv.build_hypotheses() if h.sequence == "LOW_R1" and h.context == "none")
    sub = df[dv._context_mask(df, h)]
    m = dv.metrics(sub, h, df)
    assert "effect_2r" in m and m["n"] == len(sub.dropna(subset=["y_buy_exp_2r"]))
    assert abs(m["effect_2r_net_of_cost"] - (m["effect_2r"] - 0.10)) < 1e-9


def test_test_set_is_evaluated_only_for_candidates_that_pass_discovery_and_validation(monkeypatch):
    df = _toy(n=600)
    calls = []
    real = dv.metrics

    def spy(sub, h, split_df):
        if sub is not None and len(sub) and (sub["f_index"] >= dv.TEST[0]).all():
            calls.append(h.name)
        return real(sub, h, split_df)

    monkeypatch.setattr(dv, "metrics", spy)
    monkeypatch.setattr(dv, "DISCOVERY", (300, 400))
    monkeypatch.setattr(dv, "VALIDATION", (400, 500))
    monkeypatch.setattr(dv, "TEST", (500, 10**9))
    monkeypatch.setattr(dv, "MIN_N", 5)
    result = dv.run(df)
    eligible = [r["d"]["hypothesis"] for r in result["rows"] if r["eligible_for_test"]]
    assert set(calls) <= set(eligible)
    for r in result["rows"]:
        if not r["eligible_for_test"]:
            assert r["test"] is None


def test_selection_rejects_small_samples():
    df = _toy(n=200)
    result = dv.run(df)  # default MIN_N=100 exceeds the toy samples
    assert not any(r["discovery_pass"] for r in result["rows"])
