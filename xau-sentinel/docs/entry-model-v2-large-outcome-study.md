# Entry Model V2: larger historical outcome study (post-direction-gating-fix baseline)

Research only. The frozen implementation (`analysis/entry_model/hierarchy.py` and its layers,
post direction/state gating fix) was not changed to produce this report — confirmed in section 1.
No threshold, entry condition, target rule, stop rule, or confidence weight was touched.

## 1. Freeze confirmation

Checked directly against the source before running anything:

- `hierarchy.py` still computes `exposed_direction` (gated on `confirmation_5m == CONFIRMED`,
  `CONFLICTED` preserved as a sentinel) — the direction-gating fix is active.
- `setup_15m.py` still has the `htf_ready` gate (1D/4H + 1H must agree before any direction).
- `precision_1m.py` is only ever consulted after 5M confirmation reaches `DEVELOPING`+, and its
  result is never read when constructing the entry candidate — 1M remains precision-only.
- `ai/strategy/rules.py` (target selection, stop/R:R) shows no diff against the prior stage —
  untouched.
- No A+ file (`ai/strategy/*`) was modified.

## 2. Dataset

Same real XAUUSD MT5 pickles (`raw_big.pkl`, `raw_entry_extra.pkl`) as every prior Entry Model
study — same broker/source, same UTC timestamps, same closed-candle convention. **M5 remains the
limiting required timeframe** (2025-05-14 to 2026-10-06, ~17 months) — this is already the largest
clean M5 history available; it was not possible to extend the window further without M5 data that
does not exist. What *was* increased: sampling density, from every 50th M15 bar (~12.5h, the prior
400-sample study) to **every 2nd M15 bar (~30 minutes) — 41x denser**, giving **16,449 evaluation
points** instead of 400. M1 remains available only from 2026-08-06 (~2 months), unchanged — a hard
data limitation, not a methodology choice.

No condition was loosened to produce more samples; this is the same frozen model, observed more
often, over the same real history.

## 3. Candidate funnel

| Stage | n | % of total | % of previous stage |
|---|---|---|---|
| All evaluation samples | 16,449 | 100% | — |
| HTF context resolved (1D+4H agree) | 3,105 | 18.9% | 18.9% |
| 1H direction established (and compatible with HTF) | 1,007 | 6.1% | 32.4% |
| 15M setup (developing or confirmed) | 367 | 2.2% | 36.4% |
| 5M confirmation (developing or confirmed) | 301 | 1.8% | 82.0% |
| 5M confirmation CONFIRMED | 258 | 1.6% | 85.7% |
| `ENTRY_READY` | 185 | 1.1% | 71.7% |
| Tradeable candidate (stop + target both resolved) | 187 | 1.1% | — |

(The last two rows are not a strict sub-funnel of each other — `ENTRY_CONFIRMED`/`PRECISION_
AVAILABLE` snapshots can also be tradeable without reaching `ENTRY_READY`'s exact label, hence 187
tradeable snapshots against 185 `ENTRY_READY` ones.)

After de-duplicating consecutive re-observations of the *same* persisting setup (same direction and
same stop price across adjacent samples — the same real-world candidate observed repeatedly at this
sampling density, not a new one each time):

- **152 distinct candidates**, of which **115 are genuinely tradeable** (both a deterministic stop
  and target).
- Rejected/incomplete, among samples that reached a confirmed direction: 44 never got an
  `entry_candidate` built at all (state capped before `ENTRY_CONFIRMED` in that snapshot), 27 had a
  stop but **no qualifying opposing zone for `select_target()`** — the target side of this model's
  reused primitive fails open (returns `None`, never a fabricated target) about as often as it
  succeeds with a usable value, for candidates that otherwise qualify.
- **LONG 83, SHORT 46, and 23 where direction read `None`/unresolved at the group's own defining
  snapshot** (a 15M setup or 5M-developing snapshot that never reached a resolved, confirmed
  direction — correctly inert under the gating fix, not an error).
- By month: spread across nearly the whole window (every month from 2025-05 to 2026-10 except
  2026-02, 2026-03, and 2026-06 show zero candidates) — ranging from 2 to 26 per month, no single
  month dominating.
