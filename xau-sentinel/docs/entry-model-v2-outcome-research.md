# Entry Model V2: outcome research on the frozen Top-Down Multi-Timeframe model

Research only. No line of `analysis/entry_model/hierarchy.py` (or any of its layer modules), `config.py`,
A+, V2, Risk, or MT5 integration was changed to produce this report. Every number comes from a
read-only extraction and analysis pipeline (kept outside the repo, in the session scratchpad) run
against the same real XAUUSD MT5 history as the prior research.

## 1. Objective

Determine whether the frozen Entry Model V2 produces historically meaningful entry candidates, and
audit the hierarchy's own logic for structural problems — without tuning anything.

## 2. Frozen model definition

Exactly `analysis/entry_model/hierarchy.py` as built and validated previously
(`docs/entry-model-v2-hierarchy.md`): 1D+4H location/context → 1H bias → 15M setup → 5M confirmation
→ 1M precision → entry candidate. No threshold, weight, or decision rule was touched for this stage.

## 3. Dataset

Same `raw_big.pkl` (M5/M15/H1/H4)/`raw_entry_extra.pkl` (D1/M1) pickles, same UTC timestamps, same
closed-candle convention, same ~17-month window (2025-05-16 to 2026-10-05), same sampling (every
50th M15 bar, 400 samples) as the prior V2 validation run.

**Reproduction check — exact match:**

| State | Previous run | This run |
|---|---|---|
| CONFLICTED | 182 | 182 |
| HTF_LOCATION_IDENTIFIED | 119 | 119 |
| EXPIRED | 59 | 59 |
| HTF_CONTEXT_ALIGNED | 23 | 23 |
| INVALIDATED | 11 | 11 |
| ENTRY_READY | 4 | 4 |
| ENTRY_CONFIRMED | 1 | 1 |
| ENTRY_CONFIRMATION_DEVELOPING | 1 | 1 |

Bit-for-bit identical. The frozen model is fully deterministic; no investigation was needed.

## 4. Candidate extraction

All samples reaching `ENTRY_CONFIRMATION_DEVELOPING`, `ENTRY_CONFIRMED`, or `ENTRY_READY` — **6
candidates total**, not only the 4 `ENTRY_READY` ones. Each `setup_id` is `{direction}:{as_of}`.

## 5. Candidate table

| setup_id | state | entry | stop | target | R:R | tradeable | confidence |
|---|---|---|---|---|---|---|---|
| SHORT:2025-05-29T00:10 | ENTRY_READY | 3260.78 | 3303.37 | 3256.48 | 0.10 | yes | 52 |
| LONG:2025-06-12T20:10 | ENTRY_READY | 3388.99 | 3377.80 | 3399.05 | 0.89 | yes | 41 |
| LONG:2025-06-15T23:10 | ENTRY_CONFIRMED | 3447.39 | 3428.68 | — | — | **no (no target)** | 51 |
| LONG:2025-12-19T09:25 | ENTRY_CONFIRMATION_DEVELOPING | — | — | — | — | **no (no entry/stop/target)** | 55 |
| LONG:2025-12-23T00:55 | ENTRY_READY | 4470.53 | 4431.42 | 4470.61 | 0.00 | yes | 61 |
| LONG:2026-01-15T21:55 | ENTRY_READY | 4615.67 | 4600.46 | 4618.19 | 0.16 | yes | 46 |

4 of 6 are tradeable (a full entry/stop/target). The other 2 are correctly labeled
`UNTRADEABLE / INCOMPLETE` rather than having a value invented — `ENTRY_CONFIRMED` means a stop
exists but no qualifying opposing target was found yet; `ENTRY_CONFIRMATION_DEVELOPING` has neither,
by the model's own definition of that state.

5 of 6 are LONG, 1 SHORT — too few to read as a directional bias of the model itself.

## 6. Outcome methodology

Reuses `analysis.entry_model.outcome.label_outcome()` exactly as it exists — no new outcome
definition. **Fixed-horizon** outcomes use `max_bars` (5/10/20/50/100 closed M5 bars); **first-event**
outcomes use `max_bars=None` (resolves at target, stop, or the end of available history, whichever
comes first). Both are reported per candidate, clearly labeled.

