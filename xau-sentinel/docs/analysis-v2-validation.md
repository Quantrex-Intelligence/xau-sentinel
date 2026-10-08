# Analysis Engine V2: validation and audit fixes

Scope: the raw-MT5 audit of V2 market intelligence and the fixes made for its highest-priority findings.
No A+ rule, FundedNext rule, backtest method, LLM path or monitoring path was changed.

## Method

- Sample: 6,000 M5 XAUUSD bars (2026-09-04 to 2026-10-06, about one month), as-of times every 3 hours (153 samples, 150 with a usable price).
- Ground truth: raw MT5 bars. Each claim was re-derived from closed bars, not from V2's own output.
- The forming bar carries only its open price. Its high, low and close are future data at the as-of time and are never used.
- Before and after were measured with the same script on the same samples.

## Before and after

| Measure | Before | After |
|---|---|---|
| Events in the active stream | 7,078 | 3,062 |
| Events considered before per-tier caps | 7,078 | 3,655 |
| Tier-1 events (SWEEP, MSS, BOS, DISPLACEMENT) | 854 | 854 (0 lost) |
| Duplicate area events (same bar, kind, direction) | 816 copies, 133 samples | 0 |
| FVG events | 938 | 298 |
| FVG events already FILLED | 499 | 0 |
| Active FVG events (OPEN or RETESTED) | 439 | 298 |
| Active scenarios whose invalidation was already met | 48 samples | 0 |
| Scenarios marked INVALIDATED (kept, explicit) | not possible | 56 |
| Out-of-order sequences reported with MSS or displacement CONFIRMED | 4 | 0 |
| Out-of-order sequences still flagged in the evidence | 4 | 4 (guarded, see below) |
| Broken-level confluence leans | 494 | 225 |
| Samples with more than one broken-level lean on one side | 132 | 0 |
| Key-area states (all areas kept on the analysis) | 5,780 | 5,780 total, 992 active |
| RETEST events in the active stream | 1,031 | 390 |
| RETEST wording "returned to X" when the bar did not reach X | 567 | 0 |

Raw-truth checks that were not changed still pass on all samples: sweep confirmation, BOS and MSS replay, FVG three-candle condition and status labels, H1-pivot zone touches and zone width, Wilder ADX against the reference, price location, and forming-bar exclusion (events, relations, scenarios and narrative identical with and without the forming bar, 26 samples).

## What changed

- P0 (A+ safety): the bridge carries the chronology flag. `decide_from_facts` treats an out-of-order V2 sequence as unconfirmed: MSS, displacement and retracement do not pass. The V2 display marks the steps after the sweep as not reached. Regression tests: `tests/test_v2_validation_fixes.py`.
- P1 (scenarios): each scenario has structured invalidation checks. A scenario whose check is already met by the last closed M5 close is kept with state `INVALIDATED` and the reason. The forming bar is never used.
- P2 (dedupe): area events with the same bar, kind and direction collapse into one event. Every level is kept in `levels` and listed in the detail.
- P3 (prioritization): `analysis/v2/priority.py`. Tiers: 1 structure and liquidity, 2 nearby area relations, 3 volatility and range, 4 FVG. Within a tier: most recent first, then nearest to price. Caps: tier 1 = 16, tier 2 = 12, tier 3 = 6, tier 4 = 4. FILLED FVGs are not emitted.
- P4 (confluence): broken levels in the same direction become one lean per direction, with the levels in the detail. Opposite directions stay separate.
- P5 (key areas): active only within `ACTIVE_AREA_ATR = 3.0` of price. Distant areas stay on the analysis and are reported as `distant_key_area_count`.
- P6 (RETEST wording): "returned to X" only when the bar reached X. Otherwise "touched within 0.5 ATR of X". The detection tolerance is unchanged.
- P7 (supersession): a later opposite-direction state event on the same area supersedes an earlier one. The superseded record stays on the area as evidence and is excluded from the active stream.
- P8 (FVG bug): `size_atr` is reset for every gap. Regression tests use a monkeypatched NaN ATR.
- P9 (sweep buffer): unchanged. The unit inconsistency is documented in `config.py`.

## Round 2: sequence ordering and MSS ownership

