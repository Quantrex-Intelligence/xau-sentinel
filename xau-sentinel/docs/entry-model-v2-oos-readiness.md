# Entry Model V2: out-of-sample validation readiness

Infrastructure-only stage. No new research result. This builds the pipeline that will evaluate the
frozen hypothesis once genuinely unseen MT5 data exists; it does not run that evaluation now.

## 1. Files changed

All new, all uncommitted, all outside the production app:

- `research/__init__.py` — package marker, research-only disclaimer.
- `research/entry_model_v2_oos/__init__.py` — package docstring, explicitly distinguishing this
  package from the pre-existing, unrelated `backtest/` package (Analysis Engine V2 feature
  research — a different "V2," a different model).
- `research/entry_model_v2_oos/spec.py` — the frozen, machine-readable research spec: hypothesis
  bound, IS boundary, qualifying states, frozen model fingerprint, frozen config values.
- `research/entry_model_v2_oos/boundary.py` — temporal boundary guard
  (`assert_sample_times_after_boundary`, `assert_candidates_after_boundary`) and frozen-model guard
  (`assert_model_unchanged`). Every function raises loudly; none silently filters.
- `research/entry_model_v2_oos/stats.py` — dependency-free statistics helpers (Wilson CI,
  percentile bootstrap, `summarize_r`, `compare_groups`), a durable port of the scratchpad helpers
  used throughout the IS research.
- `research/entry_model_v2_oos/pipeline.py` — funnel, candidate extraction/deduplication, outcome
  labeling, hypothesis/comparison split. Calls `hierarchy.evaluate()` and `label_outcome()`
  directly and unchanged.
- `research/entry_model_v2_oos/run_oos_evaluation.py` — the CLI entrypoint described in §4.
- `tests/test_entry_model_v2_oos_pipeline.py` — 24 regression tests for the above (plumbing only,
  no claimed finding).
- `docs/entry-model-v2-oos-research-spec.md` — the human-readable, authoritative frozen spec.
- `docs/entry-model-v2-oos-readiness.md` — this document.

Not touched: `analysis/entry_model/*`, `ai/strategy/rules.py`, `config.py`, any production route,
the frontend, or the pre-existing `backtest/` package. Confirmed in §7.

## 2. Frozen hypothesis specification

Full detail in `docs/entry-model-v2-oos-research-spec.md`. Summary:

- **Hypothesis**: tradeable candidates with `0.5 <= planned_RR < 1.0` have better expectancy than
  the rest of the tradeable candidate population.
- **Comparison group**: every other tradeable OOS candidate, reported in full, nothing excluded.
- **IS boundary**: `2026-10-06 12:20:00 UTC` (the IS M5 history's own last bar's `time` field). A
  valid OOS candidate's defining timestamp must be strictly after this instant.
- **Frozen model**: `analysis.entry_model.hierarchy.evaluate` + `outcome.label_outcome` + the shared
  A+ risk primitives, fingerprinted as `62427db38bef9e8f1d67ebd6d4e3417e5506f6c504fc865610bfef97113fcdaa`
  (SHA-256 over the 10 files named in the spec doc, in fixed order).
- **Spec version**: `entry-model-v2-oos-1.0`.

## 3. Data-boundary safeguards

Two independent checks, both in `research/entry_model_v2_oos/boundary.py`:

1. `assert_sample_times_after_boundary(sample_times)` — called *before* any model evaluation runs,
   on the proposed evaluation timestamps. Raises `OOSBoundaryViolation` naming the earliest
   offending timestamp if any sample is at or before `IS_DATA_END`.
2. `assert_candidates_after_boundary(candidates)` — called *again, independently*, after candidate
   extraction, on each candidate's own `first_asof`. Raises `OOSBoundaryViolation` naming every
   offending `setup_id` if any exist.

Neither function filters, relabels, or drops an offending record — both only pass silently or raise.
`pipeline.run_evaluation_samples()` enforces check (1) by default (`enforce_oos_boundary=True`); the
bypass flag exists only for the plumbing tests exercising evaluation mechanics on synthetic
pre-boundary timestamps, never for a real run.

**A real boundary leak was found and fixed while building this.** The sampling helper
(`run_oos_evaluation.py::build_sample_times`) originally filtered candidate evaluation instants on
each M5 bar's `close_time > IS_DATA_END`. Since `IS_DATA_END` was frozen using a bar's own `time`
(open) field, and `close_time` is 5 minutes later, the single already-known last IS bar
(`time=12:20:00`, `close_time=12:25:00`) would have incorrectly passed the filter as "OOS." Fixed to
filter on `time > IS_DATA_END` instead. Caught by deliberately running the boundary guard against
the actual cached IS pickle files (see §6) rather than only against synthetic test timestamps —
demonstrating exactly the kind of off-by-one leak this safeguard exists to prevent.

## 4. OOS evaluator design

`research/entry_model_v2_oos/run_oos_evaluation.py`, run as `python -m
research.entry_model_v2_oos.run_oos_evaluation --data <path>`. Steps, in order:

1. `boundary.assert_model_unchanged()` — recomputes the model fingerprint; aborts immediately if
   `analysis/entry_model/*` or `ai/strategy/rules.py` have changed since the spec was frozen.
2. Loads the raw candle dict (`M1`/`M5`/`M15`/`H1`/`H4`/`D1`) from a pickle or a directory of
   per-timeframe pickles — this script never fetches from MT5 itself; that is left to however the
   caller gets new data once it exists.
3. `build_sample_times()` — every M5-closed-candle instant strictly after `IS_DATA_END` (by `time`,
   not `close_time` — see §3), at the requested density.
