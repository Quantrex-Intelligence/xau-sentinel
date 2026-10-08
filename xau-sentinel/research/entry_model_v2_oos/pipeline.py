"""The frozen Entry Model V2 evaluation pipeline: funnel, candidate extraction/deduplication, and
outcome labeling. This is a durable, repo-housed port of the logic the in-sample studies used
(docs/entry-model-v2-large-outcome-study.md and docs/entry-model-v2-rr-decomposition.md) -- the
SAME methodology, not a reimplementation, so an OOS run and the frozen IS result are comparable.

Calls analysis.entry_model.hierarchy.evaluate() and analysis.entry_model.outcome.label_outcome()
directly and unchanged. Nothing here alters any V2 parameter, threshold, or decision rule.
"""
from collections import Counter
from typing import Callable, Dict, List, Optional

import pandas as pd

import analysis.entry_model.hierarchy as hierarchy
from analysis.entry_model.outcome import label_outcome
from research.entry_model_v2_oos import spec
from research.entry_model_v2_oos.boundary import assert_candidates_after_boundary, assert_sample_times_after_boundary

REQUIRED_TFS = ("M1", "M5", "M15", "H1", "H4", "D1")
DEFAULT_COUNT = {"M1": 300, "M5": 300, "M15": 300, "H1": 300, "H4": 300, "D1": 60}


def make_frames_at(raw: Dict[str, pd.DataFrame], count: Dict[str, int] = None) -> Callable:
    """`raw` maps timeframe -> the FULL candle history (any source; this function does not care
    whether it came from MT5 live, a pickle, or anything else). Returns a `frames_at(asof)` closure
    identical in behaviour to every prior research stage's own frames_at(): the last `count[tf]`
    closed bars with close_time <= asof, per timeframe."""
    count = count or DEFAULT_COUNT

    def frames_at(asof) -> Dict[str, pd.DataFrame]:
        asof = pd.Timestamp(asof)
        out = {}
        for tf in REQUIRED_TFS:
            df = raw.get(tf)
            if df is None:
                out[tf] = None
                continue
            closed = df[df["close_time"] <= asof].tail(count.get(tf, 300))
            out[tf] = closed.reset_index(drop=True)
        return out

    return frames_at


def run_evaluation_samples(raw: Dict[str, pd.DataFrame], sample_times, enforce_oos_boundary: bool = True) -> List[dict]:
    """Runs the frozen hierarchy.evaluate() at every sample time, in order. If
    `enforce_oos_boundary`, every sample time must be strictly after spec.IS_DATA_END (raises
    OOSBoundaryViolation otherwise, before any evaluation is run) -- pass False only for the
    non-OOS regression tests in tests/test_entry_model_v2_oos_pipeline.py, never for a real run."""
    sample_times = [pd.Timestamp(t) for t in sample_times]
    if enforce_oos_boundary:
        assert_sample_times_after_boundary(sample_times)
    frames_at = make_frames_at(raw)
    records = []
    for asof in sample_times:
        out = hierarchy.evaluate(frames_at(asof), asof)
        out["asof"] = str(asof)
        records.append(out)
    return records


def funnel(records: List[dict]) -> List[dict]:
    """Identical staging to the in-sample study's funnel -- see docs/entry-model-v2-large-outcome-study.md section 3."""
    n = len(records)
    stage1 = [r for r in records if (r.get("higher_timeframe") or {}).get("htf_context") in ("BULLISH", "BEARISH")]
    stage2 = [r for r in stage1 if (r.get("intraday") or {}).get("intraday_bias") in ("BULLISH", "BEARISH")
             and (r.get("intraday") or {}).get("compatible_with_htf")]
    stage3 = [r for r in stage2 if (r.get("setup_15m") or {}).get("setup_status") in ("SETUP_DEVELOPING", "SETUP_CONFIRMED")]
    stage4 = [r for r in stage3 if (r.get("confirmation_5m") or {}).get("confirmation_status") in ("DEVELOPING", "CONFIRMED")]
    stage5 = [r for r in stage4 if (r.get("confirmation_5m") or {}).get("confirmation_status") == "CONFIRMED"]
    stage6 = [r for r in records if r["state"] == "ENTRY_READY"]
    stage7 = [r for r in records if (r.get("entry_candidate") or {}).get("stop") is not None
             and (r.get("entry_candidate") or {}).get("target") is not None]

    def row(name, lst, prev_n):
        return {"stage": name, "n": len(lst), "pct_of_total": round(100 * len(lst) / n, 3) if n else None,
                "pct_of_previous": None if prev_n is None else (round(100 * len(lst) / prev_n, 2) if prev_n else None)}

    return [
        row("All evaluation samples", records, None),
        row("HTF context resolved", stage1, n),
        row("1H direction established (compatible)", stage2, len(stage1)),
        row("15M setup (developing or confirmed)", stage3, len(stage2)),
        row("5M confirmation developing or confirmed", stage4, len(stage3)),
        row("5M confirmation CONFIRMED", stage5, len(stage4)),
        row("ENTRY_READY", stage6, len(stage5)),
        row("Tradeable candidate (stop+target both resolved)", stage7, len(stage6)),
    ]


