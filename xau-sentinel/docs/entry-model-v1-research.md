# Entry Model V1: offline statistical research (frozen-model evaluation)

Research only. No line of `analysis/entry_model/model.py`, `config.py`, A+, or V2 was changed to
produce this report. Every number below comes from a read-only, offline extraction and analysis
pipeline (scripts kept outside the repo, in the session scratchpad) run against real XAUUSD MT5
history. Nothing here is committed or pushed, and nothing here changes production behaviour.

## 1. Frozen model definition

The model evaluated is exactly `analysis/entry_model/model.py` as hardened and validated in the
previous stage (`docs/entry-model-v1-plan.md`), with its production configuration:

| Setting | Value | Source |
|---|---|---|
| `ENTRY_MODEL_SWEEP_MAX_BARS` | 8 (M15 bars, ~2h) | `config.py`, this model's own setting |
| `AI_STRATEGY_SWEEP_WINDOW_MINUTES` | 60 | A+'s own setting; not read by this model, untouched |
| Required timeframes | M5, M15, H1, H4, D1 (M1 optional, for 1M confirmation only) | `model.REQUIRED` |
| Entry/stop/target | `ai/strategy/rules.py` primitives, unmodified | reused read-only |

No thresholds, sweep windows, conditions, entry rules, stop/target logic, or confidence weights
were changed for this research. The 4/6/8/12-bar window *comparison* in section 9 is reconstructed
**offline, post-hoc**, from a single research-only extraction run (window monkeypatched to 12 bars
inside an isolated research script only — never in `config.py`). This is exact, not approximate:
nothing downstream of the window check in `evaluate()` reads the window constant, so a smaller
window's behaviour is reproduced exactly by discarding any snapshot older than that window and
taking the setup's state as of the latest snapshot still within it.

## 2. Dataset

**Source:** real MT5 XAUUSD history already pulled for the hardening stage (`raw_big.pkl`:
M5/M15/H1/H4; `raw_entry_extra.pkl`: D1/M1), extended to the full range all five required
timeframes support at once: **2025-05-16 to 2026-10-05 (~17 months)**, versus ~2 months in the
hardening stage's validation (M1 is still only available from 2026-08-06, so the 1M-confirmation
evidence is absent before that date — honestly reported as "no M1 data", never fabricated).

**Sampling:** every 3rd M15 bar (45 minutes), 10,936 snapshots, each evaluated exactly as
`evaluate(frames, now)` is called in production (closed candles only, no lookahead).

**Dataset audit (section 2 of the request) — result: no problems found.**

- Distinct setup IDs (`direction:sweep_time`): 350. No duplicates (groups are keyed by this ID by
  construction; checked programmatically — none found).
- No duplicate as-of timestamps within any single setup's own snapshot history — checked, none found.
- No lookahead: every outcome-replay bar used is strictly after the setup's own `record_time_utc`
  (enforced by `m5[m5.time > t0]`); checked across every signal (see below) — 0 violations.