4. `boundary.assert_sample_times_after_boundary()` on that list, before any evaluation runs.
5. `pipeline.run_evaluation_samples()` — runs the frozen `hierarchy.evaluate()` across the sample
   grid, unchanged.
6. `pipeline.funnel()` — the same staged funnel (HTF → 1H → 15M → 5M developing → 5M confirmed →
   `ENTRY_READY` → tradeable) as the in-sample study.
7. `pipeline.extract_candidates()` — deduplicates by working direction + stop price;
   `boundary.assert_candidates_after_boundary()` re-checks the result independently.
8. `pipeline.split_hypothesis_vs_comparison()` — the *only* place the `[0.5, 1.0)` bound is applied,
   via `spec.in_hypothesis_group()`.
9. `pipeline.label_candidate_outcome()` for every tradeable candidate, both first-event and each
   requested fixed horizon (`--max-bars-list`, default `24,48,96` M5 bars).
10. `stats.summarize_r()` / `stats.compare_groups()` for both groups.
11. Writes a provenance-stamped JSON report (§5) to `--out` and prints a one-line summary.

The script accepts no argument that touches a V2 threshold, rule, or parameter — the only
configurable things are sampling density (`--sample-every`) and which fixed horizons to additionally
report (`--max-bars-list`), both sampling *mechanics*, never the model. It deliberately prints no
verdict label ("supported"/"not supported"); that interpretation is a separate human step reading
the report's numbers, kept apart from computation the same way every prior stage in this research
line did.

## 5. Provenance safeguards

Every report's `provenance` block records: research spec version, the model fingerprint actually
used (and the frozen one it was checked against), the IS boundary, evaluation start time (UTC),
sample count and time range, per-timeframe candle counts and first/last timestamps, total and
tradeable candidate counts (split by group), the boundary-check result (including any violation
count — always 0, or the run already aborted), and a breakdown of why any 5M-confirmed candidate
never became tradeable (no entry candidate built, no deterministic stop, no qualifying target zone).
This is enough to audit a future result without re-running anything.

## 6. Test results

```
tests/test_entry_model_v2_oos_pipeline.py .......................  (24 passed)
tests/test_entry_model_hierarchy.py        (46 passed)
tests/test_entry_model.py                  (37 passed)
tests/test_entry_model_outcome.py          (12 passed)
--------------------------------------------------------------
119 passed
```

Full backend suite: `1802 passed` (no DB required for this run; existing suite configuration
handled it as usual).

Beyond the automated tests, the boundary guard was demonstrated against the real cached MT5 data
(`%TEMP%\raw_big.pkl`, the freshest cache, M5 ending exactly at `IS_DATA_END`):

- `build_sample_times()` against it returns `0` candidate evaluation instants.
- `run_oos_evaluation.run()` against it raises `OOSBoundaryViolation` end-to-end with a message
  naming the exact problem, rather than producing any report.

This is the required non-result-claiming validation of the safeguard itself (§6 of the task): it
proves the pipeline correctly refuses to treat existing in-sample data as OOS, it does not claim any
OOS finding.

## 7. Confirmation production V2 unchanged

```
git status --short analysis/entry_model/ ai/strategy/rules.py config.py
 M config.py
?? analysis/entry_model/
```

`analysis/entry_model/` is untracked (uncommitted since the original V2 build in an earlier stage of
this research line) and was not touched in this stage — `git diff` shows no pending changes, and the
model fingerprint check (`assert_model_unchanged()`) passes against the live files. `config.py` shows
as modified, but `git diff config.py` shows only the pre-existing `ENTRY_MODEL_SWEEP_MAX_BARS`
addition and comment from the original V2 build — nothing from this stage edited it; no tool in this
stage ever wrote to `config.py`. No historical in-sample result (the 152/115-candidate study, the
R:R decomposition, or the robustness audit) was re-run or altered.

## 8. How to run this once new MT5 data exists

1. Confirm the new data genuinely extends past the frozen boundary:
   `2026-10-06 12:20:00 UTC` (check the new M5 series' own last `time` value is well past this, not
   merely its `close_time`).
2. Fetch and save the new history per timeframe (`M1`, `M5`, `M15`, `H1`, `H4`, `D1`) as a dict of
   DataFrames — each needs `time`, `open`, `high`, `low`, `close`, `close_time`, `is_closed` columns,
   the same shape `mt5/market_data.py` already produces — pickled either as one file (`{tf: df}`) or
   as a directory of `<TF>.pkl` files.
3. Run:
   ```
   python -m research.entry_model_v2_oos.run_oos_evaluation \
       --data <path to the pickle or directory> \
       --sample-every 1 \
       --max-bars-list 24,48,96 \
       --out docs/entry-model-v2-oos-result.json
   ```
4. If it raises `FrozenModelChanged`: `analysis/entry_model/*` or `ai/strategy/rules.py` has changed
   since this spec was frozen. Either restore the frozen files, or deliberately re-freeze the spec
   (update `FROZEN_MODEL_FINGERPRINT` in `spec.py` **and** `docs/entry-model-v2-oos-research-spec.md`
   together, with a note explaining why) before running again.
5. If it raises `OOSBoundaryViolation`: the data does not genuinely extend past the frozen boundary.
   Fix the data pull — never filter the offending rows out to make the run proceed.
6. On success, read the written JSON report's `provenance` block first, then
   `outcome_summary.first_event` and `outcome_summary.by_horizon` for the hypothesis-vs-comparison
   numbers. Write the interpretive verdict (`Supported` / `Weak-uncertain` / `Not supported`, or — if
   either group is still under 10 candidates — `Insufficient data`) as a separate document, the same
   way every prior stage in this research line kept interpretation separate from computation. Do not
   label a result "validated" or "proven" from a single OOS run; the strict-OOS stage of this
   research line already recommended a second, independent validation period before any such claim.