- By session (of the candidate's own defining bar): New York 58, London 39, Off-session 28, Asian
  27 — plausible for XAUUSD's known liquidity pattern, not independently validated against a null
  model here.
- 1M precision was available for **41 of 152** candidates (27%).

## 4. Outcome study (n=115 tradeable candidates)

Deterministic forward replay, reusing `analysis.entry_model.outcome.label_outcome()` exactly as
built for the prior studies — no new outcome definition. First-event (unbounded) resolution:

- **Target-first: 75. Stop-first: 40. Unresolved/timeout: 0** (every candidate resolved within the
  available forward M5 history).
- Win rate (R > 0): **65.2%**, 95% CI **[56.2%, 73.3%]**.
- Mean R: **−0.007**, 95% CI **[−0.160, 0.169]** — **the interval straddles zero.**
- Median R: **0.12**. Std R: 0.92. Profit factor: **0.98** (losses slightly exceed gains in
  aggregate). Max drawdown of the R-equity curve (in sample order): **12.17R**.
- All stop-hit outcomes are exactly −1.0R by construction (the model never lets a loss exceed the
  defined stop) — the 12.17R drawdown is a run of several losing trades in sequence, not one
  outsized loss; confirmed by inspecting the five worst individual outcomes, every one of which
  reads exactly `-1.0`.

**This is no longer a sample too small to compute (n ≥ 10), but it does not demonstrate an edge.**
The confidence interval on mean R includes zero, and the profit factor sits just under 1. A
positive median R and a win rate above 50% exist alongside a mean R indistinguishable from zero and
a real double-digit-R drawdown stretch — a mixed, not a clearly promising, picture.

## 5. MFE / MAE

| | Mean (R) | Median (R) | p25 | p75 |
|---|---|---|---|---|
| MFE | 0.62 | 0.33 | 0.16 | 0.75 |
| MAE | 0.67 | 0.31 | 0.10 | 1.10 |

Favorable and adverse excursion are similar in magnitude on average — consistent with the
near-zero mean R above, not an independent finding.

## 6. Near-zero-target diagnostic (not changed, per instruction)

- Entry-to-target distance, entry-to-stop distance, and a target/stop ratio were computed for every
  one of the 115 tradeable candidates. **4 of 115 (3.5%)** meet the strict near-zero definition used
  here (target distance < 5% of stop distance) — rarer at this larger scale than the earlier
  3-of-6 finding, which was not representative.
- **However, the *planned* R:R distribution is skewed low more broadly than the strict near-zero
  count suggests**: of 113 candidates with both legs resolved, mean R:R 0.95, median **0.41**, and
  **47 of 113 (42%) have a planned R:R below 0.3**. The near-zero cases are the extreme tail of a
  wider pattern, not an isolated artifact.
- Every selected target traces to a real, named zone: London High (36), Asian High (23), London Low
  (18), Asian Low (12), Previous Day Low (10), H1 Swing High (6), Previous Day High (5), H4 Swing
  Low (2), H4 Swing High (1) — confirming, at scale, the earlier finding that `select_target()`
  always resolves to a genuine structural level, never a fabricated one. Session highs/lows
  (Asian/London) dominate, consistent with the model's entry moment (current M5 close at
  confirmation) often sitting close to the most recently-formed session extreme.
- **Still not changed.** This is consistent with, and reinforces, the prior conclusion: the target
  *hierarchy* is semantically sound; the *systematic skew toward low R:R* is a property of when V2
  samples its entry, and no existing, V2-appropriate deterministic minimum exists to apply without
  tuning a new threshold.

## 7. 1M precision analysis (n=41 with precision, of 152 candidates; 30 of the 115 tradeable)

- Available for 41/152 candidates (27%) — the first time this model's 1M layer has had enough data
  to analyze at all (0 of 6 in the prior study).
- **Timing: 0 of 41 occurred before 5M confirmation; all 41 occurred at or after it** — confirming
  the anti-override gate in `hierarchy.py` is doing exactly what it is designed to do (1M is never
  consulted earlier).
- **Entry/stop/R:R mechanics**: by construction, `precision_1m`'s result is never read when building
  `entry_candidate` — so 1M precision cannot and does not change the entry price, stop distance, or
  planned R:R of any candidate. This was confirmed, not assumed: the precision flag is purely
  informational in the current architecture.
- **Outcome comparison** (tradeable candidates only):

  | | n | Win rate (95% CI) | Mean R (95% CI) | Profit factor | Max DD (R) |
  |---|---|---|---|---|---|
  | With 1M precision | 30 | 73.3% [55.6%, 85.8%] | 0.055 [−0.230, 0.343] | 1.21 | 2.54 |
  | Without 1M precision | 85 | 62.3% [51.7%, 71.9%] | −0.029 [−0.217, 0.174] | 0.92 | 12.17 |

  The "with precision" group looks descriptively better on every metric — **but both mean-R
  confidence intervals still include zero**, and the apparent edge is confounded: the "with
  precision" group's average *planned* R:R is **0.59**, materially lower than the "without" group's
  **1.08** — smaller targets are mechanically easier to hit, which alone could explain a higher win
  rate without any genuine precision-driven improvement. **No claim that 1M precision improves
  performance is supported by this data** — the comparison is suggestive enough to be worth
  re-examining once the model's R:R profile itself is better understood, not before.

