# Entry Model V2: exploratory robustness audit of the 0.5–1.0R in-sample finding

**All results in this document are in-sample exploratory analysis on the existing 115-candidate
dataset from `docs/entry-model-v2-rr-decomposition.md`. No out-of-sample claim is made or implied
anywhere below — there is no genuinely unseen MT5 data after 2026-10-06 (confirmed in the prior
stage), so none was used or relabeled.** No production file was touched (confirmed via `git status`
below); no entry/stop/target/confirmation/direction logic, filter, or threshold was changed.

## 1. Bootstrap analysis

Method: resample each group's realized-R values with replacement, same size as the group, 10,000
iterations, fixed seed (reproducible on re-run).

| Group | n | Observed mean R | Bootstrap mean R | 95% bootstrap CI | Bootstrap std | % of resamples with mean R > 0 |
|---|---|---|---|---|---|---|
| All 115 | 115 | −0.007 | −0.006 | [−0.167, 0.165] | 0.085 | 45.8% |
| **0.5–1.0R bucket** | 23 | **+0.196** | +0.195 | **[−0.157, 0.511]** | 0.168 | **87.3%** |
| Comparison group | 92 | −0.058 | −0.058 | [−0.239, 0.142] | 0.097 | 26.8% |

**The 0.5–1.0R bucket's own bootstrap CI still includes zero** (and even dips slightly negative at
the 2.5th percentile) — the bootstrap does not eliminate the possibility of a true mean at or below
zero. What it does show: resampling the SAME 23 observations lands on a positive mean 87.3% of the
time, a meaningfully higher rate than the all-115 pool's near-coin-flip 45.8% or the comparison
group's 26.8%. This is a directional signal, not a resolved one.

## 2. Permutation / null test

**Null hypothesis**: planned-R:R bucket membership carries no information about realized R — any
random group of 23 candidates drawn from the pooled 115 R-values would do just as well.

**Method**: 10,000 draws of 23 values *without replacement* from the pooled 115 realized-R values
(membership randomized, the R-values themselves never altered), recording each draw's mean.

| | Value |
|---|---|
| Observed bucket mean R | +0.196 |
| Pool mean R (all 115) | −0.007 |
| Mean of the null distribution | −0.006 |
| Null distribution std | 0.170 |
| Null 95% range | [−0.323, 0.340] |
| **Observed result's percentile in the null distribution** | **87.9th** |
| **One-sided p-value** (P(null ≥ observed)) | **0.121** |
| Two-sided p-value | 0.235 |

**The observed +0.196 sits at the 87.9th percentile of the null — unusual, but not rare enough to
reject the null at a conventional 5% threshold.** About 1 in 8 random, equally-sized draws from the
full candidate pool would match or beat this result by chance alone. This is a weak-to-moderate
signal, explicitly **not** statistical significance, and is not treated as one.

## 3. Concentration analysis

| | |
|---|---|
| Bucket total realized R | 4.50 (over 23 candidates, mean 0.196) |
| Top 1 contributor | `SHORT:2026-09-17 09:15` — 0.96R, **21.3% of total bucket R** |
| Top 3 contributors | +`SHORT:2026-05-18 07:45`, `SHORT:2026-09-15 20:15` — 2.83R, **62.9%** |
| Top 5 contributors | + two more — 4.52R, **100.4%** (the remaining 18 candidates net to roughly zero) |
| Mean R after removing the single largest winner | **0.161** (down from 0.196, an 18% reduction) |
| Median R | 0.61 |
| Win / loss split | 16 wins, 7 losses |

**The result is meaningfully concentrated**: 5 of 23 trades (22%) account for the entire net
positive contribution; the other 18 collectively net to essentially zero. Removing only the single
best trade cuts the mean by nearly a fifth. No observation was excluded from any other analysis in
this report — this section only quantifies the concentration, it does not remove anything.

## 4. Temporal / direction / session breakdown (descriptive only)

**By month** (all flagged `insufficient`, n<10 in every single month):

