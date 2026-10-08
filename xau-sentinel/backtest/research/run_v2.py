"""Run Strategy Discovery Lab V2 and write backtest/research/results/discovery_v2_report.txt.

Test-set metrics appear only for candidates that passed discovery, validation and
walk-forward gating. The continuation-vs-reversal table uses discovery and
validation only, so it never reads the test period.
"""
from pathlib import Path

import pandas as pd

from backtest.research import discovery_v2 as dv
from backtest.research.v2_features import SEQ_TYPES, TRIGGER_DIRECTION

DATA = Path(__file__).parent / "data" / "features_v2_6m.csv"
RESULTS = Path(__file__).parent / "results"


def _classify(r: dict) -> str:
    if r["d"]["n"] < dv.MIN_N:
        return "INSUFFICIENT SAMPLE"
    if r["eligible_for_test"]:
        test = r["test"] or {}
        test_ok = test.get("effect_t") is not None and test.get("effect_t") == test.get("effect_t") \
            and (test.get("effect_2r", 0) > 0) == (r["d"]["effect_2r"] > 0) and abs(test.get("effect_t", 0)) >= 1.96
        if test_ok and test.get("effect_2r_net_of_cost", 0) > 0:
            return "ROBUST CANDIDATE"
        return "PROMISING" if test.get("effect_2r", 0) * r["d"]["effect_2r"] > 0 else "REJECTED (test reversed)"
    if r["discovery_pass"] and not r["validation_pass"]:
        return "DISCOVERY ONLY (failed validation)"
    if r["discovery_pass"]:
        return "DISCOVERY ONLY (failed walk-forward)" if not r["walk_forward_ok"] else "DISCOVERY ONLY"
    return "REJECTED"


def _continuation_reversal(df: pd.DataFrame) -> pd.DataFrame:
    disc = df[(df["f_index"] >= dv.DISCOVERY[0]) & (df["f_index"] < dv.VALIDATION[1])]
    rows = []
    for side in ("LOW", "HIGH"):
        for ctx in dv.CONTEXTS:
            for family, members in (("reversal", (f"{side}_R1", f"{side}_R2")),
                                    ("continuation", (f"{side}_C1", f"{side}_C2"))):
                for seq in members:
                    h = dv.Hypothesis(seq, seq, ctx, TRIGGER_DIRECTION[seq])
                    m = dv.metrics(disc[dv._context_mask(disc, h)], h, disc)
                    rows.append({"side": side, "context": ctx, "family": family, "sequence": seq,
                                 "n": m["n"], "p_plus2r": m.get("p_plus2r"),
                                 "expectancy_2r": m.get("expectancy_2r"),
                                 "effect_2r": m.get("effect_2r")})
    return pd.DataFrame(rows)