## 8. Validation

- **Entry Model V2 tests**: 46/46 (`tests/test_entry_model_hierarchy.py`).
- **V1 tests**: 37/37 + 12/12 (untouched).
- **Full backend suite**: 1780/1780 passed.
- **E2E checklists**: not re-run in full this stage — `git status` confirms zero production files
  changed since the prior stage's 98/99 run (the one known failure there is the pre-existing,
  unrelated `SetupPanel` disclosure issue documented in `docs/entry-model-v2-fixes.md`); since this
  stage only ran read-only research scripts outside the repo, that result stands unchanged.
- **Historical replay integrity**: 5 randomly-sampled tradeable candidates checked by hand against
  raw M5 data — entry price matches the real M5 close at the candidate's own defining bar in all 5;
  every `time_to_target`/`time_to_invalidation` is strictly positive (no lookahead) in all 5.
- **Frozen model unchanged**: confirmed in section 1, and by the fact that re-running the prior
  400-sample study's exact sampling (available from the earlier stage) was not repeated here since
  no code changed since that run was last verified bit-for-bit reproducible.

## 9. Confidence intervals and sample-size limitations

- n=115 tradeable candidates clears the n≥10 threshold used throughout this project's research
  (no longer flagged `insufficient` by that rule), but 95% CIs on mean R are still roughly
  ±0.17 wide around a value near zero — wide enough that "no detectable edge" and "a small real
  edge" are both consistent with the data.
- The 1M-precision subgroup (n=30 with precision) is smaller and its CI correspondingly wider.
- 23 months of calendar time produced 152 distinct candidates — roughly 7-9 per month — meaning a
  much larger sample would require either a much longer history (not available for M5) or accepting
  a materially different sampling/aggregation approach; both are future-research questions, not
  something to force now.
- Candidates are not independent draws (the market is one continuous, serially-correlated price
  path) — no correction for this was attempted; treat the CIs above as indicative, not exact.

## 10. Comparison with the previous 400-sample study

| | Prior (400 samples, every 50th M15 bar) | This study (16,449 samples, every 2nd M15 bar) |
|---|---|---|
| Distinct candidates | 6 | 152 |
| Tradeable | 4 | 115 |
| Mean R | not statistically meaningful (n=4) | −0.007, CI [−0.16, 0.17] |
| 1M precision available | 0 | 41 (27%) |
| Near-zero targets | 3 of 4 (75%, not representative) | 4 of 115 (3.5%) |

The larger sample both supplies enough data to compute real statistics *and* corrects the earlier,
small-sample impression that near-zero targets were the norm — they are not; they are a rare tail
of a broader, more moderate low-R:R skew.

## 11. Is the evidence sufficient?

**PROMISING BUT PRELIMINARY — leaning toward NEUTRAL on the headline number.** The funnel and
outcome pipeline now produce enough candidates (n=115) for real statistics, which is itself the
main finding of this stage. But the central result — mean R ≈ 0 with a CI straddling zero, profit
factor just under 1, and a 12R drawdown stretch — does **not** demonstrate a usable edge. The
positive median R and above-50% win rate are real but do not outweigh a mean that cannot be
distinguished from zero. This is not `INSUFFICIENT` (the sample is now large enough to say
something), and it is not yet strong enough to call `PROMISING` without the "preliminary" and
"leaning neutral" qualifiers attached.

## 12. Recommended next research step

1. Investigate *why* mean R sits near zero despite a >50% win rate — likely the low-R:R skew
   (section 6): many small wins are not enough to offset occasional stop-outs when the average
   planned reward is well under 1R. This is a research question about the *interaction* between
   win rate and R:R, not a license to tune R:R now.
2. Re-examine the 1M-precision comparison (section 7) after controlling for planned R:R, since the
   current apparent difference is confounded by it.
3. If a future, separately-authorized stage decides to address the R:R skew, it should be evaluated
   against an **out-of-sample** slice of this same data (e.g. a chronological holdout), not the
   same 115 candidates used to notice the pattern — to avoid exactly the kind of post-hoc
   threshold-fitting this stage was explicitly asked not to do.
4. Accumulate more M1 history before drawing any firmer conclusion about 1M precision specifically.
