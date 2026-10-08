"""CLI entrypoint for the Entry Model V2 out-of-sample evaluation.

Usage (once genuinely unseen MT5 data after spec.IS_DATA_END exists):

    python -m research.entry_model_v2_oos.run_oos_evaluation --data <pickle_dir_or_file> \
        [--sample-every 5] [--max-bars-list 24,48,96] [--out docs/entry-model-v2-oos-result.md]

This script does not and cannot alter any Entry Model V2 parameter: it calls
analysis.entry_model.hierarchy.evaluate() and analysis.entry_model.outcome.label_outcome() exactly
as the production code and every prior research stage did, with no arguments that touch a
threshold or rule. The only configurable things here are *sampling mechanics* (how often to
evaluate, which fixed horizons to additionally report) -- never the model itself.

Every run:
  1. Loads the raw candle data (M1/M5/M15/H1/H4/D1) the caller points it at.
  2. Verifies the frozen model's content fingerprint is unchanged (boundary.assert_model_unchanged).
  3. Verifies every proposed evaluation timestamp is strictly after spec.IS_DATA_END
     (boundary.assert_sample_times_after_boundary) -- fails loudly before any evaluation runs.
  4. Runs the frozen hierarchy.evaluate() across the sample grid.
  5. Builds the funnel, extracts deduplicated candidates (boundary.assert_candidates_after_boundary
     re-checked here, independently, after extraction).
  6. Splits hypothesis (0.5<=RR<1.0) vs comparison group via spec.in_hypothesis_group() only.
  7. Labels outcomes for every tradeable candidate, both first-event and each requested fixed horizon.
  8. Writes a provenance-stamped Markdown report -- data source/range, candle counts, model
     fingerprint, spec version, evaluation timestamp, candidate counts, any excluded/boundary
     records -- so the result is auditable independent of this script's own say-so.

This script intentionally does NOT compute or print a verdict label ("supported"/"not supported").
That interpretive step belongs to a human research write-up reading this report's numbers, the same
way every prior stage in this research line kept interpretation separate from computation.
"""
import argparse
import json
import pickle
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from research.entry_model_v2_oos import pipeline, spec
from research.entry_model_v2_oos.boundary import (
    FrozenModelChanged,
    OOSBoundaryViolation,
    assert_candidates_after_boundary,
    assert_model_unchanged,
    assert_raw_data_has_no_pre_boundary_contamination,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


def load_raw(data_path: Path) -> dict:
    """`data_path` is either a single pickle containing a dict of {tf: DataFrame}, or a directory
    containing one pickle per timeframe named like 'M5.pkl'. Either way, every DataFrame must have
    'time', 'close_time', and 'is_closed' columns, matching mt5/market_data.py's own output shape --
    this loader does not fetch from MT5 itself; that is the caller's job, done however is convenient
    once new data exists."""
    if data_path.is_dir():
        raw = {}
        for tf in pipeline.REQUIRED_TFS:
            f = data_path / f"{tf}.pkl"
            if f.exists():
                with open(f, "rb") as fh:
                    raw[tf] = pickle.load(fh)
        return raw
    with open(data_path, "rb") as fh:
        obj = pickle.load(fh)
    if not isinstance(obj, dict):
        raise ValueError(f"{data_path} must unpickle to a dict of {{timeframe: DataFrame}}")
    return obj


def build_sample_times(raw: dict, sample_every: int) -> list:
    """Every M5-closed-candle timestamp strictly after spec.IS_DATA_END, taking every `sample_every`-th
    one (matching the sampling-density approach of the large in-sample study -- see
    docs/entry-model-v2-large-outcome-study.md).

    Filters on the bar's own `time` (open) field, not `close_time`: spec.IS_DATA_END was frozen as
    the IS M5 history's own last bar's `time` value, so comparing against `close_time` here would
    leak that exact already-known IS bar back in as "OOS" (its close_time, 5 minutes after its
    time, is already past IS_DATA_END even though the bar itself was fully part of the IS dataset).
    Each selected bar's `close_time` -- the instant it actually finished forming -- is what gets
    returned as the evaluation instant, so the model sees it as the most recently closed candle."""
    m5 = raw.get("M5")
    if m5 is None:
        raise ValueError("raw data is missing the M5 timeframe, required to drive sampling")
    closed = m5[m5["is_closed"] & (m5["time"] > spec.IS_DATA_END)]
    return list(closed["close_time"].iloc[::max(1, sample_every)])


def provenance_block(raw: dict, sample_times: list, model_fp: str, started_at: datetime) -> dict:
    prov = {
        "research_spec_version": spec.SPEC_VERSION,
        "model_fingerprint": model_fp,
        "frozen_model_fingerprint_expected": spec.FROZEN_MODEL_FINGERPRINT,
        "is_data_end": str(spec.IS_DATA_END),
        "evaluation_started_at_utc": started_at.isoformat(),
        "n_sample_times": len(sample_times),
        "sample_time_range": [str(sample_times[0]), str(sample_times[-1])] if sample_times else None,
        "candle_counts": {},
    }
    for tf, df in raw.items():
        if df is None:
            continue
        prov["candle_counts"][tf] = {
            "n_rows": int(len(df)),
            "first_time": str(df["time"].min()) if len(df) else None,
            "last_time": str(df["time"].max()) if len(df) else None,
        }
    return prov


def run(data_path: Path, sample_every: int, max_bars_list: list, out_path: Path) -> dict:
    started_at = datetime.now(timezone.utc)

    model_fp = assert_model_unchanged()  # raises FrozenModelChanged loudly if drifted; never caught here

    raw = load_raw(data_path)
    assert_raw_data_has_no_pre_boundary_contamination(raw)  # loud check BEFORE any filtering
    sample_times = build_sample_times(raw, sample_every)
    if not sample_times:
        raise OOSBoundaryViolation(
            f"No M5-closed candles strictly after spec.IS_DATA_END ({spec.IS_DATA_END}) were found in "
            f"{data_path}. There is no valid OOS sample to evaluate -- this is not a result, it is a "
            f"data problem to fix before running again."
        )

    records = pipeline.run_evaluation_samples(raw, sample_times, enforce_oos_boundary=True)
    funnel_rows = pipeline.funnel(records)
    candidates = pipeline.extract_candidates(records)
    boundary_check = assert_candidates_after_boundary(candidates)  # independent second check, post-extraction
    rejections = pipeline.rejection_reasons(records)

    split = pipeline.split_hypothesis_vs_comparison([c for c in candidates if c["tradeable"]])
    hyp, comp = split["hypothesis_group"], split["comparison_group"]

    m5_all = raw["M5"]
    outcomes_first_event = {
        "hypothesis_group": [pipeline.label_candidate_outcome(c, m5_all, max_bars=None) for c in hyp],
        "comparison_group": [pipeline.label_candidate_outcome(c, m5_all, max_bars=None) for c in comp],
    }
    outcomes_by_horizon = {}
    for mb in max_bars_list:
        outcomes_by_horizon[mb] = {
            "hypothesis_group": [pipeline.label_candidate_outcome(c, m5_all, max_bars=mb) for c in hyp],
            "comparison_group": [pipeline.label_candidate_outcome(c, m5_all, max_bars=mb) for c in comp],
        }

    from research.entry_model_v2_oos import stats as stats_mod

    def r_values(outcomes):
        return [o.get("outcome_r") for o in outcomes if o.get("outcome_r") is not None]

    summary = {
        "first_event": {
            "hypothesis_group": stats_mod.summarize_r(r_values(outcomes_first_event["hypothesis_group"]), "hypothesis (0.5<=RR<1.0)"),
            "comparison_group": stats_mod.summarize_r(r_values(outcomes_first_event["comparison_group"]), "comparison (all other tradeable)"),
            "comparison_test": stats_mod.compare_groups(
                r_values(outcomes_first_event["hypothesis_group"]), r_values(outcomes_first_event["comparison_group"]),
                "hypothesis", "comparison",
            ),
        },
        "by_horizon": {},
    }
    for mb in max_bars_list:
        oh = outcomes_by_horizon[mb]
        summary["by_horizon"][mb] = {
            "hypothesis_group": stats_mod.summarize_r(r_values(oh["hypothesis_group"]), f"hypothesis @ {mb} bars"),
            "comparison_group": stats_mod.summarize_r(r_values(oh["comparison_group"]), f"comparison @ {mb} bars"),
            "comparison_test": stats_mod.compare_groups(
                r_values(oh["hypothesis_group"]), r_values(oh["comparison_group"]), "hypothesis", "comparison",
            ),
        }

    prov = provenance_block(raw, sample_times, model_fp, started_at)
    prov["n_evaluation_records"] = len(records)
    prov["n_candidates_total"] = len(candidates)
    prov["n_candidates_tradeable"] = len(hyp) + len(comp)
    prov["n_candidates_hypothesis_group"] = len(hyp)
    prov["n_candidates_comparison_group"] = len(comp)
    prov["boundary_check"] = {
        "is_data_end": str(boundary_check.is_data_end),
        "min_candidate_time": str(boundary_check.min_candidate_time) if boundary_check.min_candidate_time else None,
        "n_candidates": boundary_check.n_candidates,
        "n_violations": boundary_check.n_violations,
    }
    prov["rejection_reasons_for_confirmed_but_untradeable"] = rejections

    report = {
        "provenance": prov,
        "funnel": funnel_rows,
        "candidates": candidates,
        "outcome_summary": summary,
    }

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data", required=True, type=Path, help="pickle file or directory of per-TF pickles")
    ap.add_argument("--sample-every", type=int, default=1, help="evaluate every Nth closed M5 candle after the boundary")
    ap.add_argument("--max-bars-list", default="24,48,96", help="comma-separated fixed horizons (in M5 bars) to additionally report")
    ap.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "entry-model-v2-oos-result.json")
    args = ap.parse_args()

    max_bars_list = [int(x) for x in args.max_bars_list.split(",") if x.strip()]

    try:
        report = run(args.data, args.sample_every, max_bars_list, args.out)
    except (OOSBoundaryViolation, FrozenModelChanged) as e:
        print(f"OOS evaluation aborted: {type(e).__name__}: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"Wrote OOS evaluation report to {args.out}")
    print(f"  candidates: {report['provenance']['n_candidates_total']} total, "
          f"{report['provenance']['n_candidates_tradeable']} tradeable "
          f"({report['provenance']['n_candidates_hypothesis_group']} hypothesis, "
          f"{report['provenance']['n_candidates_comparison_group']} comparison)")


if __name__ == "__main__":
    main()
