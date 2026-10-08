# Entry Model V2 out-of-sample research specification (frozen)

This is the human-readable, **authoritative** version of the frozen research spec. The
machine-readable companion is `research/entry_model_v2_oos/spec.py`. If the two ever disagree, this
document wins and `spec.py` has drifted — fix the code to match this document, never the reverse.

Nothing on this page may be edited to make a future OOS result look better. Any genuine need to
change a frozen value here requires changing this document and `spec.py` together, in a commit that
says so explicitly, and never after an OOS result is already known.

## 1. The frozen hypothesis

> Candidates whose planned R:R falls in **0.5 ≤ R:R < 1.0** have better expectancy than the broader
> population of tradeable Entry Model V2 candidates.

This was discovered descriptively in the 115-candidate in-sample decomposition
(`docs/entry-model-v2-rr-decomposition.md`) and given an in-sample robustness read in
`docs/entry-model-v2-robustness-audit.md` (verdict: **WEAK EXPLORATORY SIGNAL**, not validated,
not proven). It has never been tested against genuinely unseen data. This page exists to make that
test possible later without re-deriving or silently narrowing the hypothesis.

- **Hypothesis group**: tradeable candidates with `0.5 <= planned_RR < 1.0` (half-open interval,
  matching the in-sample study's own bucket boundaries).
- **Comparison group**: every other tradeable candidate in the same OOS sample — `planned_RR` is
  `None` (no target resolved) or outside `[0.5, 1.0)`. Nothing is excluded from the comparison
  group; it is reported in full, exactly as the in-sample study did.
- The only code allowed to implement this bound check is `spec.in_hypothesis_group()`. No other
  module may re-implement the comparison inline.

## 2. The frozen in-sample boundary

```
IS_DATA_END = 2026-10-06 12:20:00 UTC
```

This is the last M5 bar's own `time` (open) value across every cached in-sample dataset used by the
152-candidate / 115-tradeable-candidate study and every later decomposition/robustness stage built
on it. A valid OOS candidate's own defining timestamp (`first_asof`, the candidate's earliest
qualifying observation) must be **strictly after** this instant.

**Convention note**: this boundary is defined against a bar's own `time` (open) field, not
`close_time`. A bar's `close_time` is 5 minutes later than its `time` for M5 data, so comparing
against `close_time` would let the single already-known last IS bar leak back in as a false
"OOS" sample (its `close_time`, 12:25:00, is already past 12:20:00 even though the bar itself was
part of the IS dataset). This was found and fixed during this infrastructure build — see
`research/entry_model_v2_oos/run_oos_evaluation.py::build_sample_times` and the regression test
`test_build_sample_times_excludes_a_bar_whose_close_time_leaks_past_the_boundary_but_whose_own_time_does_not`
in `tests/test_entry_model_v2_oos_pipeline.py`.

If a proposed OOS dataset contains any sample at or before this boundary, the pipeline raises
`research.entry_model_v2_oos.boundary.OOSBoundaryViolation` and refuses to produce a result. It
never filters the offending rows out and continues — a boundary violation is a data problem to fix,
not something to silently work around.

## 3. The frozen model

The hypothesis is only comparable across IS and OOS if it is the same model both times. "The
model" for this research line is:

- `analysis.entry_model.hierarchy.evaluate` — the orchestrator (direction/state ladder,
  `exposed_direction` gating, invalidation, entry candidate construction, confidence).
- `analysis.entry_model.outcome.label_outcome` — outcome replay (MFE/MAE, R-multiple, first-event
  and fixed-horizon resolution).
- The risk primitives it calls into, shared with A+: `ai.strategy.rules.compute_stop_loss`,
  `select_target`, `compute_risk_reward`, `display_rr`.

Since `analysis/entry_model/*` has no commit yet (it was uncommitted when this research line began
and remains uncommitted here — see repo `git log`), a git hash would be misleading as a "frozen
version" marker. Instead, `spec.py::compute_model_fingerprint()` computes a SHA-256 over the fixed,
ordered concatenation of these files' bytes:

