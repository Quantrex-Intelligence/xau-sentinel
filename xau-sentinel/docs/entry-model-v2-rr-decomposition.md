# Entry Model V2: why does a 65.2% win rate produce ~0R expectancy?

Research/decomposition only, on the already-computed 152-candidate / 115-tradeable dataset from
`docs/entry-model-v2-large-outcome-study.md`. No replay was re-run; no production code was touched.
Confirmed via `git status`: `analysis/entry_model/`, `ai/strategy/rules.py`, and `config.py` carry
no new diff from this stage.

## 1. R:R bucket table

| Bucket | n | Win rate | Mean R | Median R | Profit factor | Mean MFE (R) | Mean MAE (R) | Target-first | Stop-first |
|---|---|---|---|---|---|---|---|---|---|
| < 0.25 | 39 | 87.2% | **−0.017** | 0.11 | 0.86 | 0.24 | 0.28 | 34 | 5 |
| 0.25–0.5 | 22 | 72.7% | **−0.018** | 0.30 | 0.94 | 0.39 | 0.48 | 16 | 6 |
| 0.5–1.0 | 23 | 69.6% | **+0.196** | 0.61 | 1.64 | 0.79 | 0.62 | 16 | 7 |
| 1.0–1.5 | 11 | 45.5% | −0.024 | −1.00 | 0.96 | 1.00 | 0.84 | 5 | 6 |
| 1.5–2.0 | 2 | 0% | −1.00 | −1.00 | 0.00 | 0.24 | 1.36 | 0 | 2 | *(n=2, flagged insufficient)* |
| > 2.0 | 16 | 25.0% | +0.001 | −1.00 | 1.00 | 1.34 | 1.60 | 4 | 12 |

No bucket was dropped. Win rate falls monotonically as planned R:R rises (mechanically expected —
larger targets are harder to reach before price reverses). **Mean R does not rise with win rate** —
the two lowest buckets (53% of all 115 candidates) have high win rates but *negative* mean R; the
middle bucket (0.5–1.0) is the only one with a mean R and profit factor clearly above breakeven.

## 2. Payoff decomposition: why is planned R:R low?

| | Mean | Median |
|---|---|---|
| Target distance (ATR) | 1.10 | 0.91 |
| Stop distance (ATR) | 2.27 | 1.95 |

- **62 of 115 (54%)** have a target under 1 ATR away (small target).
- **53 of 115 (46%)** have a stop over 2 ATR away (large stop).
- **36 of 115 (31%) show both at once** — the worst combination.
- **36 of 115 (31%) show neither** (a reasonably-sized target *and* stop).
- Stop source: **M15 swing 80 (70%), sweep extreme 35 (30%)**. The swing-based stop (used whenever
  no sweep anchors the setup — now common, since 15M evidence is independent/optional in V2) is
  structurally farther away than a sweep extreme, which plausibly explains why stops run large more
  often than targets run small.
- Target source: dominated by session extremes — **London High (36), Asian High (23), London Low
  (18), Asian Low (12)** — 89 of 115 (77%) of all targets. These are genuine, correctly-identified
  structural levels (confirmed in the prior audit), but session extremes are frequently *close* to
  current price precisely because price often approaches or retests them, which is why they produce
  short target distances so often.

**Conclusion: a combination, not a single cause** — target-too-close (54%) is somewhat more
prevalent than stop-too-far (46%) alone, but roughly a third of candidates have both at once, and
they are not independent (the same session-range conditions that put a target close by also tend
to coincide with a structurally distant M15 swing stop).

## 3. MFE analysis — a finding that had to be corrected mid-analysis

An initial pass found "67.3% of candidates' MFE exceeded their own planned target" and almost
reported this as evidence of a too-conservative target leaving profit on the table. **Disaggregating
by actual outcome shows this is misleading:**

- **100% of the 75 target-hit trades** show MFE exceeding the planned target — but this is
  mechanical: `label_outcome()` measures MFE from the wick of the bar that touches the target, which
  by construction reaches at least the target price, plus on average **0.22R of ordinary wick
  overshoot**. This is not "left on the table" profit; the position's own exit logic ends there.
- **Only 1 of the 38 stop-hit trades (2.6%)** ever got close to the planned target before reversing
  to stop — and that one case was a rounding-level difference (planned R:R 0.15, MFE 0.16R).
  **Losing trades essentially never ran favorably toward the target first** — when the trade was
  wrong, it tended to be wrong fairly directly, not "almost right."
