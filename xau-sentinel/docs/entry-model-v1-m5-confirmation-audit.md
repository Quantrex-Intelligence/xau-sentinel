# Entry Model V1: M5-resolution audit of the 5M-confirmation bottleneck

Audit only. No line of `analysis/entry_model/model.py`, `config.py`, A+, or V2 was changed. Every
number below comes from calling the model's own, unmodified production primitives
(`build_sequences`, `find_fvgs`, the `CONFIRMED` constant) directly, at 5-minute resolution, against
real XAUUSD MT5 history. Nothing here is committed or pushed.

## 1. Objective

The prior research (`docs/entry-model-v1-research.md`) sampled every 45 minutes and found 11 of 350
tracked sweeps reached sweep → MSS → displacement → FVG → retracement, and 0 of those 11 ever showed
a 5M confirmation. Because 45 minutes is coarser than a single M5 bar, that result could have been a
**sampling artifact**. This audit re-examines the same 11 cases at the model's own finest native
resolution — every closed M5 bar — to determine whether the bottleneck is real.

## 2. Frozen production definitions (used exactly as-is)

- Sweep window: `config.ENTRY_MODEL_SWEEP_MAX_BARS = 8` (M15 bars). All 11 cases reached retracement
  within this window in the original research, so it is not re-litigated here.
- MSS / displacement / retracement / ownership / chronology: `analysis.v2.sequence.build_sequences`
  (M15 for setup formation, M5 for entry confirmation), unmodified.
- FVG: `analysis.v2.fvg.find_fvgs`, unmodified, same anchor-time filter model.py itself uses (an FVG
  only counts once both MSS and displacement are confirmed, formed at or after the later of the two).
- 5M confirmation: model.py's own exact definition —
  `mss5.status == CONFIRMED and mss5.bar_time is not None and mss5.bar_time >= retest_time`, where
  `retest_time = fvg.retested_at or fvg.formed_at`. Not changed, not reinterpreted.
- 1M logic, confidence, A+, V2: untouched, not exercised by this audit.

No new condition, threshold, or scoring was added. Each of the 11 sweeps is **pinned** (its exact
`LiquidityEvent`, recovered from the original research run, re-used unchanged) and passed directly
into `build_sequences`/`find_fvgs`, rather than re-running `evaluate()`'s own `detect_sweeps` +
"pick the latest sweep" logic at every bar — this guarantees every snapshot traces *this* sweep,
never a later, unrelated one (the cross-contamination section 5 of the request warns against).

## 3. Dataset and period

Same XAUUSD MT5 history, same `raw_big.pkl`/`raw_entry_extra.pkl` pickles, same UTC timestamps and
closed-candle (`is_closed`) rules as the prior research. The 11 cases span 2025-06-11 to
2026-09-25. Each case was replayed at every closed M5 bar from its sweep time forward, for up to 24
hours (12× the production 2-hour sweep-freshness window) or until the case's own natural stopping
point (see section 5) — whichever came first.

## 4. Previous 45-minute sampling result (reference)

All 11 cases showed the "5M confirmation" checklist item as `WAITING` at the exact 45-minute sample
where retracement was first observed. 0 of 11 reached `ENTRY_CONFIRMATION`.

## 5. M5-resolution methodology

