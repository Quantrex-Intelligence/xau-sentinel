"""CLI: python -m backtest.run [--months 6] [--oos-days 60] [--stride 1] [--horizon 48] [--k 1.0]

Baseline benchmark over real MT5 XAUUSD M5 history. Replays the existing engine
in parallel chunks, splits in-sample / out-of-sample, and writes the full report
to backtest/results/. Methodology: docs/backtest/METHODOLOGY.md.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import List

import pandas as pd

from analysis.structure import compute_atr
from backtest.data import load_history
from backtest.replay import SIGNAL_TYPES, WARMUP, Signal, replay
from backtest.report import base_rate, breakdown, non_overlap_row, non_overlapping, summarize, wilson

TFS = ("M5", "M15", "H1", "H4")
RESULTS_DIR = Path(__file__).parent / "results"


def _chunk(args) -> List[Signal]:
    frames, start, end, stride, horizon, k = args
    sigs = replay(frames, start=max(0, start - WARMUP), end=end, stride=stride, horizon=horizon, k=k)
    return [s for s in sigs if s.index >= start]


def run_window(frames: dict, start: int, end: int, stride: int, horizon: int, k: float,
               workers: int) -> List[Signal]:
    n = end - start
    step = max(1, n // (workers * 4))
    jobs = [(frames, s, min(s + step, end), stride, horizon, k) for s in range(start, end, step)]
    with ProcessPoolExecutor(max_workers=workers) as pool:
        out: List[Signal] = []
        for part in pool.map(_chunk, jobs):
            out.extend(part)
    return sorted(out, key=lambda s: s.index)


def _stable(is_row: pd.Series, oos_row: pd.Series) -> str:
    """Only call an edge stable when both windows have enough decided signals,
    lift has the same sign, and each window's Wilson interval excludes the
    baseline on the same side."""
    if pd.isna(is_row["win_rate"]) or pd.isna(oos_row["win_rate"]):
        return "insufficient data"
    if is_row["decided"] < 30 or oos_row["decided"] < 30:
        return "insufficient data (<30 decided)"
    same_sign = (is_row["lift_vs_base"] > 0) == (oos_row["lift_vs_base"] > 0)
    is_above = is_row["ci95_low"] > is_row["base"]
    oos_above = oos_row["ci95_low"] > oos_row["base"]
    is_below = is_row["ci95_high"] < is_row["base"]
    oos_below = oos_row["ci95_high"] < oos_row["base"]
    if same_sign and ((is_above and oos_above) or (is_below and oos_below)):
        return "STABLE edge"
    if same_sign:
        return "same direction, not significant in both windows (likely noise)"
    return "UNSTABLE (flips between IS and OOS, noise)"


def stability_line(signal_type: str, is_sig: List[Signal], oos_sig: List[Signal],
                   is_base: float, oos_base: float, horizon: int) -> str:
    """One STABILITY line, built from that type's own IS and OOS non-overlapping rows."""
    is_r = non_overlap_row(is_sig, is_base, horizon, signal_type)
    oos_r = non_overlap_row(oos_sig, oos_base, horizon, signal_type)
    is_r["base"], oos_r["base"] = is_base, oos_base
    return (f"{signal_type}: {_stable(pd.Series(is_r), pd.Series(oos_r))}  "
            f"(IS {is_r['win_rate']}, OOS {oos_r['win_rate']})")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--months", type=int, default=6)
    p.add_argument("--stride", type=int, default=1)
    p.add_argument("--horizon", type=int, default=48)
    p.add_argument("--k", type=float, default=1.0)
    p.add_argument("--oos-days", type=int, default=60)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--refresh", action="store_true")
    args = p.parse_args()

    frames = {tf: load_history(tf, args.months, refresh=args.refresh).reset_index(drop=True) for tf in TFS}
    m5 = frames["M5"]
    atr = compute_atr(m5)
    cutoff = m5["time"].iloc[-1] - pd.Timedelta(days=args.oos_days)
    split = int(m5.index[m5["time"] >= cutoff][0])

    lines: List[str] = []
    def out(s: str = "") -> None:
        print(s, flush=True)
        lines.append(s)

    out(f"Dataset: {args.months} months {m5['time'].iloc[0]} .. {m5['time'].iloc[-1]} (M5, {len(m5)} bars)")
    out(f"IS: bars 300..{split}   OOS: bars {split}..{len(m5)} (last {args.oos_days} days)")
    out(f"Label: +/-{args.k} ATR(14) within {args.horizon} M5 bars; win rate = wins/(wins+losses)")

    windows = {}
    for label, start, end in (("IN-SAMPLE", 300, split), ("OUT-OF-SAMPLE", split, len(m5))):
        signals = run_window(frames, start, end, args.stride, args.horizon, args.k, args.workers)
        base_wins, base_decided, base = base_rate(m5, atr, range(start, end, args.stride), args.horizon, args.k)
        base_lo, base_hi = wilson(base_wins, base_decided)
        windows[label] = (signals, base, base_lo, base_hi)
        out(f"\n== {label}: bars {start}..{end}  baseline win rate {base:.3f} "
            f"(95% CI {base_lo:.3f}..{base_hi:.3f}, n={base_decided})")
        out(summarize(signals, base, args.horizon).to_string(index=False))

    is_sig, is_base, _, _ = windows["IN-SAMPLE"]
    oos_sig, oos_base, _, _ = windows["OUT-OF-SAMPLE"]
    all_sig = is_sig + oos_sig

    out("\n== STABILITY (non-overlapping signals, IS vs OOS)")
    for t in SIGNAL_TYPES:
        out(stability_line(t, is_sig, oos_sig, is_base, oos_base, args.horizon))

    full_base_wins, full_base_decided, full_base = base_rate(
        m5, atr, range(300, len(m5), args.stride), args.horizon, args.k)
    out(f"\nFull-period baseline win rate {full_base:.3f} (n={full_base_decided})")
    for t in SIGNAL_TYPES:
        sigs = non_overlapping([s for s in all_sig if s.signal_type == t], args.horizon)
        out(f"\n== {t}: breakdowns over 6 months, non-overlapping (n={len(sigs)})")
        for field in ("month", "direction", "session", "regime"):
            out(breakdown(sigs, full_base, field).to_string(index=False))

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / f"baseline_{args.months}m.txt").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
