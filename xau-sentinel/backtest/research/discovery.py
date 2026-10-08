"""Strategy Discovery Lab: pre-registered contextual hypotheses.

The hypothesis list below is FIXED before any result is looked at. It is not
searched exhaustively. Each hypothesis is a condition over known-at-time-t
features plus a direction (BUY or SELL). Outcomes are y_* columns only.

Splits (by bar index, chronological):
    discovery   [300, 17000)   used to rank hypotheses
    validation  [17000, 23382) used to confirm discovery candidates
    test        [23382, end)   read ONCE, only for candidates that pass
                               discovery and validation

Selection rule (fixed in advance):
    discovery: |t| >= Z_DISCOVERY (Bonferroni over the hypothesis count, two-sided)
    validation: same sign, |t| >= 1.96, n >= MIN_N in both
"""
from dataclasses import dataclass
from math import sqrt
from typing import Callable, List

import numpy as np
import pandas as pd
from statistics import NormalDist

DISCOVERY = (300, 17000)
VALIDATION = (17000, 23382)
TEST = (23382, 10**9)
MIN_N = 100
COST_ATR = 0.10  # round-trip cost sensitivity, in ATR units (spread is small vs ATR on M5 gold)


@dataclass(frozen=True)
class Hypothesis:
    name: str
    family: str
    direction: str  # BUY or SELL
    condition: Callable[[pd.DataFrame], pd.Series]


def _near(col: str, side: str, tol: float = 0.5):
    if side == "above":
        return lambda d: (d[col] > 0) & (d[col] <= tol)
    return lambda d: (d[col] < 0) & (d[col] >= -tol)


def build_hypotheses() -> List[Hypothesis]:
    hyps: List[Hypothesis] = []

    # A. Higher-timeframe direction + one event on the entry timeframe.
    events = {
        "sweep_low_recent": lambda d: d["f_sweep_low_recent"] == 1,
        "sweep_high_recent": lambda d: d["f_sweep_high_recent"] == 1,
        "mss_M5_bull": lambda d: d["f_mss_M5"] == 1,
        "mss_M5_bear": lambda d: d["f_mss_M5"] == -1,
        "bos_M5_bull": lambda d: d["f_bos_M5"] == 1,
        "bos_M5_bear": lambda d: d["f_bos_M5"] == -1,
        "disp_bull": lambda d: d["f_disp"] == 1,
        "disp_bear": lambda d: d["f_disp"] == -1,
    }
    for h1 in (1, -1):
        for ev_name, ev in events.items():
            for direction in ("BUY", "SELL"):
                hyps.append(Hypothesis(
                    f"H1dir{h1:+d} & {ev_name} -> {direction}", "A_structure_event", direction,
                    (lambda h1, ev: lambda d: (d["f_h1_dir"] == h1) & ev(d))(h1, ev)))

    # B. Location: price within 0.5 ATR of a key level on one side, in each direction.
    locations = {
        "PDH": ("f_dist_pdh_atr", "above"), "PDL": ("f_dist_pdl_atr", "below"),
        "H1 swing high": ("f_dist_h1_sh_atr", "above"), "H1 swing low": ("f_dist_h1_sl_atr", "below"),
        "H4 swing high": ("f_dist_h4_sh_atr", "above"), "H4 swing low": ("f_dist_h4_sl_atr", "below"),
    }
    for loc, (col, side) in locations.items():
        for direction in ("BUY", "SELL"):
            hyps.append(Hypothesis(f"near {loc} -> {direction}", "B_location", direction, _near(col, side)))

    # C. Sweep at a matching location: sweep of support -> BUY; sweep of resistance -> SELL.
    support = [("f_dist_pdl_atr", "below"), ("f_dist_h1_sl_atr", "below"), ("f_dist_h4_sl_atr", "below")]
    resistance = [("f_dist_pdh_atr", "above"), ("f_dist_h1_sh_atr", "above"), ("f_dist_h4_sh_atr", "above")]
    for col, side in support:
        hyps.append(Hypothesis(f"sweep_low & near {col} -> BUY", "C_sweep_location", "BUY",
                               (lambda c, s: lambda d: (d["f_sweep_low_recent"] == 1) & _near(c, s)(d))(col, side)))
    for col, side in resistance:
        hyps.append(Hypothesis(f"sweep_high & near {col} -> SELL", "C_sweep_location", "SELL",
                               (lambda c, s: lambda d: (d["f_sweep_high_recent"] == 1) & _near(c, s)(d))(col, side)))

    # D. Session interactions with the two sweep directions.
    for session in ("ASIAN", "LONDON", "NY", "OFF"):
        hyps.append(Hypothesis(f"{session} & sweep_low -> BUY", "D_session", "BUY",
                               (lambda s: lambda d: (d["f_session"] == s) & (d["f_sweep_low_recent"] == 1))(session)))
        hyps.append(Hypothesis(f"{session} & sweep_high -> SELL", "D_session", "SELL",
                               (lambda s: lambda d: (d["f_session"] == s) & (d["f_sweep_high_recent"] == 1))(session)))

    # E. Regime interactions with H1 direction.
    for regime in ("TRENDING UP", "TRENDING DOWN", "RANGING", "HIGH VOLATILITY"):
        for h1 in (1, -1):
            for direction in ("BUY", "SELL"):
                hyps.append(Hypothesis(f"{regime} & H1dir{h1:+d} -> {direction}", "E_regime", direction,
                                       (lambda r, h1: lambda d: (d["f_regime"] == r) & (d["f_h1_dir"] == h1))(regime, h1)))
    return hyps