| Month | n | Mean R |
|---|---|---|
| 2025-05 | 1 | 0.61 |
| 2025-06 | 4 | −0.14 |
| 2025-08 | 1 | 0.52 |
| 2025-10 | 1 | 0.68 |
| 2025-11 | 2 | −0.13 |
| 2025-12 | 1 | −1.00 |
| 2026-01 | 3 | 0.61 |
| 2026-05 | 2 | 0.85 |
| 2026-07 | 2 | −0.12 |
| 2026-08 | 1 | 0.79 |
| 2026-09 | 5 | 0.08 |

No month has enough candidates on its own to say anything; the sign bounces between months with no
visible trend.

**By direction**: SHORT n=11, mean R +0.27; LONG n=12, mean R +0.13. Both directions individually
positive within this bucket — a mild point in the hypothesis's favor, though neither clears n≥10
by much margin and both are themselves already inside a 23-candidate bucket.

**By session**: Off-session n=6 (+0.72), London n=6 (+0.48), Asian n=4 (+0.26), **New York n=7
(−0.53)**. New York is both the largest session subgroup in this bucket and the only one with a
clearly negative mean — the "0.5–1.0R is good" pattern does **not** hold in its single largest
session slice. All four session groups are flagged small.

## 5. Breakeven analysis (all six buckets, for context)

| Bucket | n | Mean planned R:R | Breakeven win rate | Observed win rate | Edge over breakeven (pp) | Mean R |
|---|---|---|---|---|---|---|
| <0.25 | 39 | 0.125 | 88.9% | 87.2% | −1.7 | −0.017 |
| 0.25–0.5 | 22 | 0.341 | 74.6% | 72.7% | −1.8 | −0.018 |
| **0.5–1.0** | 23 | 0.696 | 59.0% | 69.6% | **+10.6** | +0.196 |
| 1.0–1.5 | 11 | 1.162 | 46.3% | 45.5% | −0.8 | −0.024 |
| 1.5–2.0 | 2 (insufficient) | 1.810 | 35.6% | 0.0% | −35.6 | −1.00 |
| >2.0 | 16 | 3.913 | 20.4% | 25.0% | +4.6 | +0.001 |

Four of six buckets sit within ~2 percentage points of their own mathematical breakeven line — no
meaningful deviation from chance. The 0.5–1.0R bucket's **+10.6pp** gap is the largest positive
deviation in the table and the only one both (a) sizeable and (b) not built on an `insufficient`-
flagged n. **This is the same number already reported in the prior study — this audit does not
produce a new estimate of it, only tests how much confidence it deserves (sections 1–3, 6).**

## 6. Dependence / clustering

Market observations are not independent random draws; this was checked directly rather than
assumed.

**Within the 0.5–1.0R bucket (n=23)**: 20 distinct calendar days produced the 23 candidates — only
3 days contributed 2 each (2025-11-13, 2026-07-10, 2026-09-24). Median gap between consecutive
candidates (sorted by time): **173.8 hours (~7.2 days)**; minimum gap 4.5 hours. **Clustering inside
this specific bucket is mild** — it is not a handful of days repeatedly re-triggering the same
signal.

**Across all 115 candidates**: clustering is substantial. Median gap only 5.5 hours; 83 of 114
consecutive pairs fall within 24 hours of each other; several single calendar days contributed 4-6
candidates each (2025-12-22: 6, 2026-08-24: 6, 2026-09-14: 6, 2026-01-21: 4, 2026-01-28: 4,
2026-04-16: 4, 2026-07-10: 4, 2026-08-21: 4, 2026-09-23: 4). **This means the 115 "candidates" do
not represent 115 independent market episodes — a single volatile day can and does produce several
of them at once.** The ordinary bootstrap/permutation CIs used throughout this project's research
(sections 1–2 here, and every prior R-multiple CI) treat each candidate as an independent draw; this
clustering means **those CIs are likely narrower than the true uncertainty** — a real limitation
affecting this whole research line, not unique to the 0.5–1.0R bucket, and not corrected for here
(no new statistical model was built, per instruction) — only reported.

## 7. Overall assessment

1. **Does the 0.5–1.0R result look robust within this existing sample?** Partially. It holds up
   directionally under bootstrap (87% of resamples positive) and sits at the 88th percentile of a
   permutation null — genuinely unusual, not the norm for a random same-sized slice of this data.
