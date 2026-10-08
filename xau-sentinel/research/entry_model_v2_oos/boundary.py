"""Temporal data-boundary and frozen-model protection for the Entry Model V2 OOS pipeline.

Every function here either passes silently or raises loudly -- never silently filters, relabels,
or drops a boundary-violating record. A future OOS run that trips one of these is a bug or a data
mistake to fix, not something to work around in the pipeline.
"""
from dataclasses import dataclass
from typing import Sequence

import pandas as pd

from research.entry_model_v2_oos import spec


class OOSBoundaryViolation(Exception):
    """Raised when data or a candidate at/before spec.IS_DATA_END would otherwise enter an
    'OOS' evaluation. Never caught-and-filtered by this package -- the caller must fix the input."""


class FrozenModelChanged(Exception):
    """Raised when analysis/entry_model/* or ai/strategy/rules.py no longer matches the content
    fingerprint the research spec was frozen against. The OOS run must stop: comparing a changed
    model's behaviour against the frozen in-sample result would not be a valid test of the
    original hypothesis."""


@dataclass(frozen=True)
class BoundaryCheckResult:
    is_data_end: pd.Timestamp
    min_candidate_time: "pd.Timestamp | None"
    n_candidates: int
    n_violations: int


def assert_sample_times_after_boundary(sample_times: Sequence) -> None:
    """Call this BEFORE running the frozen model over any proposed OOS sample list. Every as-of
    timestamp used to drive evaluation must be strictly after spec.IS_DATA_END -- this is checked
    before spending any time evaluating the model, so a misconfigured data pull fails immediately
    rather than after a long run."""
    times = [pd.Timestamp(t) for t in sample_times]
    bad = [t for t in times if t <= spec.IS_DATA_END]
    if bad:
        raise OOSBoundaryViolation(
            f"{len(bad)} of {len(times)} proposed evaluation timestamps are at or before the "
            f"frozen IS boundary ({spec.IS_DATA_END}). Earliest offending timestamp: {min(bad)}. "
            f"This is not a valid OOS sample -- fix the data pull, do not filter these out here."
        )


def assert_candidates_after_boundary(candidates: Sequence[dict], time_key: str = "first_asof") -> BoundaryCheckResult:
    """Call this AFTER candidate extraction, as a second, independent check. `candidates` is the
    same list shape produced by pipeline.extract_candidates() -- each item must have a
    `time_key` field. Raises OOSBoundaryViolation naming every offending candidate if any exist;
    otherwise returns a small summary for the provenance record."""
    times = [pd.Timestamp(c[time_key]) for c in candidates]
    bad_ids = [c.get("setup_id", "<no setup_id>") for c, t in zip(candidates, times) if t <= spec.IS_DATA_END]
    if bad_ids:
        raise OOSBoundaryViolation(
            f"{len(bad_ids)} of {len(candidates)} candidates have a {time_key} at or before the "
            f"frozen IS boundary ({spec.IS_DATA_END}): {bad_ids[:10]}"
            f"{' ...' if len(bad_ids) > 10 else ''}. This is not a valid OOS sample."
        )
    return BoundaryCheckResult(
        is_data_end=spec.IS_DATA_END,
        min_candidate_time=min(times) if times else None,
        n_candidates=len(candidates), n_violations=0,
    )


def assert_raw_data_has_no_pre_boundary_contamination(raw: dict, time_col: str = "time") -> None:
    """Call this on a freshly loaded raw {timeframe: DataFrame} dict BEFORE any sampling or
    filtering happens. Unlike assert_sample_times_after_boundary (which checks a list of proposed
    evaluation instants you already intend to use), this checks the SOURCE data itself for any row
    at or before spec.IS_DATA_END.

    This exists because a sampling helper that simply filters `df[time_col] > IS_DATA_END` before
    building its sample list would silently drop contaminated rows rather than reporting them --
    the exact silent-filtering failure mode this research line has repeatedly been told to avoid.
    If the data a caller points this pipeline at mixes in-sample and post-boundary rows (e.g. a
    wrong file, a bad merge, a rolling fetch that always includes some trailing IS history), that is
    worth knowing about loudly, even though the sampler would have ignored those rows anyway."""
    bad = {}
    for tf, df in raw.items():
        if df is None or time_col not in getattr(df, "columns", []):
            continue
        contaminated = df[pd.to_datetime(df[time_col]) <= spec.IS_DATA_END]
        if len(contaminated):
            bad[tf] = {"n_rows": len(contaminated), "latest_contaminated": str(contaminated[time_col].max())}
    if bad:
        detail = ", ".join(f"{tf}: {info['n_rows']} row(s), latest at {info['latest_contaminated']}"
                           for tf, info in bad.items())
        raise OOSBoundaryViolation(
            f"Raw data supplied for OOS evaluation contains rows at or before the frozen IS "
            f"boundary ({spec.IS_DATA_END}): {detail}. This is not filtered out silently -- fix the "
            f"data source (wrong file, bad merge, or a fetch that needs to start later) before "
            f"running again."
        )


def assert_model_unchanged() -> str:
    """Raises FrozenModelChanged if the live analysis/entry_model/*.py + ai/strategy/rules.py no
    longer match the fingerprint the research spec was frozen against. Returns the current
    fingerprint (== spec.FROZEN_MODEL_FINGERPRINT) on success, for the provenance record."""
    current = spec.compute_model_fingerprint()
    if current != spec.FROZEN_MODEL_FINGERPRINT:
        raise FrozenModelChanged(
            f"The Entry Model V2 implementation has changed since the research spec was frozen.\n"
            f"  Frozen fingerprint:  {spec.FROZEN_MODEL_FINGERPRINT}\n"
            f"  Current fingerprint: {current}\n"
            f"An OOS run against a changed model is not a valid test of the frozen hypothesis. "
            f"Either restore the frozen files, or deliberately re-freeze the spec (updating "
            f"FROZEN_MODEL_FINGERPRINT in spec.py AND docs/entry-model-v2-oos-research-spec.md "
            f"together, with a note explaining why) before running OOS evaluation again."
        )
    return current