def _stats(sub: pd.DataFrame, direction: str) -> dict:
    sign = 1 if direction == "BUY" else -1
    ret = (sub["y_fwd_ret_48_atr"] * sign).dropna()
    n = len(ret)
    if n < 2:
        return {"n": n, "mean_ret_atr": np.nan, "t": np.nan, "win_rate": np.nan, "expectancy_pm1": np.nan}
    mean = float(ret.mean())
    sd = float(ret.std(ddof=1))
    t = mean / (sd / sqrt(n)) if sd > 0 else np.nan
    labels = sub["y_label_buy_pm1"] if direction == "BUY" else sub["y_label_sell_pm1"]
    labels = labels.dropna()
    wins = int((labels == "win").sum())
    losses = int((labels == "loss").sum())
    decided = wins + losses
    return {
        "n": n,
        "mean_ret_atr": round(mean, 4),
        "t": round(t, 2) if t == t else np.nan,
        "win_rate": round(wins / decided, 3) if decided else np.nan,
        "expectancy_pm1": round((wins - losses) / decided, 3) if decided else np.nan,
        "mfe_atr": round(float((sub["y_mfe_up_atr"] if sign > 0 else sub["y_mfe_down_atr"]).mean()), 3),
        "mae_atr": round(float((sub["y_mae_up_atr"] if sign > 0 else sub["y_mae_down_atr"]).mean()), 3),
    }


def split(df: pd.DataFrame, bounds) -> pd.DataFrame:
    return df[(df["f_index"] >= bounds[0]) & (df["f_index"] < bounds[1])]


def evaluate(df: pd.DataFrame, hyps: List[Hypothesis]) -> pd.DataFrame:
    rows = []
    for h in hyps:
        for name, bounds in (("discovery", DISCOVERY), ("validation", VALIDATION)):
            sub = split(df, bounds)
            mask = h.condition(sub).fillna(False)
            rows.append({"hypothesis": h.name, "family": h.family, "direction": h.direction,
                         "split": name, **_stats(sub[mask], h.direction)})
    return pd.DataFrame(rows)


def select(results: pd.DataFrame, n_tests: int) -> pd.DataFrame:
    """Apply the pre-registered selection rule. Bonferroni two-sided threshold."""
    z_disc = NormalDist().inv_cdf(1 - 0.05 / (2 * n_tests))
    disc = results[results["split"] == "discovery"].set_index("hypothesis")
    val = results[results["split"] == "validation"].set_index("hypothesis")
    rows = []
    for name in disc.index:
        d, v = disc.loc[name], val.loc[name]
        passes_disc = (d["n"] >= MIN_N) and (abs(d["t"]) >= z_disc if d["t"] == d["t"] else False)
        same_sign = (d["mean_ret_atr"] > 0) == (v["mean_ret_atr"] > 0)
        passes_val = (v["n"] >= MIN_N) and same_sign and (abs(v["t"]) >= 1.96 if v["t"] == v["t"] else False)
        rows.append({"hypothesis": name, "family": d["family"], "direction": d["direction"],
                     "disc_n": d["n"], "disc_t": d["t"], "disc_mean_atr": d["mean_ret_atr"],
                     "val_n": v["n"], "val_t": v["t"], "val_mean_atr": v["mean_ret_atr"],
                     "passes_discovery": passes_disc, "passes_validation": passes_disc and passes_val,
                     "z_threshold": round(z_disc, 2)})
    return pd.DataFrame(rows)