## 7. Candidate-level outcomes

| setup_id | first event | outcome_R | MFE | MAE | time to event |
|---|---|---|---|---|---|
| SHORT:2025-05-29T00:10 | TARGET_HIT | 0.10 | 6.96 | 0.57 | 5 min |
| LONG:2025-06-12T20:10 | TARGET_HIT | 0.90 | 14.20 | 9.36 | 3h 50min |
| LONG:2025-12-23T00:55 | TARGET_HIT | 0.00 | 10.03 | 0.11 | 5 min |
| LONG:2026-01-15T21:55 | TARGET_HIT | 0.17 | 4.05 | 0.00 | 1h 05min |

**Fixed-horizon detail** (only the one non-trivial case changes across horizons): LONG:2025-06-12
reads `STILL_OPEN` at 5, 10, and 20 bars (MAE growing to 9.36 by bar 20) and only resolves
`TARGET_HIT` by the 50-bar horizon — correctly distinguishing "no event yet within this window" from
"resolved." The other three target-hit within 1-13 bars, so every fixed horizon agrees with the
first-event result for them.

## 8. Aggregate results (n=4 tradeable — explicitly too small to generalize)

- Win rate (R > 0): 75% (3/4), 95% CI **[30%, 95%]** — the interval itself shows how little this
  tells us.
- Mean R: 0.29, 95% CI **[0.04, 0.70]**. Median R: 0.14.
- No stop was hit in this sample (0 losses), so profit factor is undefined (no denominator).
- Mean MFE 8.81, mean MAE 2.51 (price units, n=4).

**These numbers are flagged `insufficient` by the same minimum-sample threshold (n≥10) used in the
V1 research** — reported for completeness, not as evidence of anything. Three of the four
"wins" (0.10R, 0.00R, 0.17R) resolved in 5 minutes to just over an hour because the reused
`ai.strategy.rules.select_target` found an opposing qualifying level barely beyond entry — a real,
observable property of this sample, not a flaw introduced for this report. Only one candidate
(0.90R, resolved in 3h50m with real adverse excursion along the way) looks like a substantive trade
by any reasonable reading. **A naive "target-hit rate" of 100% would overstate this sample badly;
reading `outcome_R` is what reveals that most of it is close to break-even.**

## 9. Stage-by-stage comparison

| Stage | n in this run | Metric |
|---|---|---|
| HTF_CONTEXT_ALIGNED | 23 | price drift (not R — no stop exists yet), signed by context direction |
| SETUP_DEVELOPING | 0 | **INSUFFICIENT DATA** |
| SETUP_CONFIRMED | 0 | **INSUFFICIENT DATA** (every sample that reached setup confirmation in this run also reached a later, qualifying state) |
| ENTRY_CONFIRMATION_DEVELOPING / ENTRY_CONFIRMED / ENTRY_READY | 6 | real R-multiple (section 8) |

`HTF_CONTEXT_ALIGNED` price drift (mean, signed favorable, raw price units — no risk defined yet so
not comparable in magnitude to the R-multiples above):

| Horizon (M5 bars) | n | Mean drift | Median drift |
|---|---|---|---|
| 5 | 23 | +4.03 | +2.73 |
| 10 | 23 | +5.28 | +1.83 |
| 20 | 23 | +9.16 | +7.95 |
| 50 | 23 | +9.32 | +10.01 |
| 100 | 23 | +6.55 | +8.00 |

Directionally positive at every horizon in this descriptive sample — a tentative signal that simply
being in an aligned HTF context correlates with favorable subsequent drift, **not a claim of an edge**
(n=23, no risk normalization, not independently validated). The middle of the funnel
(`SETUP_DEVELOPING`/`SETUP_CONFIRMED` as a *terminal* state) cannot be compared at all here: in this
400-sample run, nothing stopped at those two states — everything that reached `SETUP_CONFIRMED` also
reached a later, qualifying state by the time it was sampled.

## 10. 1M precision analysis

