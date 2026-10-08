# Entry Model V2: direction/state gating fix, and the target-selection audit

Fixes the structural finding from `docs/entry-model-v2-outcome-research.md` section 12. No new
indicator, ML/LLM logic, or parameter was added; no threshold was tuned; the intended V2 hierarchy
(1D+4H → 1H → 15M → 5M → 1M → entry candidate) is unchanged in shape.

## 1. Direction/state gating — the fix

### Root cause

`hierarchy.evaluate()` set the output's `direction` field directly from `setup_15m`'s own
resolution, with no further check. `setup_15m.evaluate_setup()`'s own gate checked only `intraday_bias`
(1H), never `htf_context` (1D/4H) or `intraday["compatible_with_htf"]`. So a 15M setup could fully
confirm a direction the 1H layer itself held only because 1D and 4H had never agreed with each
other — and that direction reached the output unconditionally, even while 5M had never confirmed
anything.

### The fix (two parts, both additive gates — no detector, chain, or state name changed)

1. **`analysis/entry_model/setup_15m.py`** — `evaluate_setup()` now takes `htf_context` and
   `compatible_with_htf` in addition to `intraday_bias`. A direction can only be resolved from 15M
   evidence when `htf_context` is `BULLISH`/`BEARISH`, `intraday_bias` is `BULLISH`/`BEARISH`, *and*
   `compatible_with_htf` is true. If any of those is missing, `setup_direction` stays `NEUTRAL` and
   `setup_status` stays `WAITING`, regardless of how one-sided the 15M evidence is. The evidence
   itself is still gathered and shown on the checklist (informative), just not turned into a
   direction. This is the root-cause fix: it stops the leak at its source, not just at the output.
2. **`analysis/entry_model/hierarchy.py`** — the internal `direction` variable (used, exactly as
   before, to drive 5M confirmation, invalidation, expiry, and entry-candidate construction) is kept
   separate from the newly-introduced `exposed_direction`, which is what the function actually
   returns. `exposed_direction` is `"CONFLICTED"` when a genuine conflict exists (unchanged safety
   behavior, preserved exactly), the resolved `LONG`/`SHORT` value only once 5M confirmation has
   reached `CONFIRMED` (never merely `DEVELOPING`), and `None` otherwise. 1M precision is never
   consulted in this computation at all, so it can never create or change `direction`.

### Required semantics — verified

| Rule | Enforced by |
|---|---|
| 1D/4H unresolved → not actionable | `setup_15m`'s `htf_context` check |
| 1H unresolved or incompatible → not an established bias | `setup_15m`'s `intraday_bias`/`compatible_with_htf` check |
| 15M unresolved → no setup direction | unchanged (`setup_direction` stays `NEUTRAL` with no evidence) |
| 5M not confirmed → no entry direction/candidate | `hierarchy.py`'s `exposed_direction` gate on `confirmation_status == "CONFIRMED"` |
| 1M never establishes or overrides direction | `exposed_direction` never reads `precision_1m` at all |
| CONFLICTED safety behavior preserved | checked first, unconditionally, exactly as before |

### Before vs after — behavior, not just counts

A precise per-sample diff of the full 400-sample replay (identical sampling, identical raw data):

| | Before → After |
|---|---|
| State label changed | 232 / 400 |
| `direction` field changed | 375 / 400 |
| `direction` was LONG/SHORT, now `None` (leak fixed) | 200 |
| `direction` was `None`/`CONFLICTED`, now newly LONG/SHORT | **0** |
| `direction` LONG/SHORT both before and after, same value | 6 |
| `direction` LONG/SHORT both before and after, **different** value (a flip) | **0** |

The fix is strictly conservative: it only ever *removes* a premature claim, never introduces a new
one and never changes which direction was claimed. The large state-label change (182→19
`CONFLICTED`, 119→318 `HTF_LOCATION_IDENTIFIED`, 59→1 `EXPIRED`, 11→0 `INVALIDATED`) is the direct,
intended consequence: many samples were previously being labeled `CONFLICTED`/`EXPIRED`/`INVALIDATED`
based on a direction that should never have been asserted in the first place (1D/4H had not agreed);
they now correctly read as "not yet resolved" (`HTF_LOCATION_IDENTIFIED`/`HTF_CONTEXT_ALIGNED`)
instead of claiming something about a direction that was never genuinely established.

All 6 of the original outcome-research candidates are reproduced with **identical** state and
entry price — the fix does not touch any case that had already earned a resolved direction. The one
case that changes is exactly the one the fix targets: `LONG:2025-12-19T09:25` (`ENTRY_CONFIRMATION_
DEVELOPING`, 5M only `DEVELOPING`) now correctly shows `direction: None` instead of a premature
`LONG`.

### Regression tests added (`tests/test_entry_model_hierarchy.py`)

8 new tests, each isolating exactly one of the required scenarios: direction absent with 1D/4H
unresolved (despite strong 15M evidence), direction absent with 1H unresolved, direction absent with
1H resolved but incompatible with HTF, direction absent with 15M unresolved, direction absent with
15M `SETUP_CONFIRMED` but 5M not confirmed (the core bug), direction present once 5M genuinely
confirms, 1M precision never creating direction while 5M is only `DEVELOPING`, and 1M precision
never changing an already-established direction (toggled on/off with the result compared). All 38
pre-existing hierarchy tests were updated only where their call signature changed (6 tests) or
needed a resolved/compatible HTF+1H to isolate the behavior they were already testing; their
assertions are otherwise unchanged.

