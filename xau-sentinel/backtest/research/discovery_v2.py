"""Strategy Discovery Lab V2: preregistered sequence x context hypotheses.

Hypotheses are fixed in code before any result is viewed:
    8 sequence triggers (backtest/research/v2_features.py) x 4 contexts = 32.

Contexts (evaluated at the trigger bar):
    none           every trigger of that sequence
    h1_aligned     H1 direction agrees with the trade direction
    h1_against     H1 direction opposes the trade direction
    key_location   the sweep happened at a key level on its side
                   (LOW side: PDL / H1 swing low / H4 swing low within 0.5 ATR below;
                    HIGH side: PDH / H1 swing high / H4 swing high within 0.5 ATR above)

Splits (chronological bar index, same as V1):
    discovery  [300, 17000)   validation [17000, 23382)   test [23382, end)

Metrics per split: n, mean and median forward return (signed, 48 bars), P(+1R/+2R/+3R
before -1R) with Wilson intervals, expectancy in R (2R target) with bootstrap interval,
MFE/MAE, and EFFECT = expectancy minus the matched baseline (same direction, same
session, same split, all bars). Cost sensitivity subtracts COST_R.

Selection (fixed):
    discovery: n >= MIN_N and |t(effect)| >= Bonferroni z over the hypothesis count
    validation: same effect sign, n >= MIN_N, |t| >= 1.96
    walk-forward: same sign in at least 2 of 3 discovery blocks
    test: evaluated ONLY for candidates passing discovery and validation
"""
from dataclasses import dataclass
from math import sqrt
from statistics import NormalDist
from typing import Callable, Dict, List

import numpy as np
import pandas as pd

from backtest.research.outcomes_r import COST_R, wilson
from backtest.research.v2_features import SEQ_TYPES, TRIGGER_DIRECTION

DISCOVERY = (300, 17000)
VALIDATION = (17000, 23382)
TEST = (23382, 10**9)
MIN_N = 100
BOOT_N = 2000
BOOT_SEED = 7
CONTEXTS = ("none", "h1_aligned", "h1_against", "key_location")
KEY_TOL = 0.5


@dataclass(frozen=True)
class Hypothesis:
    name: str
    sequence: str
    context: str
    direction: str


def build_hypotheses() -> List[Hypothesis]:
    return [Hypothesis(f"{seq} | {ctx}", seq, ctx, TRIGGER_DIRECTION[seq])
            for seq in SEQ_TYPES for ctx in CONTEXTS]


def _context_mask(df: pd.DataFrame, h: Hypothesis) -> pd.Series:
    base = df[f"trig_{h.sequence}"] == 1
    if h.context == "none":
        return base
    sign = 1 if h.direction == "BUY" else -1
    if h.context == "h1_aligned":
        return base & (df["f_h1_dir"] == sign)
    if h.context == "h1_against":
        return base & (df["f_h1_dir"] == -sign)
    if h.context == "key_location":
        if h.sequence.startswith("LOW"):
            cols = ["f_dist_pdl_atr", "f_dist_h1_sl_atr", "f_dist_h4_sl_atr"]
            near = df[cols].apply(lambda s: (s < 0) & (s >= -KEY_TOL)).any(axis=1)
        else:
            cols = ["f_dist_pdh_atr", "f_dist_h1_sh_atr", "f_dist_h4_sh_atr"]
            near = df[cols].apply(lambda s: (s > 0) & (s <= KEY_TOL)).any(axis=1)
        return base & near
    raise ValueError(h.context)


def _split(df: pd.DataFrame, bounds) -> pd.DataFrame:
    return df[(df["f_index"] >= bounds[0]) & (df["f_index"] < bounds[1])]


def baseline_map(split_df: pd.DataFrame, direction: str) -> Dict[str, float]:
    """Mean 2R expectancy of every bar in the split, per session, same direction."""
    key = direction.lower()
    col = f"y_{key}_exp_2r"
    sub = split_df.dropna(subset=[col])
    return sub.groupby("f_session")[col].mean().to_dict()