**0 of the 6 candidates ever had `precision_1m.precision_status == "AVAILABLE"`.** The split requested
(with vs without 1M precision) is **INSUFFICIENT DATA** by construction — there is no "with precision"
group to compare against. No conclusion about 1M precision's value can be drawn from this sample,
positive or negative.

## 11. CONFLICTED analysis (182 / 400 = 45.5%)

Every `CONFLICTED` sample was re-examined by re-deriving the 15M evidence categories fresh (not just
reading the stored summary, since a `CONFLICTED` 15M record does not store which categories tied):

| Reason | Count | Share |
|---|---|---|
| 1H vs 15M disagreement (15M majority opposes the established 1H bias) | 95 | 52% |
| 15M evidence tie (equal bullish/bearish category count) | 51 | 28% |
| 15M vs 5M disagreement (5M majority opposes the 15M setup direction) | 25 | 14% |
| HTF vs 1H disagreement (1H bias incompatible with 1D/4H context) | 11 | 6% |

**Reading:** the largest share (52%) is the 15M layer's own evidence outvoting an already-established
1H bias — by design this is reported as `CONFLICTED` rather than silently overriding the higher
timeframe, so this is the hierarchy's safety rule firing as intended, not obviously a defect. The
second-largest (28%, ties) is closer to **noisy evidence**: a 1-vs-1 category tie is a coin-flip
outcome of discrete evidence counting, not necessarily a real market disagreement — a plausible
target for a future, more graduated conflict rule (not changed here). The smallest categories (5M-vs-
15M, 14%; HTF-vs-1H, 6%) look like genuine, infrequent cross-timeframe disagreement. None of this was
classified as an implementation defect in the sense of "a bug producing a wrong answer" — section 13
reports a related but distinct and more serious finding.

## 12. Hierarchy audit — a structural finding

**The top-level `direction` field is not gated by `state`.** `hierarchy.evaluate()` sets
`direction = setup["setup_direction"]` directly from the 15M layer's own resolution, and returns it
unconditionally — regardless of whether `state` has actually progressed past the HTF/1H layers.

Checked across all 400 samples: **142 (35.5%) have a resolved `direction` of `LONG` or `SHORT` while
`state` is still `HTF_LOCATION_IDENTIFIED` or `HTF_CONTEXT_ALIGNED`** — meaning the 1D/4H layer has
not even agreed on a bias (`HTF_LOCATION_IDENTIFIED`) or the 1H layer has not been accepted as
compatible (`HTF_CONTEXT_ALIGNED` without advancing), yet the output's own `direction` field reads as
confidently as it would at `ENTRY_READY`. Example: `2025-05-20 21:00` reads
`state=HTF_LOCATION_IDENTIFIED, direction=SHORT, setup_status=SETUP_CONFIRMED` — a fully-confirmed
15M setup sitting underneath a `state` that says the hierarchy hasn't even settled on a higher-
timeframe bias yet.

The root cause: `setup_15m.evaluate_setup()`'s own direction gate checks only `intraday_bias` (1H),
never `htf_context` (1D/4H) or `intraday["compatible_with_htf"]` — so a 15M setup can fully confirm a
direction that the 1H layer itself holds only because 1D and 4H never agreed with each other, or where
1H is already flagged incompatible with HTF. `state` is correctly capped by the ladder logic in
`hierarchy.py` (it never advances past `HTF_CONTEXT_ALIGNED` without `compatible_with_htf`), but
`direction` carries no equivalent gate, and a consumer that reads `direction` without also checking
`state` would see a confident call that the hierarchy itself has not endorsed.

This is a genuine case of **a lower timeframe's evidence effectively bypassing a higher timeframe's
gate** — not through the conflict-resolution vote (section 11's majority rule, audited separately and
not found to be the problem here), but through a field that simply does not consult the ladder at all.
**V2.1 hypothesis (not implemented):** either (a) set `direction = None` whenever `state` has not
reached at least `INTRADAY_BIAS_ESTABLISHED`, or (b) pass `htf_context`/`compatible_with_htf` into
`evaluate_setup()` so the 15M layer's own gate reflects the full hierarchy, not just 1H. Either fix is
small and localized; neither was made here.

## 13. Statistical limitations