- Winners' mean MFE (0.74R) vs. losers' mean MFE (0.37R), winners' mean MAE (0.23R) vs. losers'
  mean MAE (1.48R, i.e. the full −1R stop plus rounding) — losers did see *some* initial favorable
  movement (0.37R on average) before failing, which is not an absurd directional read, but nowhere
  near enough to call it "almost a winner."

**Answering the specific questions asked:**
- *Does low planned R:R also have low MFE?* Yes, directionally (mean MFE rises from 0.24R in the
  lowest bucket to 1.34R in the highest) — but this is confounded by the SAME early-exit mechanic:
  a tiny target gets hit (and MFE tracking stops) almost immediately, so low-bucket MFE is partly an
  artifact of resolving fast, not purely "price couldn't move further."
- *Are candidates reaching substantially more favorable excursion than their selected target?*
  **No, not meaningfully**, once target-hit's mechanical overshoot is excluded.
- *Are winners mostly small wins while losers are larger?* **Yes, exactly** — mean winning R
  **+0.52**, mean losing R **exactly −1.00** (every stop-hit by construction; see section 4).
- *Is the negative expectancy explained by the payoff distribution rather than directional
  accuracy?* **Yes — see section 1's bucket table and the breakeven comparison in section 7.**

## 4. Full realized-R distribution (n=115)

| | Value |
|---|---|
| Mean | −0.007 |
| Median | 0.12 |
| Std dev | 0.918 |
| Min | −1.00 |
| Max | 4.00 |
| Q25 | −1.00 |
| Q75 | 0.41 |
| Positive R count | 75 (65.2%) |
| Negative/zero R count | 40 (34.8%) |
| **Mean winning R** | **+0.52** |
| **Mean losing R** | **−1.00** (exact, by construction — the model never lets a loss run past the stop) |

This is the direct, numeric answer to the headline question: **a 65.2% win rate at an average win
of +0.52R against an average loss of exactly −1.00R gives an expectancy of**
`0.652 × 0.52 + 0.348 × (−1.00) ≈ −0.007` — matching the reported mean R almost exactly. **The win
rate alone was never going to be informative without the payoff ratio next to it**; a ~2:1 loss-to-
average-win ratio needs roughly a 66% win rate just to break even, and this sample sits right at
that line.

## 5. Direction / session / month diagnostics (descriptive only)

**Direction**: SHORT (n=42) mean R +0.14, median +0.20; LONG (n=73) mean R −0.09, median +0.11.
Both groups clear n≥10. The SHORT/LONG gap could be a real asymmetry, a sampling artifact of which
sessions/months happened to produce SHORT vs LONG candidates, or noise — not independently
distinguishable here; **not a basis for any directional filter**.

**Session** (of the candidate's own defining bar): Asian (n=24, mean R −0.14), London (n=34, mean R
−0.17), New York (n=37, mean R −0.02), **Off-session (n=20, mean R +0.45, win rate 90%)**. The
off-session figure is the most striking number in the whole study and the one most likely to be
noise, a labeling quirk, or a genuine but small-sample effect — flagged here explicitly as the
weakest-support finding in this report, not a lead to act on.

**Month**: 15 months represented, n ranging from 2 to 20. **9 of 15 months have n<10 and are
explicitly flagged `insufficient`** in the underlying data. The 6 months with n≥10 (2025-06, 2025-12,
2026-01, 2026-08, 2026-09, plus the overall total) show mean R ranging from −0.39 (2025-12, the
single worst month) to +0.17 (2026-08) — no consistent trend, consistent with a system hovering
near breakeven with month-to-month noise rather than a drifting or improving edge.

## 6. 1M precision — controlled for planned R:R

| | n | Mean planned R:R | Win rate | Mean R | Profit factor |
|---|---|---|---|---|---|
| With 1M precision | 30 | 0.59 | 73.3% | 0.055 | 1.21 |
| Without 1M precision | 85 | 1.08 | 62.3% | −0.029 | 0.92 |

The uncontrolled comparison still favors "with precision" — but **the two groups are not trading
at the same R:R**, so this is the same confound flagged in the prior study. Controlling by R:R
bucket:

| Bucket | With-precision n | With-precision mean R | Without-precision n | Without-precision mean R |
|---|---|---|---|---|
| <0.25 | 11 | +0.047 | 28 | −0.043 |
| 0.25–0.5 | 9 | +0.180 | 13 | −0.155 |
| 0.5–1.0 | 5 | +0.134 | 18 | +0.213 |
| 1.0–1.5 | 2 | −1.000 | 9 | +0.193 |
| 1.5–2.0 | 0 | — | 2 | −1.000 |
| >2.0 | 2 | +0.920 | 14 | −0.130 |