- No forming-candle leakage: `evaluate()` closes every frame before use (already covered by the
  hardening stage's `test_forming_candle_never_changes_the_result`); re-confirmed here by construction
  since the extraction calls the same `evaluate()`.
- MFE/MAE computed only after the entry point: enforced by `label_outcome()`'s own replay loop,
  which only ever sees bars from `path` (strictly after `record_time_utc`).
- Entry/stop/target preserved correctly: spot-checked — every would-be "signal" record carries a
  non-null entry price, consistent with its state; 0 signals in this run lacked one (there were also
  0 signals at all — see section 4).
- Aborted/invalidated/expired are distinguishable from completed: `state`/`outcome_status` fields
  are disjoint and present on every record with a sweep.
- Missing values handled explicitly: no `NaN` found in any numeric outcome field across the dataset
  (checked with `np.isnan`); all "unknown" values are Python `None`, never a silently-propagated NaN
  (the specific failure mode flagged as a past project risk).
- Direction preserved: every snapshot's `direction` field matches its own `setup_id` prefix — checked,
  0 mismatches.
- Timeframe evidence preserved: every tracked snapshot carries its `timeframes` dict — checked, 0 missing.

Raw totals: 10,936 snapshots, of which 9,639 never had a sweep yet (NO_SETUP 8,879 + HTF_ALIGNED 760)
and 1,297 did (350 distinct sweeps, long 210 / short 140).

## 3. Outcome definitions used

Only the existing, already-built definitions (`analysis/entry_model/outcome.py`) are used — no new
outcome definition was invented:

- **`target_hit` / `stop_hit`**: the first of the setup's own plan (stop) or first target to be
  touched by a closed-bar high/low on the M5 path after the record time. Both touched on the same
  bar resolve to the stop (conservative).
- **`outcome_r`**: `+reward/risk` if the target was hit, `-1.0` if the stop was hit, else `None`
  (never fabricated for an unresolved setup).
- **MFE / MAE**: the best/worst excursion from entry, in price and in R, tracked every bar up to
  resolution (or to the end of available history).
- **Horizon**: unbounded — the replay runs until the stop or target is hit or the available M5
  history (up to 2026-10-06) runs out. No fixed time horizon was imposed, since the model's own plan
  (not an external horizon) defines the exit.

## 4. Baseline performance — **cannot be computed**

**Zero setups reached a state with an entry plan (`ENTRY_CONFIRMATION` or `ENTRY_READY`), at any of
the four tested windows (4, 6, 8, or 12 M15 bars), across all 350 tracked sweeps over 17 months.**

| Window (M15 bars) | Tracked sweeps | Signals (entry plan) | Resolved outcomes |
|---|---|---|---|
| 4 | 350 | 0 | 0 |
| 6 | 350 | 0 | 0 |
| 8 (frozen production) | 350 | 0 | 0 |
| 12 | 350 | 0 | 0 |

There is no win rate, average R, expectancy, drawdown, or MFE/MAE distribution to report, because
there are no trades. This is reported here rather than silently worked around, per the instruction to
stop and report a data problem rather than fix it — except this is not a data problem, it is the
model's real, measured behaviour on real history. Section 6 explains exactly where the funnel stops.

## 5. Individual conditions

Because every ICT condition in this model (sweep → MSS → displacement → FVG → retracement → 5M
confirmation) is a **sequential gate**, not an independent feature, "outcome rate" or "average R" of
a condition cannot be computed before the final gate (an entry), because there is no trade before
that point. What **can** be measured for a gate is how many tracked sweeps ever satisfy it
(occurrence rate) — that is section 6's funnel, which is the right way to read this section's
request given the data. Three conditions that are *not* hard gates (so they can, in principle, be
compared against an outcome once one exists) are 1H context alignment, premium/discount, and event
ordering — none have an outcome to attach to yet either, for the same reason.

Descriptive (non-outcome) rates, over the 350 tracked sweeps, within the frozen 8-bar window:

| Condition | Occurrence | Rate of sweeps |
|---|---|---|
| Swept (tracked within 8 bars) | 210 / 350 | 60% |
| → MSS confirmed | 54 / 210 | 26% |
| → + Displacement confirmed | 24 / 210 | 11% |
| → + FVG formed | 14 / 210 | 7% |
| → + Retracement into the FVG | 11 / 210 | 5% |
| → + 5M confirmation | ~0 / 210 (see section 6) | ~0% |

(140 of the 350 sweeps were first observed by this 45-minute sampling only after they were already
more than 8 bars old — a sampling-resolution gap, not a real-world absence of a sweep; see
*Limitations*, section 17 below. The "210" denominator above is the sweeps actually observed fresh.)

## 6. Incremental value — the funnel (this is the most important result)

Nested conversion, over the 210 sweeps observed fresh within the frozen 8-bar window:

```text
Sweep                          210  (100%)
Sweep + MSS                     54  ( 26%)
Sweep + MSS + Displacement      24  ( 11%)
+ FVG                            14  (  7%)
+ Retracement into the FVG      11  (  5%)
+ 5M confirmation                 0*  (0%)   <-- the funnel ends here, never once in 17 months
```

\* The *conversion funnel* counter (which OR's `confirm5` across every snapshot of a setup, not
necessarily at the same moment as retracement) found exactly **one** snapshot, across all 350
setups, where `confirm5` was ever `True` — and it was not the same setup/moment as any of the 11
retracement cases. **In every one of the 11 setups that reached retracement, the "5M confirmation"
checklist item was still `WAITING` at that exact moment** (verified directly from each one's own
checklist — see `entry_research_diagnostics.json`).

This is a genuine, well-evidenced structural finding, not a small-sample artifact of one or two
setups: **the conjunction this model requires for an entry — price currently sitting back inside the
M15 FVG *and* a fresh M5 structure shift at or after that exact retest — did not co-occur even once**
in 210 freshly-observed sweeps over 17 months of real XAUUSD M15/M5 data. A plausible mechanism (not
proven, offered as a hypothesis): M5 structure shifts take a number of M5 bars to confirm, and by the
time one arrives, price has typically already moved out of (or traded through) the M15 FVG, so
`retrace_ok` is no longer true on the same snapshot.

Sample efficiency cost of each gate (how much of the funnel each one discards): MSS discards 74% of
sweeps, displacement discards a further 15 points, FVG a further 4, retracement a further 2 — all
large but individually plausible costs for a disciplined ICT sequence. The 5M-confirmation gate is
different in kind: it discards effectively 100% of what reaches it. That makes it the dominant,
structural bottleneck of the entire model, not merely the smallest-sample gate.

The second funnel the spec asks for (HTF alignment + sweep + MSS + displacement + FVG, read at the
population/snapshot level rather than per-sweep) is the snapshot-state distribution already reported
in the hardening stage and reproduced per-window in section 9 below.

## 7. Interaction analysis — insufficient sample

With zero entries, no interaction pair (HTF×sweep, sweep×MSS, MSS×displacement, displacement×FVG,
FVG×OTE, S/D×sweep, S/R×sweep, 5M×1M, …) has an outcome to condition on. The only interaction that
*can* be read from the data as collected is the one in section 6 (retracement × 5M confirmation),
and it is already the central finding above.

## 8. Event ordering

Measured over every snapshot where both MSS and displacement were confirmed (31 ordered snapshots,
not gated on reaching an entry, since ordering is a structural fact independent of the entry gate):

| Ordering | Count | Share |
|---|---|---|
| SIMULTANEOUS | 21 | 68% |
| DISPLACEMENT_FIRST | 8 | 26% |
| MSS_FIRST | 2 | 6% |

Consistent with the hardening stage's smaller sample: simultaneous sweep/structure-shift/displacement
is the dominant real pattern, not the rare case. Of these, the sweep bar was itself the MSS bar in 9
cases and the displacement bar in 13 — both common, confirming the earlier finding that treating
"sweep == displacement bar" as the exception would have been wrong. **No outcome-rate comparison
across orderings is possible (no entries), so no ordering can be called superior — this is a
descriptive result only, not a predictive one.**

## 9. Sweep-window sensitivity (offline, research-only; production is unchanged at 8 bars)

Reconstructed at the **snapshot level** (every snapshot reclassified as `EXPIRED` if its own sweep
age exceeds the window, else its actual computed state — this avoids the sampling-gap artifact that
affects setup-level "first-observed" tables; see *Limitations*):

| State | W=4 | W=6 | W=8 (frozen) | W=12 |
|---|---|---|---|---|
| EXPIRED | 993 | 872 | 758 | 516 |
| LIQUIDITY_SWEPT | 255 | 340 | 409 | 559 |
| MSS_CONFIRMED | 26 | 44 | 66 | 110 |
| DISPLACEMENT_CONFIRMED | 12 | 18 | 26 | 42 |
| RETRACEMENT_WAITING | 7 | 15 | 24 | 44 |
| INVALIDATED | 4 | 8 | 14 | 26 |
| ENTRY_CONFIRMATION / ENTRY_READY | 0 | 0 | 0 | 0 |

Widening the window monotonically shifts mass from EXPIRED into every later state — a real,
reproducible sensitivity, not noise. But **it never produces a single entry at any width tested**.
Widening the window further is not a fix for the finding in section 6 (the bottleneck is the
*simultaneity* of retracement and 5M confirmation, not the sweep's own freshness) — a window of 20 or
50 bars would still have to pass through the same near-zero conjunction. This is reported as a
sensitivity result, not a recommendation to widen the window (doing so was explicitly out of scope
and would not address the actual bottleneck).

## 10. 1M confirmation — cannot be evaluated; gated behind a condition that never fires

`confirm1` was `True` in exactly 0 of 10,936 snapshots. It cannot be compared (5M-only vs 5M+1M)
because the 5M-only population it would be compared against is itself empty. This is not evidence
that 1M confirmation is useless — it is evidence that the question is unreachable while the 5M gate
in section 6 remains the binding constraint. Revisit after that gate is addressed.

## 11. OTE analysis

Measured over every snapshot where OTE was computable (displacement confirmed with a valid impulse):

| OTE overlap | Count |
|---|---|
| NOT_APPLICABLE (no displacement/impulse yet) | 26 |
| NONE | 14 |
| PARTIAL | 10 |
| FULL | 0 |

**`FULL` overlap (the FVG sitting entirely inside the 0.62–0.79 retracement band) was never observed,
even once, across 17 months.** `PARTIAL` was less common than `NONE`. Purely descriptively (no
outcome data exists to test whether OTE overlap would have improved results), OTE as currently
computed appears to rarely confirm strongly in real gold price action at this timeframe combination —
consistent with the plan document's original caveat that OTE is "an ICT convention, not validated,"
now with a measured (not assumed) rarity to go with that caveat.

## 12. Supply/Demand and S/R

Among the 24 snapshots where an FVG existed, a key area (supply/demand/S-R, from `build_key_areas`)
overlapped it in 20 (83%). This is a high co-occurrence rate. With no outcome data, it cannot be
called "useful" or "redundant" in a predictive sense — but descriptively, a condition that is true
on 83% of the population it's checked against carries little information to *discriminate* outcomes
even if real outcomes existed, simply because it is nearly always true once an FVG exists. This is
flagged as a plausible **redundancy candidate** for the next research pass, to be confirmed only once
real outcomes exist to test it against.

## 13–15. Statistical methodology, train/validation/OOS, walk-forward

Wilson score intervals, percentile bootstrap, and plain OLS (`numpy.linalg.lstsq`; no scipy/sklearn/
statsmodels are installed in this environment) were implemented and ready to run (see
`research_stats.py`), with a minimum-sample threshold of 10 before any comparison is interpreted —
but **none of sections 13–15 can be executed on zero outcomes.** No chronological split, no
walk-forward windowing, and no regression was run, because there is no dependent variable. Building
and testing the statistical harness on an empty dependent variable would produce numbers that look
like results but mean nothing; per the instruction to avoid overfitting and not force a conclusion,
none are reported.

## 16. Overfitting avoidance — what was deliberately *not* done

- Thresholds, gates, windows (other than the explicitly-requested 4/6/8/12 offline comparison, not
  applied to production), confidence weights, and entry rules were not changed.
- The sweep window was not widened in production to manufacture entries, even though section 9 shows
  that would not have produced any anyway.
- No condition was removed, no "inconvenient" period discarded, no setup cherry-picked.
- Only one extraction was run per window-reconstruction need; no repeated searching over parameter
  combinations to find a configuration that produces trades.

## 17. Limitations

- **Sampling resolution.** Snapshots were taken every 45 minutes (every 3rd M15 bar), not every M5
  bar. Section 6's central finding (5M confirmation essentially never coincides with retracement) is
  based on the states visible at that cadence. A brief, single-M5-bar coincidence between retests
  could in principle be missed between samples. This is a real limitation, not dismissed: the
  recommended next step (section 19) is a finer-resolution (every M5 bar) re-run focused specifically
  on this gate before concluding anything stronger than "not observed at 45-minute resolution."
- **Sampling-gap artifact on setup-level tables.** 140 of 350 tracked sweeps were first observed by
  this cadence only after they were already more than 8 bars old, which would misclassify them as
  "expired" in a naive first-seen table. Section 9's table is built at the snapshot level specifically
  to avoid this; section 5's funnel denominator (210) excludes those 140 sweeps rather than silently
  miscounting them.
- **M1 history is short** (from 2026-08-06 only), so 1M confirmation could not even be assessed in
  roughly 15 of the 17 months — moot in any case, since 5M confirmation (its prerequisite) never fired.
- **No outcome data exists**, so sections 4, 7, 10 (comparative part), 11 (comparative part), 12
  (comparative part), 13, 14, and 15 could not be executed, only described structurally.
- Confidence scores were observed in the range 20–82 (mean 32.2) across 525 scored snapshots —
  descriptive only; confidence remains uncalibrated and is not evidence of anything predictive.

## 18. Classification

| Condition | Classification | Basis |
|---|---|---|
| HTF (1D+4H) alignment, sweep, MSS, displacement, FVG, retracement | **Insufficient sample** (for predictive value) | Required gates; no outcome data exists to test them against; occurrence rates only |
| 5M confirmation (as currently defined) | **Negative / structural bottleneck** | Never co-occurs with retracement in 210 fresh sweeps over 17 months — actively prevents any entry |
| Event ordering (SIMULTANEOUS dominant) | **Insufficient sample** (for predictive value) | Real, measured distribution; no outcome link possible yet |
| OTE | **Promising but uncertain, leaning weak** | FULL overlap never observed; PARTIAL rarer than NONE; no outcome data |
| Supply/Demand & S/R (key areas) | **Redundant candidate** | 83% co-occurrence with FVG; likely low marginal information even once outcomes exist |
| 1M confirmation | **Insufficient sample** | Never reached; gated entirely behind the 5M bottleneck |
| Confidence score | **Heuristic / uncalibrated** (unchanged) | Descriptive range only, 20–82; no outcome link |

No condition is classified "Strong evidence" — none could be, with zero outcomes.

## 19. Proposed Entry Model V2 hypothesis — not implemented, not proven

```text
HTF alignment (1D + 4H)
+
Liquidity sweep (15M)
+
MSS + Displacement (either order, including same-bar)
+
FVG formed
+
[HYPOTHESIS, NOT PROVEN] a redefined, less time-sensitive "execution confirmation" step that does
   not require a fresh M5 structure shift to land on the exact same snapshot as the FVG retest --
   e.g. a confirmation window spanning several M5 bars after the retest, rather than requiring both
   facts to be true simultaneously
+
Retracement into the FVG
+
[OPTIONAL, UNVALIDATED] 1M confirmation, re-evaluated only once the step above can fire at all
```

Everything above the "[HYPOTHESIS]" line is **observed and structurally supported** by this
research (the funnel in section 6). The bracketed step is a **hypothesis only**: this research
identifies *where* the model breaks down, not what the correct fix is, and no change has been made
to validate one. OTE and 1M confirmation are marked optional/unvalidated per sections 11 and 10.

## 20. Has an edge been demonstrated?

**No — and it could not be evaluated either way.** Entry Model V1, run exactly as frozen and
validated, over 17 months of real XAUUSD history (350 tracked liquidity sweeps, 10,936 snapshots),
produced **zero completed entries** at the production window (8 M15 bars) and at every offline
comparison window tested (4, 6, 12 bars). With zero trades there is no win rate, no R-multiple, no
expectancy, and no statistically valid basis — positive or negative — for a profitability claim.
What this research *does* demonstrate, with real evidence, is exactly where the model's funnel
collapses (5M confirmation never coinciding with FVG retracement) and several descriptive facts
about the ICT conditions it uses (event ordering, OTE rarity, key-area redundancy) that should guide
the next research iteration rather than a premature statistical claim on this one.