def _working_direction(r: dict) -> Optional[str]:
    """The setup's underlying (ungated) direction, i.e. setup_15m's own setup_direction -- LONG,
    SHORT, NEUTRAL, or CONFLICTED. Unlike r['direction'] (the exposed/gated value hierarchy.evaluate
    returns, which is None whenever 5M confirmation has not yet reached CONFIRMED -- see the
    exposed_direction gating fix), this stays LONG/SHORT for the entire life of a setup once 15M
    resolves one, which is what candidate identity/deduplication needs: an ENTRY_CONFIRMATION_DEVELOPING
    snapshot and the ENTRY_CONFIRMED snapshot that follows it are the same real-world candidate even
    though the exposed direction only appears at the second one."""
    setup = r.get("setup_15m") or {}
    return setup.get("setup_direction")


def extract_candidates(records: List[dict]) -> List[dict]:
    """Identical deduplication to the in-sample study: a run of consecutive (in sample order)
    qualifying snapshots sharing the same working direction AND the same stop price is ONE
    real-world candidate, observed repeatedly -- not a new one each time. See
    docs/entry-model-v2-large-outcome-study.md section 3 for the full rationale. Grouping uses the
    working direction (see _working_direction), not the exposed/gated r['direction'], which is None
    during ENTRY_CONFIRMATION_DEVELOPING and would otherwise collapse unrelated developing setups
    into one bogus group."""
    qualifying = [r for r in records if r["state"] in spec.QUALIFYING_STATES]
    qualifying.sort(key=lambda r: r["asof"])

    groups, current = [], None
    for r in qualifying:
        cand = r.get("entry_candidate")
        stop_key = None if cand is None or cand.get("stop") is None else round(cand["stop"]["price"], 2)
        key = (_working_direction(r), stop_key)
        if current is not None and current["key"] == key:
            current["rows"].append(r)
        else:
            if current is not None:
                groups.append(current)
            current = {"key": key, "rows": [r]}
    if current is not None:
        groups.append(current)

    rank = {"ENTRY_CONFIRMATION_DEVELOPING": 0, "ENTRY_CONFIRMED": 1, "PRECISION_AVAILABLE": 2, "ENTRY_READY": 3}
    out = []
    for g in groups:
        first, last = g["rows"][0], g["rows"][-1]
        best = max(g["rows"], key=lambda r: rank.get(r["state"], -1))
        cand = best.get("entry_candidate")
        direction = _working_direction(first)
        out.append({
            "setup_id": f"{direction}:{first['asof']}",
            "first_asof": first["asof"], "last_asof": last["asof"], "n_observations": len(g["rows"]),
            "direction": direction, "exposed_direction": best.get("direction"), "best_state": best["state"],
            "tradeable": cand is not None and cand.get("stop") is not None and cand.get("target") is not None,
            "entry": None if cand is None else cand.get("entry"),
            "stop": None if cand is None or cand.get("stop") is None else cand["stop"]["price"],
            "stop_basis": None if cand is None or cand.get("stop") is None else cand["stop"]["basis"],
            "target": None if cand is None or cand.get("target") is None else cand["target"]["price"],
            "rr": None if cand is None else cand.get("rr"),
            "precision_available": any((r.get("precision_1m") or {}).get("precision_status") == "AVAILABLE" for r in g["rows"]),
            "confidence_score": (best.get("confidence") or {}).get("score"),
        })
    return out


def label_candidate_outcome(candidate: dict, m5_all: pd.DataFrame, max_bars: Optional[int] = None) -> dict:
    """Reuses analysis.entry_model.outcome.label_outcome unchanged. `m5_all` must be the FULL M5
    history (so forward replay can see bars after the candidate's own time)."""
    if not candidate["tradeable"]:
        return {"outcome_status": "UNTRADEABLE_INCOMPLETE"}
    t0 = pd.Timestamp(candidate["first_asof"])
    path = m5_all[m5_all["time"] > t0].reset_index(drop=True)
    outcome_input = {"direction": candidate["direction"], "entry": {"price": candidate["entry"]},
                     "stop": {"price": candidate["stop"]}, "targets": [{"price": candidate["target"]}],
                     "record_time_utc": candidate["first_asof"]}
    return label_outcome(outcome_input, path, max_bars=max_bars)


def split_hypothesis_vs_comparison(candidates: List[dict]) -> Dict[str, List[dict]]:
    """The ONLY place a candidate is sorted into the hypothesis group or the comparison group --
    uses spec.in_hypothesis_group(), never a re-implemented bound check."""
    hyp = [c for c in candidates if spec.in_hypothesis_group(c.get("rr"))]
    comp = [c for c in candidates if not spec.in_hypothesis_group(c.get("rr"))]
    return {"hypothesis_group": hyp, "comparison_group": comp}


def rejection_reasons(records: List[dict]) -> dict:
    reasons = Counter()
    for r in records:
        conf = r.get("confirmation_5m") or {}
        if conf.get("confirmation_status") != "CONFIRMED":
            continue
        cand = r.get("entry_candidate")
        if cand is not None and cand.get("stop") is not None and cand.get("target") is not None:
            continue
        if cand is None:
            reasons["no entry_candidate built (state capped before ENTRY_CONFIRMED)"] += 1
        elif cand.get("stop") is None:
            reasons["no deterministic stop"] += 1
        elif cand.get("target") is None:
            reasons["no qualifying opposing zone for select_target()"] += 1
    return dict(reasons)