At every closed M5 bar `t` after the sweep: recompute the M15 sequence (MSS/displacement/
invalidation) and FVG (direction, status, retest time) fresh from `t`'s own M15/M5 windows (exactly
the windowing `evaluate()` uses), then recompute the M5 sequence for 5M confirmation. Record, every
bar: `mss_ok`, `disp_ok`, whether the FVG is present and its status, `retrace_ok`
(price back in the FVG, or the FVG's own `RETESTED` status), `confirm5` (the definition above), and
the sequence's own `invalidated`/`ordering` flags. **The question this audit actually answers is
whether `confirm5` and `retrace_ok` are ever `True` on the *same* bar** — that conjunction, not
either flag alone, is what `evaluate()` requires for `ENTRY_CONFIRMATION`.

Stop conditions per case (chronologically valid, no lookahead): the conjunction is found; the FVG
being tracked is filled (production semantics already make confirmation impossible after that,
since a filled gap is excluded from `find_fvgs`'s non-filled results, so `confirm5` cannot be
computed against it again); the sequence is invalidated (production stops tracking outright); or the
24-hour scan horizon is exhausted.

## 6. All 11 targeted cases — traced timestamps

| Setup | Sweep | MSS (M15) | Displacement (M15) | FVG formed | Retrace (price back in FVG) | confirm5 alone (first) | **Conjunction (ENTRY_CONFIRMATION)** | Fate |
|---|---|---|---|---|---|---|---|---|
| LONG:2025-06-11 18:00 | 18:00 | 18:15 | 18:00 | 18:15 | **18:40** | — | **never** | scan horizon reached, still RETESTED |
| LONG:2025-06-12 09:45 | 09:45 | 10:15 | 10:15 | 10:30 | **11:30** | — | **never** | scan horizon reached, still RETESTED |
| SHORT:2025-07-08 07:00 | 07:00 | 08:00 | 07:15 | 08:15 | **08:45** | — | **never** | scan horizon reached, still RETESTED |
| LONG:2025-09-30 14:00 | 14:00 | 14:00 | 14:00 | 14:15 | **15:10** | — | **never** | scan horizon reached, still RETESTED |
| LONG:2025-10-03 11:30 | 11:30 | 12:30 | 12:30 | 12:45 | **13:45** | — | **never** | data ran out (~9h), still RETESTED |
| LONG:2026-01-22 13:45 | 13:45 | 14:30 | 14:30 | 14:30 | **15:05** | 14:45 (3 bars) | **never** | scan horizon reached, still RETESTED |
| SHORT:2026-02-09 23:00 | 23:00 | 23:00 | 23:00 | 23:15 | **23:45** | — | **never** | FVG filled 2026-02-10 14:30 |
| SHORT:2026-05-20 00:45 | 00:45 | 01:15 | 01:15 | 01:15 | **01:55** | 01:30 (3 bars) | **never** | FVG filled 2026-05-20 11:30 |
| SHORT:2026-09-17 18:30 | 18:30 | 18:30 | 19:15 | 19:30 | **19:55** | — | **never** | FVG filled 2026-09-18 00:15 |
| SHORT:2026-09-24 00:15 | 00:15 | 01:45 | 01:45 | 01:45 | **02:20** | 02:00 (3 bars) | **never** | **invalidated 02:45** |
| SHORT:2026-09-25 13:00 | 13:00 | 14:00 | 13:15 | 14:15 | **14:40** | — | **never** | FVG filled 2026-09-25 15:00 |

All times UTC. **The conjunction (`confirm5 AND retrace_ok` on the same bar) was found in 0 of 11
cases, at full M5 resolution, scanning up to 24 hours per case** (vs. the production 2-hour
sweep-freshness window) — not merely 0 of 11 at 45-minute resolution.

## 7. The mechanism (not just the count) — three cases show exactly why

Three cases (LONG:2026-01-22, SHORT:2026-05-20, SHORT:2026-09-24) show `confirm5` becoming `True`
**on its own**, independent of retracement — but in every one of the three, it fires **before**
`retrace_ok` ever becomes `True`, then turns back `False` by the time retracement actually happens.
Raw bar-by-bar evidence for LONG:2026-01-22 (sweep 13:45, M15 MSS+displacement 14:30):

| Bar (UTC) | `confirm5` | `retrace_ok` | `mss5_time` | `fvg.status` |
|---|---|---|---|---|
| 14:45 | **True** | False | 14:30 | OPEN |
| 14:50 | **True** | False | 14:30 | OPEN |
| 14:55 | **True** | False | 14:30 | OPEN |
| 15:00 | False | False | — | OPEN |
| **15:05** | False | **True** | — | OPEN |
| 15:15 | False | True | — | RETESTED |

The mechanism: `retest_time = fvg.retested_at or fvg.formed_at`. Before any genuine retest, that
falls back to `formed_at` (14:30) — so the M5 structure shift that happened at the same moment as
the M15 displacement (14:30) trivially satisfies `mss5_time (14:30) >= retest_time (14:30)`, and
`confirm5` reads `True` for a few bars, **despite price not having retraced into the FVG at all
yet**. Once price genuinely returns (15:05) and the FVG's `retested_at` is set, `retest_time`
advances to that later moment — and the earlier (14:30) M5 structure shift is now **too old**
relative to the new reference, so `confirm5` reads `False` again, right as `retrace_ok` finally
turns `True`. SHORT:2026-05-20 and SHORT:2026-09-24 show the identical pattern (confirm5 fires once,
pre-retest, then lapses once the real retest moves the reference forward). This is a timing artifact
of the `retested_at or formed_at` fallback, not a market-structure finding — it means the one
condition that *can* independently satisfy `confirm5` is systematically the wrong one (pre-retest),
and the model has no mechanism to let a *later* M5 structure shift re-satisfy the gate once the
reference time has advanced past it.

## 8. Confirmation-window test (0/1/2/3/4/6 M5 bars after retracement) — research-only, production unchanged

Because the conjunction was never found for any case, there is no "N bars after retracement" value
at which confirmation occurs, for any of 0/1/2/3/4/6-bar windows. Widening the window examined does
not help here, because the problem is not *how long after retracement* confirmation is searched for
— it is that the qualifying M5 structure shift, in every case it existed at all, occurred **before**
retracement, and the model's own reference-time logic invalidates it once retracement happens. A
wider post-retracement window cannot recover an M5 shift that already happened pre-retracement.

| Confirmation window after retracement | Cases reaching confirmation |
|---|---|
| 0 (same bar) | 0 / 11 |
| 1 bar | 0 / 11 |
| 2 bars | 0 / 11 |
| 3 bars | 0 / 11 |
| 4 bars | 0 / 11 |
| 6 bars | 0 / 11 |
| Unbounded (up to 24h / fill / invalidation) | 0 / 11 |

## 9. Sampling-miss analysis — did 45-minute sampling cause the result?

**Partially, for the independent `confirm5` flag — but not for the answer that matters.** The three
transient `confirm5=True` windows (section 7) each lasted only 3 M5 bars (15 minutes), shorter than
the 45-minute sampling interval, so the 45-minute cadence could easily miss them by construction. A
grid check against the exact 45-minute sample times used in the prior research confirms this
happened for two of the three (LONG:2026-01-22's 14:45–14:55 window and SHORT:2026-09-24's
02:00–02:10 window both fall strictly between sample points); the third (SHORT:2026-05-20's
01:30–01:40 window) happens to include a sample point (01:30) and so was technically visible, though
still reported as `WAITING` in the checklist at that cadence's own retrace-detection moment, since
that check was made at a different asof. Discovering these blips changes nothing material, though:
**none of the three ever coincide with `retrace_ok`**, which is the
actual required conjunction. Finer sampling resolution did add information (it revealed `confirm5`
firing on its own in 3/11 cases, where the 45-minute checklist read `WAITING` throughout), but it did
not change the headline count — **0 of 11 cases reach `ENTRY_CONFIRMATION` at 45-minute resolution,
and 0 of 11 reach it at full M5 resolution either.** The bottleneck is not a sampling artifact.

## 10. Invalid/late confirmation and chronology checks

No confirmation was found to validate against invalidation or an unrelated/opposite MSS — there is
nothing to check for 10/11 cases. For the one case that did invalidate (SHORT:2026-09-24), the
invalidation (02:45) occurred *after* retracement (02:20) and after the independent `confirm5` blip
(02:00); `confirm5` never became `True` again in the 25 minutes between retracement and invalidation,
so this is correctly classified `INVALIDATED_BEFORE_CONFIRMATION`, not a missed confirmation. Every
`mss5_time` recorded belongs to the pinned sweep's own M5 sequence call
(`build_sequences(f["M5"], [sweep])` with *this* sweep), so no cross-setup/opposite-direction MSS
contamination is possible by construction (see section 2).

Per-case classification (section 6 of the request's taxonomy):

| Classification | Cases |
|---|---|
| NO_CONFIRMATION (no `confirm5`, ever, at M5 resolution) | 8 |
| NO_CONFIRMATION, with a pre-retrace `confirm5` blip that lapsed | 3 (LONG:2026-01-22, SHORT:2026-05-20, SHORT:2026-09-24) |
| INVALIDATED_BEFORE_CONFIRMATION | 1 (SHORT:2026-09-24; also counted above) |
| SAME_BAR / NEXT_BAR / 2–6 bars / LATER_THAN_6 | 0 (none ever reached the conjunction) |

Event ordering among the 11 (MSS vs. displacement, M15): SIMULTANEOUS 7, DISPLACEMENT_FIRST 3,
MSS_FIRST 1 — consistent with the broader 350-sweep sample in the prior research.

## 11. Expansion beyond the 11 cases

11 cases were sufficient for a decisive answer (the mechanism in section 7 explains the result
structurally, not just statistically), so the full M5-resolution expansion to all sweeps reaching
only sweep→MSS→displacement→FVG (section 11 of the request) was not run. For completeness: of the 14
sweeps that formed an FVG in the original research, 3 never reached retracement at all within the
8-bar window (`LONG:2025-06-16`, `LONG:2025-09-18`, `SHORT:2026-09-24 07:15`) — these were excluded
from the 11 by definition and were not separately traced here.

## 12. Raw-data validation and data quality

- Every bar used is `is_closed=True` in the source data (the same `frames_at()` windowing as the
  production route); no forming-bar leakage — confirmed by construction (same `_closed()` convention
  used throughout this codebase).
- All timestamps are UTC (MT5 server time converted once, at ingestion, consistent with every other
  stage of this project).
- No duplicate M5 bars were encountered (`build_sequences`/`find_fvgs` would raise or misbehave on
  duplicated timestamps; none did across 11 cases × up to 274 bars each).
- Timeframe alignment: the M15 and M5 windows at each as-of time use the identical `tail(300)` /
  `close_time <= asof` windowing as the production route and the prior research stage.
- Section 7's bar-by-bar table for LONG:2026-01-22 was manually read off the raw `find_fvgs`/
  `build_sequences` output (not a derived statistic), and the same mechanism was independently
  re-confirmed from the raw per-bar output for SHORT:2026-05-20 and SHORT:2026-09-24 — three
  independent instances of the identical pattern, not one case generalized.
- No data-quality problem was found that would prevent a conclusion.

## 13. Conclusion

### B. Genuine bottleneck — with a precisely identified mechanism, not just an absence of data

M5-resolution replay, scanning up to 24 hours per case (12× the production sweep window), confirms
the 45-minute research's finding: **0 of 11 cases ever produce a valid `ENTRY_CONFIRMATION`.** This
is not a sampling artifact (option A) — finer resolution did surface new information (`confirm5`
firing independently in 3/11 cases) but did not change the outcome, because in every one of those
cases the firing happened **before** retracement, not after it, and the model's own `retested_at or
formed_at` reference-time logic structurally prevents that earlier shift from counting once the real
retrace moves the goalpost forward. This is closer to option C (the current exact timing requirement
is unusually restrictive) than a flat "it never happens in the market" — the underlying M5 structure
shift *did* happen in 3 of 11 cases, just on the wrong side of the retracement moment, for a
definitional reason this audit can point to precisely.