## 2. Target-selection audit — no change made

### Investigation

Re-examined the three near-zero-R:R candidates from the outcome research
(`SHORT:2025-05-29` R:R 0.10, `LONG:2025-12-23` R:R 0.00, `LONG:2026-01-15` R:R 0.16) by recomputing
`compute_zones()` at each exact candidate timestamp and tracing which zone `ai.strategy.rules.
select_target()` chose and why.

**Finding:** in every one of the three cases, the selected target was the current day's **Asian
session High or Low** — a real, correctly-identified structural level (confirmed against
`compute_zones()`'s own output, not fabricated or mis-selected) — and the entry price (the current
M5 close at 5M confirmation) happened to already be sitting very close to that same level (0.08 to
4.3 price units away, against stops 15-43 units away). `select_target()` did exactly what its
docstring says: "the nearest meaningful opposing liquidity level beyond entry." Every qualifying
zone name considered (`Previous Day High/Low`, `Asian High/Low`, `H1/H4 Swing High/Low`) is a real,
meaningful structural level — the target *hierarchy* is semantically correct.

### Conclusion: not a bug in `select_target()`, and not fixed here

- `select_target()` is shared, locked logic (`ai/strategy/rules.py`, A+'s own specification, item 9)
  reused unchanged by both A+ and Entry Model V2. Modifying it would be an A+ change by proxy,
  explicitly out of scope.
- The degenerate outcomes are a consequence of **when** Entry Model V2 samples its entry (the
  current M5 close at the moment 5M confirms), which carries no guarantee of distance from any
  qualifying zone — not a flaw in which zone gets chosen once that moment is fixed.
- A+ already has a matching safeguard for exactly this situation:
  `config.AI_STRATEGY_MIN_RR = 3.0` / `rules.passes_min_rr()`, applied in
  `ai/strategy/evaluator.py`. Reusing that *exact* value for V2 was considered and rejected: it is
  A+'s own, separately-calibrated, strict threshold (3:1), and applying it here would suppress
  nearly every V2 candidate in this sample (the best one found was 0.90R) with no evidence basis for
  that number being right for a differently-designed model — that would be tuning a parameter by
  importing someone else's calibration, not reusing a generic primitive.
- No V2-specific minimum-R:R value exists to reuse, and introducing one now would be exactly the
  kind of threshold-tuning this task explicitly rules out ("Do not optimize parameters. Do not tune
  thresholds.").

**Documented as an unresolved target-selection limitation**, per the task's own fallback: Entry
Model V2 does not currently check whether a selected target is far enough from entry to represent a
meaningful objective, and no deterministic, already-existing V2-appropriate threshold exists to add
that check with today. A future, separately-authorized research stage would need to establish and
validate a V2-specific minimum distance or R:R on a larger sample before any such gate could be
added responsibly.

## 3. Validation

- **Entry Model V2 tests**: 46/46 (`tests/test_entry_model_hierarchy.py`, 8 new).
- **V1 tests**: 37/37 (`tests/test_entry_model.py`) + 12/12 (`tests/test_entry_model_outcome.py`) —
  untouched, unaffected.
- **Full backend suite**: 1780/1780 (1772 prior + 8 new).
- **Frontend**: not touched by this change (`direction: null` was already the card's existing
  "no setup" rendering path); no frontend file was modified, so the full frontend suite from the
  prior stage stands. `tsc`/ESLint/build were not re-run since no frontend file changed.
- **E2E checklists**: 98/99 across all 6 checklists (migration 21/21, analysis-v2 24/24, A+ 14/15,
  contextual-analysis 14/14, market-intelligence 13/13, historical-similarity 12/12). The one
  failure ("Stage 1 SetupPanel still renders") is a pre-existing UI issue in
  `frontend/components/setup/setup-panel.tsx` / `disclosure.tsx` — both files are completely
  untouched by this task (confirmed via `git status`) and have no relationship to Entry Model code.
  Root cause: the E2E script clicks the outer "Setup checklist, risk and alerts" disclosure
  (Playwright's substring name match finds only that button), which reveals — but does not expand —
  a *nested* "Setup checklist" disclosure that defaults to collapsed, so the checklist item text
  ("Liquidity Sweep" etc.) never renders without a second click the script doesn't make. Confirmed
  unrelated to Entry Model and out of this task's scope; not fixed here.
- **Historical 400-sample replay**: reproduced exactly on the same raw data; the precise diff above
  confirms the change is exactly and only what the fix targets.

## 4. Remaining limitations

- The large shift in aggregate state-label counts (section 1) is intended, not a residual bug — but
  it does mean any external consumer of the OLD distribution (e.g. a dashboard showing "182
  CONFLICTED") will see materially different numbers after this fix. That is the correct behavior,
  not a regression, and should be communicated if anything downstream depended on the old counts.
- `direction` can still read `LONG`/`SHORT` on an `INVALIDATED`/`EXPIRED` result if 5M had already
  reached `CONFIRMED` in that same snapshot before the invalidation/expiry fact was found — this is
  intentional (it describes *what* was invalidated/expired) and was not flagged as a problem by the
  task's required semantics, but is worth being aware of.
- The target-selection limitation (section 2) remains unresolved by design; a future research stage
  is needed before any quality gate on target distance is added.
- One pre-existing, unrelated E2E issue was found incidentally (the `SetupPanel` nested-disclosure
  click sequence, see Validation) — worth a separate look, not part of this task.
