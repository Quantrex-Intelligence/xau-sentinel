"""Dependency-free statistics helpers for the Entry Model V2 OOS pipeline -- a durable, repo-housed
copy of the same functions used throughout the in-sample research (no scipy/sklearn/statsmodels
available in this project's venv). Deliberately simple: Wilson score intervals and a percentile
bootstrap, nothing more.
"""
import numpy as np

MIN_N = 10  # minimum sample size before a group is interpreted, matching every prior research stage
RNG = np.random.default_rng(42)


def wilson_ci(successes: int, n: int, z: float = 1.96):
    if n == 0:
        return (None, None)
    p = successes / n
    denom = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return (round((centre - margin) / denom, 4), round((centre + margin) / denom, 4))


def bootstrap_ci(values, stat_fn=np.mean, n_boot: int = 2000, alpha: float = 0.05):
    values = np.asarray(values, dtype=float)
    if len(values) == 0:
        return (None, None)
    if len(values) == 1:
        v = float(stat_fn(values))
        return (v, v)
    n = len(values)
    boots = np.empty(n_boot)
    for i in range(n_boot):
        boots[i] = stat_fn(values[RNG.integers(0, n, size=n)])
    lo, hi = np.percentile(boots, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return (round(float(lo), 4), round(float(hi), 4))


def summarize_r(values, label: str = "") -> dict:
    values = [float(v) for v in values if v is not None]
    n = len(values)
    out = {"label": label, "n": n}
    if n == 0:
        out["insufficient"] = True
        return out
    arr = np.asarray(values)
    wins = int((arr > 0).sum())
    out["win_rate"] = round(wins / n, 4)
    out["win_rate_ci95"] = wilson_ci(wins, n)
    out["mean_r"] = round(float(arr.mean()), 4)
    out["mean_r_ci95"] = bootstrap_ci(arr, np.mean)
    out["median_r"] = round(float(np.median(arr)), 4)
    out["std_r"] = round(float(arr.std(ddof=1)) if n > 1 else 0.0, 4)
    gains = arr[arr > 0].sum()
    losses = -arr[arr < 0].sum()
    out["profit_factor"] = None if losses == 0 else round(float(gains / losses), 4)
    wins_arr, losses_arr = arr[arr > 0], arr[arr <= 0]
    out["mean_winning_r"] = round(float(wins_arr.mean()), 4) if len(wins_arr) else None
    out["mean_losing_r"] = round(float(losses_arr.mean()), 4) if len(losses_arr) else None
    equity = np.cumsum(arr)
    running_max = np.maximum.accumulate(equity)
    out["max_drawdown_r"] = round(float((running_max - equity).max()), 4) if n else 0.0
    out["insufficient"] = n < MIN_N
    return out


def compare_groups(a, b, label_a="A", label_b="B") -> dict:
    a = np.asarray([float(v) for v in a if v is not None])
    b = np.asarray([float(v) for v in b if v is not None])
    out = {"n_a": len(a), "n_b": len(b), "label_a": label_a, "label_b": label_b}
    insufficient = len(a) < MIN_N or len(b) < MIN_N
    out["insufficient"] = insufficient
    if len(a) == 0 or len(b) == 0:
        return out
    out["mean_a"], out["mean_b"] = round(float(a.mean()), 4), round(float(b.mean()), 4)
    out["diff_mean_r"] = round(float(a.mean() - b.mean()), 4)
    win_a = float((a > 0).mean())
    win_b = float((b > 0).mean())
    out["diff_win_rate"] = round(win_a - win_b, 4)
    gains_a, losses_a = a[a > 0].sum(), -a[a < 0].sum()
    gains_b, losses_b = b[b > 0].sum(), -b[b < 0].sum()
    pf_a = None if losses_a == 0 else float(gains_a / losses_a)
    pf_b = None if losses_b == 0 else float(gains_b / losses_b)
    out["diff_profit_factor"] = None if (pf_a is None or pf_b is None) else round(pf_a - pf_b, 4)
    if not insufficient:
        boots = np.empty(2000)
        for i in range(2000):
            sa = a[RNG.integers(0, len(a), len(a))]
            sb = b[RNG.integers(0, len(b), len(b))]
            boots[i] = sa.mean() - sb.mean()
        lo, hi = np.percentile(boots, [2.5, 97.5])
        out["diff_mean_r_ci95"] = (round(float(lo), 4), round(float(hi), 4))
    return out
