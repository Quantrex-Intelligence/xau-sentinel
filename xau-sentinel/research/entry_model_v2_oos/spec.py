"""The frozen Entry Model V2 out-of-sample research specification -- machine-readable companion to
docs/entry-model-v2-oos-research-spec.md (the human-readable, authoritative version; if the two
ever disagree, the doc is authoritative and this module has drifted and must be fixed to match it,
never the other way around).

Nothing in this module may be edited to make a future OOS result look better. Changing
`IS_DATA_END`, `RR_LOW`/`RR_HIGH`, or the comparison-group definition is changing the hypothesis,
which this research line has repeatedly been told not to do. If a change is ever genuinely needed,
it must happen in both this file and the doc together, in a commit that says so explicitly -- never
silently, and never after seeing an unfavorable OOS result.
"""
import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Tuple

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]

# --- The frozen hypothesis -------------------------------------------------------------------------
# Exactly as stated in the research task. Do not widen, narrow, or re-center this interval.
RR_LOW = 0.5
RR_HIGH = 1.0  # exclusive upper bound, matching the prior in-sample study's own bucket_of()


def in_hypothesis_group(planned_rr) -> bool:
    """True iff RR_LOW <= planned_rr < RR_HIGH. The ONLY place this comparison is allowed to live --
    every caller must use this function, never re-implement the bounds inline."""
    return planned_rr is not None and RR_LOW <= planned_rr < RR_HIGH


# --- The frozen temporal boundary -------------------------------------------------------------------
# The exact end of the in-sample dataset used for the 115-candidate study
# (docs/entry-model-v2-large-outcome-study.md, docs/entry-model-v2-rr-decomposition.md,
# docs/entry-model-v2-robustness-audit.md). A valid OOS candidate's own defining timestamp must be
# STRICTLY AFTER this instant.
IS_DATA_END = pd.Timestamp("2026-10-06 12:20:00", tz="UTC")  # the IS M5 history's own last bar


# --- Frozen methodology references (no new logic; these name what is reused unchanged) -------------
FROZEN_MODEL_ENTRYPOINT = "analysis.entry_model.hierarchy.evaluate"
FROZEN_OUTCOME_ENTRYPOINT = "analysis.entry_model.outcome.label_outcome"
FROZEN_RISK_PRIMITIVES = (
    "ai.strategy.rules.compute_stop_loss",
    "ai.strategy.rules.select_target",
    "ai.strategy.rules.compute_risk_reward",
    "ai.strategy.rules.display_rr",
)
QUALIFYING_STATES = ("ENTRY_CONFIRMATION_DEVELOPING", "ENTRY_CONFIRMED", "PRECISION_AVAILABLE", "ENTRY_READY")

NO_LOOKAHEAD_NOTE = (
    "Every frame passed to the frozen model is closed-candle-only (the same `is_closed` filter "
    "analysis/entry_model/hierarchy.py itself applies); evaluation at timestamp T only ever sees "
    "bars with close_time <= T. Outcome replay for a candidate at time T0 only ever reads M5 bars "
    "with time > T0. Neither rule is re-implemented here -- both are inherited by calling the "
    "frozen entrypoints above directly."
)

COMPARISON_GROUP_NOTE = (
    "Every tradeable OOS candidate NOT in the hypothesis group -- i.e. planned_rr is None, or "
    "planned_rr is outside [0.5, 1.0). Nothing is excluded from the comparison group; it is "
    "reported in full alongside the hypothesis group, exactly as the in-sample study did."
)


# --- Frozen-code fingerprint ------------------------------------------------------------------------
# No commit exists yet for analysis/entry_model/ (it is uncommitted at the time this spec was
# written). A git hash would therefore be misleading. Instead, this is a content fingerprint of the
# exact files that define "the frozen V2 implementation" for this research line -- computed once,
# frozen into FROZEN_MODEL_FINGERPRINT below, and re-checked at the start of every OOS run
# (research/entry_model_v2_oos/boundary.py::assert_model_unchanged). A mismatch means the model
# changed since this spec was written and the run must stop rather than silently compare apples to
# oranges.
FINGERPRINT_FILES: Tuple[str, ...] = (
    "analysis/entry_model/hierarchy.py",
    "analysis/entry_model/htf.py",
    "analysis/entry_model/intraday.py",
    "analysis/entry_model/setup_15m.py",
    "analysis/entry_model/confirmation_5m.py",
    "analysis/entry_model/precision_1m.py",
    "analysis/entry_model/common.py",
    "analysis/entry_model/confidence.py",
    "analysis/entry_model/outcome.py",
    "ai/strategy/rules.py",
)

# The specific config values rules.py/hierarchy.py read, captured as values (not a whole-file hash
# of config.py, which holds many unrelated settings that would make this fingerprint drift for
# reasons that have nothing to do with this model).
FROZEN_CONFIG_VALUES = {
    "ENTRY_MODEL_SWEEP_MAX_BARS": 8,
    "AI_STRATEGY_SL_BUFFER": 0.30,
    "AI_STRATEGY_MIN_RR": 3.0,  # A+'s own threshold; NOT applied to Entry Model V2 anywhere -- see
                               # docs/entry-model-v2-fixes.md section 2. Recorded here only so a
                               # future config change to it cannot silently go unnoticed.
}


def compute_model_fingerprint() -> str:
    """SHA-256 over the concatenated bytes of every file in FINGERPRINT_FILES, in the fixed order
    given, prefixed by each file's own path (so a pure rename is also detected). Deterministic and
    does not depend on git history."""
    h = hashlib.sha256()
    for rel_path in FINGERPRINT_FILES:
        h.update(rel_path.encode("utf-8"))
        h.update(b"\x00")
        h.update((REPO_ROOT / rel_path).read_bytes())
        h.update(b"\x00")
    return h.hexdigest()


# Frozen at spec-authoring time. Re-generate this exact value with
# `python -c "from research.entry_model_v2_oos.spec import compute_model_fingerprint; print(compute_model_fingerprint())"`
# -- it must only ever be updated deliberately, alongside a note explaining why, never silently.
FROZEN_MODEL_FINGERPRINT = "62427db38bef9e8f1d67ebd6d4e3417e5506f6c504fc865610bfef97113fcdaa"


@dataclass(frozen=True)
class ResearchSpec:
    version: str
    is_data_end: pd.Timestamp
    rr_low: float
    rr_high: float
    qualifying_states: Tuple[str, ...]
    model_fingerprint: str
    config_values: dict


SPEC_VERSION = "entry-model-v2-oos-1.0"

CURRENT_SPEC = ResearchSpec(
    version=SPEC_VERSION, is_data_end=IS_DATA_END, rr_low=RR_LOW, rr_high=RR_HIGH,
    qualifying_states=QUALIFYING_STATES, model_fingerprint=FROZEN_MODEL_FINGERPRINT,
    config_values=dict(FROZEN_CONFIG_VALUES),
)