Within the same bucket, "with precision" is better in 2 of 5 comparable buckets (<0.25, 0.25–0.5),
worse in 2 (0.5–1.0, 1.0–1.5), and the >2.0 bucket's 2-vs-14 split is too thin to read either way.
**This is not a consistent, controlled advantage — it is mixed, and every cell here is small enough
that none of it should be read as evidence 1M precision improves performance.** The honest
conclusion is unchanged from the prior study: not demonstrated, in either direction, once R:R is
accounted for.

## 7. Root-cause interpretation

1. **Is the negative/flat expectancy primarily a payoff problem? Yes.** Section 1's bucket table and
   section 4's win/loss decomposition show the expectancy arithmetic directly: the win rate is not
   low, the average win is small relative to the fixed −1R loss.
2. **Is low planned R:R the dominant issue? Yes, specifically in the two lowest buckets** (53% of
   the sample), where win rate sits almost exactly at (within ~2 percentage points of) the
   mathematical breakeven win rate implied by that bucket's own average R:R (breakeven for
   <0.25's average 0.125R is 88.9%, actual 87.2%; for 0.25–0.5's average 0.341R it is 74.6%, actual
   72.7%). **There is no detectable directional edge beyond what the payoff structure itself would
   produce by chance in these two buckets.** The 0.5–1.0 bucket is the exception: breakeven 59.0%,
   actual 69.6% — a real **+10.6 percentage point** gap above breakeven, the one part of the sample
   that looks genuinely different from chance (n=23, still a single historical sample).
3. **Does MFE suggest the entry is systematically late? No clear evidence of this.** Losing trades
   show modest (0.37R) but not negligible initial favorable movement before reversing — consistent
   with "the direction was a reasonable read that didn't follow through," not "the entry was so late
   the position started underwater." The apparent "MFE exceeds target" signal does not survive
   disaggregation by outcome (section 3).
4. **Does target selection appear to be the main problem? Partially, and only in the sense already
   known**: targets are real, correctly-identified structural levels, but they are frequently close
   to entry (session extremes especially), which drives the low-R:R buckets that show no edge over
   breakeven. This is the same finding as the prior studies, now decomposed with ATR-normalized
   distances and a stop-type breakdown rather than asserted from a handful of examples.
5. **Is there any descriptive evidence that 1M precision helps? No, not once R:R is controlled for**
   — see section 6. The uncontrolled comparison's apparent edge is explained by the precision group
   trading at systematically lower R:R, not by precision itself.
6. **What should be investigated next?** See section 9.

**Hypothesis only, not a strategy change:** the 0.5–1.0 planned R:R band is the only slice of this
historical sample showing win rate meaningfully above its own breakeven line. This is flagged as a
hypothesis worth a dedicated, out-of-sample research stage — it is explicitly **not** a recommended
cutoff, and was not used to filter, re-run, or improve any number in this report.

## 8. Limitations

- n=115 overall clears the project's n≥10 threshold, but most individual buckets, sessions, and
  11 of 15 months sit at or near that threshold — explicitly flagged wherever it applies.
- Candidates are not independent draws from a stationary process; no autocorrelation or regime
  correction was attempted.
- The MFE/MAE comparison across R:R buckets is partly confounded by the early-exit mechanic
  (section 3) — flagged, not corrected, since correcting it would mean changing the outcome
  methodology mid-study.
- The off-session result (section 5) and the single best month/bucket are the parts of this report
  most likely to be noise; they are reported because the task asked for the full breakdown, not
  because they are being proposed as findings to act on.
- All of this remains a single historical sample (one real price path) replayed once: no train/
  validation/out-of-sample split was performed in this stage, consistent with "do not optimize on
  this sample."

## 9. Recommended next research stage

1. Treat the 0.5–1.0 R:R hypothesis (section 7) as a question for a **separate, out-of-sample**
   study — never re-test it against these same 115 candidates.
2. If a future stage investigates the target/stop distance pattern (section 2), gather fresh
   candidates from data not used to notice the pattern, to avoid fitting this sample's noise.
3. Re-run the 1M-precision comparison once more M1 history exists and the with-precision group is
   large enough to control for R:R without cells this thin.
4. Do not change `select_target()`, stop logic, or the direction/confirmation gating based on this
   report — it explains the existing numbers; it does not justify acting on them yet.