def main() -> None:
    df = pd.read_csv(DATA)
    result = dv.run(df)
    rows = result["rows"]
    lines = []

    def out(s: str = "") -> None:
        print(s, flush=True)
        lines.append(s)

    out("== 1. OBJECTIVE")
    out("Test whether the predictive meaning of sequences depends on context and location: P(outcome | sequence + context).")
    out("\n== 2. DATASET AND SPLIT")
    out(f"Rows: {len(df)}  discovery {dv.DISCOVERY}  validation {dv.VALIDATION}  test {dv.TEST} (gated).")
    out("Session windows: configured UTC hours (config.py). R unit: 1 ATR(14), stop at 1R, targets +1/+2/+3R.")
    out("\n== 3. PREREGISTERED HYPOTHESES")
    out(f"{len(SEQ_TYPES)} sequences x {len(dv.CONTEXTS)} contexts = {result['n_hypotheses']} hypotheses.")
    out("Sequences: " + ", ".join(f"{s} ({TRIGGER_DIRECTION[s]})" for s in SEQ_TYPES))
    out("\n== 4. NUMBER OF HYPOTHESES TESTED")
    out(f"{result['n_hypotheses']} (fixed list). Bonferroni two-sided z = {result['z']:.2f}.")
    out("\n== 5. BASELINES")
    for name, bounds in (("discovery", dv.DISCOVERY), ("validation", dv.VALIDATION)):
        sub = df[(df["f_index"] >= bounds[0]) & (df["f_index"] < bounds[1])]
        out(f"{name}: buy mean 2R expectancy {sub['y_buy_exp_2r'].mean():.4f}, "
            f"sell mean 2R expectancy {sub['y_sell_exp_2r'].mean():.4f} (all bars, matched per session in the effect).")

    out("\n== 6. STATISTICAL METHOD")
    out("Effect = candidate expectancy (2R target, stop 1R) minus same-session, same-direction baseline.")
    out("t-statistic is the paired mean of per-trigger effects over its standard error. Wilson intervals for win rates; "
        f"bootstrap ({dv.BOOT_N} resamples, seed {dv.BOOT_SEED}) for expectancy.")

    out("\n== 7. CANDIDATE RESULTS (discovery | validation | walk-forward | classification)")
    table = []
    for r in rows:
        d, v = r["d"], r["v"]
        table.append({
            "hypothesis": d["hypothesis"], "dir": d["direction"],
            "disc_n": d["n"], "disc_eff": d.get("effect_2r"), "disc_t": d.get("effect_t"),
            "val_n": v["n"], "val_eff": v.get("effect_2r"), "val_t": v.get("effect_t"),
            "wf_signs": r["walk_forward_signs"], "class": _classify(r),
        })
    out(pd.DataFrame(table).sort_values("disc_t", key=lambda s: s.abs(), ascending=False).to_string(index=False))

    out("\n== 8. CONTINUATION VS REVERSAL (discovery + validation only)")
    cr = _continuation_reversal(df)
    out(cr.to_string(index=False))

    out("\n== 9. TEST SET (only candidates passing discovery, validation and walk-forward)")
    eligible = [r for r in rows if r["eligible_for_test"]]
    if not eligible:
        out("No candidate was eligible. The test period was not evaluated for any hypothesis.")
    for r in eligible:
        t = r["test"]
        out(f"{r['d']['hypothesis']}: test n={t['n']} effect_2r={t.get('effect_2r')} t={t.get('effect_t')} "
            f"expectancy_2r={t.get('expectancy_2r')} net_of_cost={t.get('effect_2r_net_of_cost')}")

    out("\n== 10. WALK-FORWARD")
    for r in rows:
        out(f"{r['d']['hypothesis']}: effect signs by discovery block {r['walk_forward_signs']}")

    out("\n== 11. MULTIPLE COMPARISONS")
    out(f"{result['n_hypotheses']} hypotheses, Bonferroni-corrected. Expected false positives by chance at alpha 0.05 "
        f"uncorrected: {0.05 * result['n_hypotheses']:.1f}.")

    out("\n== 12. TRANSACTION COST")
    out(f"Cost sensitivity: {dv.COST_R:.2f}R per trade is subtracted from every effect (effect_2r_net_of_cost).")

    out("\n== 13. ROBUSTNESS")
    out("Parameter sensitivity (sweep window 12 vs 6 bars, key tolerance 0.25 vs 1.0 ATR) was NOT run in this pass.")
    out("Direction stability is reported through the BUY and SELL rows of the same context; no separate test.")

    out("\n== 14. FINAL CLASSIFICATION")
    counts = pd.Series([_classify(r) for r in rows]).value_counts()
    out(counts.to_string())

    out("\n== 15. FAILED AND REVERSED PATTERNS")
    reversed_rows = [r for r in rows if r["d"]["n"] >= dv.MIN_N and r["v"]["n"] >= dv.MIN_N
                     and r["d"].get("effect_2r") is not None and r["v"].get("effect_2r") is not None
                     and (r["d"]["effect_2r"] > 0) != (r["v"]["effect_2r"] > 0)]
    if reversed_rows:
        for r in reversed_rows:
            out(f"{r['d']['hypothesis']}: discovery effect {r['d']['effect_2r']} vs validation {r['v']['effect_2r']}")
    else:
        out("No hypothesis with adequate sample reversed sign between discovery and validation.")

    out("\n== 16. LIMITATIONS")
    out("Single symbol, single six-month window, hypothetical ATR-based R, no slippage model, no parameter sweep, "
        "one broker's history. Sequence windows (12 and 24 bars) were fixed a priori.")

    out("\n== 17. RECOMMENDED NEXT RESEARCH STEP")
    out("Replicate on a longer history before any candidate is considered. Do not promote a candidate from this report.")

    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "discovery_v2_report.txt").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    main()