2. **Is it heavily dependent on a few trades?** **Yes.** 5 of 23 trades account for all of the net
   positive R; removing the single best trade cuts the mean by 18%.
3. **Does it survive temporal/directional decomposition?** **Partially.** Direction (LONG/SHORT)
   splits are both individually positive. Session does not: New York, the largest session subgroup
   in the bucket, is negative. No individual month has enough data to judge on its own.
4. **Does the permutation test suggest more than random bucket assignment?** **Suggestively, not
   conclusively.** p = 0.12 one-sided — below the usual 0.05 significance bar.
5. **What evidence supports the hypothesis?** The breakeven gap (+10.6pp, the largest in the
   table), the bootstrap's 87% positive-resample rate, the 88th-percentile permutation result, and
   a positive mean in both LONG and SHORT sub-splits.
6. **What evidence argues against it?** The bootstrap CI still includes zero; the permutation
   p-value does not clear conventional significance; the result depends heavily on 5 trades; the
   New York session sub-slice is negative; every finer breakdown (month, session) is individually
   small-sample; and the dataset-wide clustering (section 6) means the effective sample size behind
   all of this is smaller than 23 independent observations.
7. **What would genuinely validate or invalidate it?** A materially larger, genuinely unseen,
   strictly later sample (see the OOS requirements below) showing the same bucket's mean R
   positive and its win rate still meaningfully above that bucket's own breakeven line, ideally
   without depending on a handful of trades to stay positive.

**Verdict: WEAK EXPLORATORY SIGNAL.**

Not "INCONCLUSIVE" — there is a real, consistent directional pattern across multiple independent
checks (bootstrap, permutation percentile, breakeven gap, direction split). Not "NO SUPPORT" for
the same reason. But it falls short of anything resembling validation: the permutation p-value does
not reach conventional significance, the bootstrap CI includes zero, and the result leans on a
small number of large wins. **This is not a "validated," "proven edge," or "OOS-supported" result,
and is not described as one anywhere in this document.**

## 8. Limitations

- Every number here is in-sample. The dataset is identical to the prior study's 115 candidates;
  no new data was pulled or substituted.
- Section 6's clustering finding means the bootstrap/permutation CIs throughout this report (and
  the prior studies) likely understate true uncertainty — candidates are not independent.
- The permutation null (random same-sized draws from the pooled 115) tests whether the *bucket
  label* carries information, not whether the bucket's underlying mechanism (payoff ratio breakeven
  math) is sound — the breakeven-math argument (section 5) and the permutation test are
  complementary, not redundant, and neither alone is conclusive.
- Small-n warnings are explicit wherever n<10 was involved (every month, most session cells); they
  are not a basis for discarding those rows, only for not over-reading them.
- This is one path of market history, replayed once. No regime, volatility, or liquidity
  conditioning was attempted.

## 9. Exact requirements for the eventual genuine OOS test

To be a valid OOS test (not performed here, and not approximated here):

1. **Data must be strictly later than 2026-10-06** (the end of the IS window used for the 115
   candidates) — no portion of the existing dataset may be relabeled or reused as "OOS."
2. **The frozen hypothesis** (`0.5 ≤ planned R:R < 1.0`) must be tested exactly as stated — no
   alternative cutoff, no search, no re-fitting based on this audit's findings (sections 1–6 above
   explain the existing result; they must not be used to adjust the interval before testing it).
3. **Same frozen V2 implementation** — same entry, stop, target, confirmation, and direction-gating
   logic as used to produce the 115-candidate dataset; confirmed unchanged by this stage's
   `git status` check and the passing Entry Model test suite.
4. **A realistic sample-size expectation going in**: at the observed historical rate (~20% of
   tradeable candidates fall in this bucket, ~7-9 tradeable candidates/month), a OOS hypothesis-
   group sample of even n≈10 would need roughly 5-6 months of new market data — this was already
   flagged when the OOS request was first raised and remains true.
5. **No peeking and re-testing** — the OOS result should be evaluated once, as a single test of the
   frozen interval, not iteratively checked and the interval adjusted if an early look looks
   unfavorable.
6. Given section 6's clustering finding, the eventual OOS analysis should also check whether its own
   candidates cluster in time before trusting its own confidence intervals at face value.