- 6 qualifying candidates, 4 tradeable, over 400 samples / ~17 months: far too few for any
  profitability claim. Every aggregate stat above is explicitly flagged `insufficient` (n < 10).
- No chronological train/validation/OOS split was performed — the sample is too small to split at
  all without making each piece meaningless.
- No threshold, weight, or rule was tuned on this sample, and none should be until a materially
  larger candidate population exists.
- The `HTF_CONTEXT_ALIGNED` price-drift numbers (n=23) are directionally suggestive but have no
  risk normalization and were not cross-checked against an independent window.

## 14. Manual validation

`ENTRY_READY`/`ENTRY_CONFIRMED` candidates were checked against the raw M5 candles around their
timestamp (not just the model's own stored output):

- **LONG:2025-06-12T20:10** — entry 3388.99 matches the M5 close at that exact bar; stop 3377.80 and
  target 3399.05 sit outside the immediately visible 2-hour window (consistent with "beyond the
  nearest confirmed M15 swing" / "nearest opposing qualifying level", not implausible values); price
  actually chopped down to the 3385-3386 area for the next 45 minutes (matching the recorded MAE of
  9.36) before eventually reaching the target 3h50m later. This is a coherent, traceable sequence.
- **SHORT:2025-05-29T00:10** — entry 3260.78 matches the M5 close exactly; the very next bar
  (00:15) has a low of 3253.83, well through the 3256.48 target, confirming the 5-minute
  `TARGET_HIT` is a real wick-touch, not an artifact. The stop (3303.37) is a large, genuine distance
  away (a volatile dump had just occurred). Mechanically correct — but exactly the degenerate-R:R
  case flagged in section 8: the target itself was only ~4.3 points from entry against a ~42-point
  stop.

Both chronologies are sound and traceable to raw data. No fabricated or implausible value was found
in either candidate.

## 15. Conclusion

**A. Does V2 currently show evidence of useful entry candidates?**
`PROMISING — preliminary evidence only, and mostly because of one candidate.` 4 tradeable candidates
in 17 months, 3 of them near break-even by construction (trivial targets), 1 genuinely substantive
(0.90R, real time and drawdown). This is not enough to call V2 useful or not useful yet.

**B. Are the historical outcomes promising, neutral, negative, or insufficient?**
`INSUFFICIENT DATA` for a probability/edge claim (n=4). Descriptively `NEUTRAL-TO-PROMISING`: no
losses in this sample, but the win sizes are mostly trivial, and the sample is far too small to
generalize either way.

**C. Which hierarchy stages appear useful?**
`HTF_CONTEXT_ALIGNED` shows a directionally favorable descriptive drift (n=23) — tentatively useful
as a filter, not proven. `SETUP_DEVELOPING`/`SETUP_CONFIRMED` cannot be judged as standalone filters
in this run (no samples terminated there). The final three states correctly produced the only
tradeable candidates found.

**D. Does 1M precision appear useful?**
`INSUFFICIENT DATA` — it never became available for any of the 6 candidates. No comparison exists to
support or refute its value.

**E. Why are so many cases CONFLICTED?**
52% is the hierarchy's own safety rule (15M evidence outvoting an established 1H bias, correctly
reported rather than silently overridden) — working as designed, not obviously a defect. 28% is a
near-coin-flip tie in discrete evidence counting — closer to noisy evidence than genuine
disagreement, and a plausible target for a future, more graduated rule. The remaining 20% (5M-vs-15M,
HTF-vs-1H) look like genuine, infrequent cross-timeframe disagreement.

**F. What should be researched next?**
1. Fix (in a separate, explicitly authorized change) the `direction`/`state` gating gap in section 12
   before trusting `direction` anywhere it is read without `state`.
2. Accumulate more M1 history so 1M precision can be evaluated at all.
3. Re-run this same outcome pipeline over a materially larger sample (a finer sampling cadence, or a
   longer history window) once more M1 data exists, specifically to grow the n=4 tradeable population
   before any statistical claim is attempted.
4. Investigate whether `select_target` should avoid near-zero-distance targets for this model
   specifically (a research question, not a production change) — three of four "wins" here were an
   artifact of exactly that.
