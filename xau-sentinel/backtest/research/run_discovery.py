"""Run the pre-registered Discovery Lab and write the report.

Test period is evaluated only for candidates that pass discovery AND validation.
"""
from pathlib import Path

import pandas as pd

from backtest.research.discovery import (
    TEST, VALIDATION, DISCOVERY, build_hypotheses, evaluate, select, split, _stats,
)

DATA = Path(__file__).parent / "data" / "features_6m.csv"
RESULTS = Path(__file__).parent / "results"


def baseline(df: pd.DataFrame, bounds) -> dict:
    sub = split(df, bounds)
    return {"buy_mean_atr": round(float(sub["y_fwd_ret_48_atr"].mean()), 4),
            "buy_win_rate": round(float((sub["y_label_buy_pm1"] == "win").sum() /
                                        max(1, ((sub["y_label_buy_pm1"] == "win") |
                                                (sub["y_label_buy_pm1"] == "loss")).sum())), 3),
            "sell_win_rate": round(float((sub["y_label_sell_pm1"] == "win").sum() /
                                         max(1, ((sub["y_label_sell_pm1"] == "win") |
                                                 (sub["y_label_sell_pm1"] == "loss")).sum())), 3),
            "n": len(sub)}


def main() -> None:
    df = pd.read_csv(DATA, parse_dates=["f_time"])
    hyps = build_hypotheses()
    results = evaluate(df, hyps)
    chosen = select(results, n_tests=len(hyps))
    passing = chosen[chosen["passes_validation"]]

    lines = []
    def out(s=""):
        print(s, flush=True)
        lines.append(s)

    out(f"Rows: {len(df)}  discovery {DISCOVERY}  validation {VALIDATION}  test {TEST}")
    out(f"Hypotheses tested (fixed list): {len(hyps)}  Bonferroni z = {chosen['z_threshold'].iloc[0]}")
    out(f"Baseline discovery: {baseline(df, DISCOVERY)}")
    out(f"Baseline validation: {baseline(df, VALIDATION)}")
    out("\n== Discovery + validation, all hypotheses (ranked by discovery t)")
    out(chosen.sort_values("disc_t", key=lambda s: s.abs(), ascending=False).to_string(index=False))

    out(f"\n== Candidates passing discovery AND validation: {len(passing)}")
    test_rows = []
    for _, c in passing.iterrows():
        h = next(x for x in hyps if x.name == c["hypothesis"])
        sub = split(df, TEST)
        mask = h.condition(sub).fillna(False)
        test_rows.append({"hypothesis": c["hypothesis"], "direction": c["direction"],
                          **_stats(sub[mask], c["direction"])})
    if test_rows:
        out(pd.DataFrame(test_rows).to_string(index=False))
    else:
        out("None. No hypothesis cleared both discovery and validation.")

    RESULTS.mkdir(parents=True, exist_ok=True)
    chosen.to_csv(RESULTS / "discovery_validation.csv", index=False)
    (RESULTS / "discovery_report.txt").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