```
analysis/entry_model/hierarchy.py
analysis/entry_model/htf.py
analysis/entry_model/intraday.py
analysis/entry_model/setup_15m.py
analysis/entry_model/confirmation_5m.py
analysis/entry_model/precision_1m.py
analysis/entry_model/common.py
analysis/entry_model/confidence.py
analysis/entry_model/outcome.py
ai/strategy/rules.py
```

Frozen value at spec-authoring time:

```
FROZEN_MODEL_FINGERPRINT = 62427db38bef9e8f1d67ebd6d4e3417e5506f6c504fc865610bfef97113fcdaa
```

Also recorded, for completeness (not independently re-checked by content, since `config.py` holds
many unrelated settings — these are the specific *values* the model reads):

| Setting | Frozen value | Note |
|---|---|---|
| `ENTRY_MODEL_SWEEP_MAX_BARS` | 8 | sweep-anchor expiry window, in M15 bars |
| `AI_STRATEGY_SL_BUFFER` | 0.30 | stop-loss buffer, shared with A+ |
| `AI_STRATEGY_MIN_RR` | 3.0 | A+'s own threshold — **not** applied anywhere in Entry Model V2 (see `docs/entry-model-v2-fixes.md` §2); recorded only so a future change to it cannot silently go unnoticed by this research line |

Before any OOS run, `research.entry_model_v2_oos.boundary.assert_model_unchanged()` recomputes the
fingerprint and raises `FrozenModelChanged` if it no longer matches. An OOS run against a changed
model is not a valid test of this frozen hypothesis.

## 4. Frozen outcome methodology

- **Entry, stop, target**: exactly `analysis.entry_model.hierarchy._entry_candidate()`'s own output
  for the candidate's defining (first-qualifying) observation — current M5 close as entry, the
  deterministic stop/target from the shared A+ risk primitives. Never re-derived or adjusted here.
- **Outcome labeling**: `analysis.entry_model.outcome.label_outcome()`, unchanged. Both first-event
  (unbounded forward replay) and fixed-horizon (`max_bars`) resolution are computed and reported.
  A stop touch and a target touch on the same bar resolve to the stop (the existing conservative
  convention).
- **No lookahead**: every frame passed to `hierarchy.evaluate()` is closed-candle-only (`is_closed`
  filter), and outcome replay for a candidate at time T0 only ever reads M5 bars with
  `time > T0`. Neither rule is re-implemented in the OOS pipeline — both are inherited by calling
  the frozen entrypoints directly.
- **Candidate deduplication**: a run of consecutive (in sample order) qualifying snapshots sharing
  the same *working* direction (`setup_15m.setup_direction`, not the gated `exposed_direction`,
  which is `None` during `ENTRY_CONFIRMATION_DEVELOPING`) **and** the same stop price is one
  real-world candidate. The group's first qualifying observation defines its timestamp for outcome
  replay. See `research/entry_model_v2_oos/pipeline.py::extract_candidates`.
- **Qualifying states**: `ENTRY_CONFIRMATION_DEVELOPING`, `ENTRY_CONFIRMED`, `PRECISION_AVAILABLE`,
  `ENTRY_READY` — the same states the in-sample funnel studies used, so a candidate that never
  progresses past `DEVELOPING` is still counted (as untradeable) rather than silently dropped.

## 5. What this research line must never do with this spec

- Widen, narrow, or re-center the `[0.5, 1.0)` interval.
- Move `IS_DATA_END` earlier or later to fit a convenient dataset.
- Exclude any OOS candidate from the comparison group.
- Treat a result from data at or before `IS_DATA_END` as out-of-sample.
- Claim "validated," "proven edge," or "OOS supported" from anything other than a genuine run
  against data strictly after `IS_DATA_END`, using the unchanged frozen model.
- Optimize any threshold, filter, or piece of V2/A+ logic in response to an OOS result.

## 6. Version

```
SPEC_VERSION = entry-model-v2-oos-1.0
```

A future deliberate change to any frozen value above bumps this version and is recorded as its own
entry in a changelog section added to this document at that time (none exists yet, since nothing
has changed since authoring).