- Both valid orders are accepted: structure shift then displacement, or displacement then structure shift. A same-bar case is labelled `SIMULTANEOUS`. The order is recorded on `MarketSequence.ordering`, in the sequence wording, in the API (`ordering`), and on `StrategyFacts.sequence_ordering`. A+ does not assume an order: the decision reads each step on its own bar, and its rules are unchanged.
- Chronology is still validated. A counted step before its sweep is invalid, and so is a retracement that is not strictly after both the structure shift and the displacement it measures. Invalid chronology is never confirmed evidence.
- MSS ownership: a structure-shift bar belongs to the most recent same-direction sweep at or before it. Other sweeps keep their evidence, but their structure shift reads as not reached, their retracement is not counted, and the API reports `mss_owner_time_utc`. Opposite-direction sweeps do not compete.

| Measure (153 samples, raw MT5) | Before | After |
|---|---|---|
| Extra claims on a shared structure-shift bar | 9 (7 bars, 7 samples) | 0 |
| Chronology violations (flag false) | 4 | 0 |
| Chronology leaks (a confirmed step before its sweep, or a retracement not after the structure shift and displacement) | 0 | 0 |
| Displacement-first sequences accepted as valid | 0 (rejected) | 2 |
| Sequences labelled MSS first / displacement first / simultaneous | not labelled | 5 / 2 / 5 |
| Raw-truth checker issues on sequences | 17 | 0 |

The four earlier chronology flags split as follows. Two were displacement-first sequences (2026-09-21 12:05 and 2026-10-05 12:05), which are now valid and labelled. The other two were earlier sweeps sharing a structure shift with a later sweep, so the shift now belongs to the later sweep.

## Round 3: genuine A+ cases and forming-price behaviour

Search: the largest raw MT5 history the broker returns, 99,000 M5 bars (2025-05-14 to 2026-10-06). The legacy A+ evaluator was run on every second M5 bar from 2025-06-01 (47,863 as-of times, 0 errors). A 10-minute step can miss an A+ that lasts under 10 minutes. The sweep window is 60 minutes, so every window is covered at that step.

- Genuine A+ ratings found: 15 as-of times, from 8 distinct candidate sweeps, 2025-06-03 to 2025-11-27. Both directions are represented (BUY 1, SELL 14).
- Legacy A+ and V2-fed A+ match on all 15 cases: rating, direction, criteria, missing conditions, invalidation, entry, stop, target, R:R, candidate sweep, and sequence facts. Sweeps and closed frames are identical.
- In all 15 cases the structure-shift bar and the displacement bar are the same bar (`SIMULTANEOUS`). MSS-first and displacement-first orders were not observed on a genuine A+ case, so they remain covered only by the earlier real-market samples and fixture tests.

Forming-price behaviour (verified, rule unchanged):

- Structure, sweeps, zones, sequences, events and areas use closed candles only. The forming bar's high and low were moved by 500 points on each of the 15 cases. Those facts are identical, and so is every decision field.
- The forming bar's price is used for entry, and only there. Entry equals the forming price rounded to cents on all 15 cases. Stop and target come from closed structure.
- R:R depends on entry, so it moves with the forming price. A +1.0 move in the forming close changed entry and R:R on all 15 cases. On 3 of them it also changed the Minimum R:R criterion, which dropped the rating from A+ to not A+. Both paths did the same. This is the existing rule, and it is a decision for you, not a V2 defect.

Final checks on this round (no production code changed): backend 1,678 passed; V2 and A+ subset 480 passed; frontend vitest 158 of 158, `tsc`, eslint and `next build` all exit 0; all 15 E2E checklists pass when run sequentially; raw-MT5 truth checks report no issues; shared-MSS claims and chronology leaks are zero.

## Residual issues and decisions needed

- Displacement before MSS: resolved in round 2. Both orders are valid, and V2 and the legacy path now agree on both (tested).
- Shared structure-shift bar: resolved in round 2 by ownership.
- A+ decision parity on raw history has not been measured. Parity is tested on fixtures only, so a raw-data comparison of legacy and V2 decisions is still needed before A+ use.
- Prioritization caps and the 3 ATR active distance are deterministic settings chosen for this change. They are reported, not tuned against outcomes.
- Sweep buffer `LIQUIDITY_SWEEP_BUFFER_PIPS = 0.5` is applied in price units, not ATR. Left unchanged until validated against MT5 data.
- Sample is about one month of M5 with 3-hour spacing. Nothing here measures predictive value.

## Readiness

- Read-only display: ready. The active stream, active key areas, labelled scenario states, and sequences with ordering and ownership are all measured on raw history.
- A+ consumption: not yet. The chronology and ownership rules are settled and tested, but A+ decision parity has not been measured on raw history, and the sample contains no live A+ setup.
- Automated downstream consumption: not ready. The sample is one month, nothing measures outcomes, and the caps and distance thresholds are settings, not validated values.