def _bootstrap_ci(values: np.ndarray, seed: int = BOOT_SEED, n_boot: int = BOOT_N):
    if len(values) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(values), size=(n_boot, len(values)))
    means = values[idx].mean(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def metrics(sub: pd.DataFrame, h: Hypothesis, split_df: pd.DataFrame) -> dict:
    key = h.direction.lower()
    sub = sub.dropna(subset=[f"y_{key}_exp_2r"])
    n = len(sub)
    base = baseline_map(split_df, h.direction)
    out = {"hypothesis": h.name, "sequence": h.sequence, "context": h.context,
           "direction": h.direction, "n": n}
    if n == 0:
        return out

    exp2 = sub[f"y_{key}_exp_2r"].to_numpy(dtype=float)
    matched = np.array([base.get(s, np.nan) for s in sub["f_session"]], dtype=float)
    diff = exp2 - matched
    diff = diff[~np.isnan(diff)]
    eff = float(diff.mean()) if len(diff) else float("nan")
    sd = float(diff.std(ddof=1)) if len(diff) > 1 else float("nan")
    t = eff / (sd / sqrt(len(diff))) if sd and sd > 0 else float("nan")

    fwd = sub[f"y_{key}_fwd_ret_48"].dropna()
    out["mean_fwd_atr"] = round(float(fwd.mean()), 4) if len(fwd) else None
    out["median_fwd_atr"] = round(float(fwd.median()), 4) if len(fwd) else None
    for k in (1, 2, 3):
        outcomes = sub[f"y_{key}_hit_{k}r"].dropna()
        wins = int((outcomes == "win").sum())
        losses = int((outcomes == "loss").sum())
        decided = wins + losses
        out[f"p_plus{k}r"] = round(wins / decided, 3) if decided else None
        lo, hi = wilson(wins, decided)
        out[f"p_plus{k}r_ci"] = (round(lo, 3), round(hi, 3)) if decided else None
        out[f"decided_{k}r"] = decided
    out["expectancy_2r"] = round(float(exp2[~np.isnan(exp2)].mean()), 4)
    lo, hi = _bootstrap_ci(exp2[~np.isnan(exp2)])
    out["expectancy_2r_ci"] = (round(lo, 3), round(hi, 3))
    out["mfe_r"] = round(float(sub[f"y_{key}_mfe_r"].mean()), 3)
    out["mae_r"] = round(float(sub[f"y_{key}_mae_r"].mean()), 3)
    out["baseline_expectancy_2r"] = round(float(np.nanmean(matched)), 4)
    out["effect_2r"] = round(eff, 4)
    out["effect_t"] = round(t, 2) if t == t else float("nan")
    out["effect_2r_net_of_cost"] = round(eff - COST_R, 4)
    return out


def _z_bonferroni(n_tests: int) -> float:
    return NormalDist().inv_cdf(1 - 0.05 / (2 * n_tests))


def walk_forward_signs(df_disc: pd.DataFrame, h: Hypothesis) -> List[float]:
    """Effect sign in each of three equal discovery blocks (chronological)."""
    lo, hi = DISCOVERY
    edges = np.linspace(lo, hi, 4)
    signs = []
    for a, b in zip(edges[:-1], edges[1:]):
        block = df_disc[(df_disc["f_index"] >= a) & (df_disc["f_index"] < b)]
        m = metrics(block[_context_mask(block, h).reindex(block.index, fill_value=False)], h, block)
        signs.append(float(np.sign(m.get("effect_2r", 0) or 0)))
    return signs


def run(df: pd.DataFrame) -> dict:
    hyps = build_hypotheses()
    z = _z_bonferroni(len(hyps))
    disc_df, val_df = _split(df, DISCOVERY), _split(df, VALIDATION)
    rows = []
    for h in hyps:
        d = metrics(disc_df[_context_mask(disc_df, h)], h, disc_df)
        v = metrics(val_df[_context_mask(val_df, h)], h, val_df)
        signs = walk_forward_signs(df, h)
        d_t, v_t = _num(d.get("effect_t")), _num(v.get("effect_t"))
        d_eff, v_eff = _num(d.get("effect_2r")), _num(v.get("effect_2r"))
        d_pass = d["n"] >= MIN_N and not np.isnan(d_t) and abs(d_t) >= z
        v_pass = (v["n"] >= MIN_N and not np.isnan(v_t) and not np.isnan(d_eff) and
                  np.sign(v_eff) == np.sign(d_eff) and abs(v_t) >= 1.96)
        wf_ok = (not np.isnan(d_eff)) and sum(1 for s in signs if s == np.sign(d_eff)) >= 2
        rows.append({"d": d, "v": v, "walk_forward_signs": signs, "discovery_pass": bool(d_pass),
                     "validation_pass": bool(d_pass and v_pass), "walk_forward_ok": bool(wf_ok),
                     "eligible_for_test": bool(d_pass and v_pass and wf_ok)})

    test_df = _split(df, TEST)
    for r in rows:
        if r["eligible_for_test"]:
            h = next(x for x in hyps if x.name == r["d"]["hypothesis"])
            r["test"] = metrics(test_df[_context_mask(test_df, h)], h, test_df)
        else:
            r["test"] = None
    return {"rows": rows, "z": z, "n_hypotheses": len(hyps)}


def _num(x) -> float:
    return float("nan") if x is None else float(x)
