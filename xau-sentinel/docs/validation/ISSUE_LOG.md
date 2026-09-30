# XAU Sentinel — Validation & Testing Phase — Issue Log

Severity: **P0** critical · **P1** high · **P2** medium · **P3** low. Status for every item below is
**Open** except where an entry's own **Status** line says otherwise — no fixes were made during the
validation phase itself (feature freeze; see `TEST_PLAN.md`); targeted fixes for specific items have since
been made in later hardening stages (Stage 19 fixed VAL-001/VAL-002/VAL-003/VAL-005; Stage 20 fixed VAL-004;
Stage 23A fixed VAL-007..011/013..015/018/025/026 — see each entry's own Status line, and the git history for the exact commits). All line numbers refer to
the codebase at commit `837f8b5` (Stage 18) unless an entry's own Status line names a later commit.

---

## P0 — Critical

### VAL-001 — Both LLM safety-filter regexes miss almost every realistic unsafe phrasing
- **Status: Resolved in Stage 19** (see this file's own commit in `git log` for the exact hash).
- **Date:** 2026-09-29
- **Subsystem:** `ai/prompts.py` (`contains_actionable_directive`, `contains_predictive_probability_claim`) — the deterministic backstop behind every AI-authored answer in the app (chat, A+ explanation, alert/trade explanation, trade review interpretation).
- **Expected:** A trade-directive or a win-probability/forecast claim, however the model phrases it, gets caught and replaced with the safety-override message before it reaches the user.
- **Actual:** Only the exact literal example phrasings in the system prompt are caught. Every one of these realistic paraphrases returns `False` (unfiltered) — **verified by direct execution against the current branch**, not inferred:
  - Directive: `"It would be wise to go long here."`, `"You should take this trade."`, `"I would recommend buying here."`, `"Go long now."`, `"Enter now."`, `"**Buy** now while the sweep is fresh."`, `"Open a long position."`, `"You should add to your position."`
  - Probability/forecast: `"This pattern tends to resolve upward."`, `"Odds favor a bounce here."`, `"There is a strong chance of a reversal."`, `"This setup is likely to play out well."`, `"Historically this leads to a bounce."`
  - Neither pattern set covers "long"/"short" wording at all — the way XAUUSD traders normally speak — and the directive set requires the literal word "I" immediately before "recommend/suggest" and only buy/sell/enter/exit as the verb (misses "add to", "move your stop", etc., despite ground rule 4 explicitly naming "add to").
- **Evidence:** `ai/prompts.py:142-148` (5 directive patterns), `:162-167` (4 probability patterns); reproduced live via `python -c "from ai.prompts import ...; print(contains_actionable_directive(...))"` for every phrase above — all `False`.
- **Reproduction:** Run the phrases above through `contains_actionable_directive()` / `contains_predictive_probability_claim()`.
- **Potential fix:** Broaden both pattern sets to cover long/short phrasing, softened imperatives ("it would be wise to...", "consider..."), "should" + any action verb (not just the fixed list), and markdown/punctuation between words (`**Buy**`, `BUY-NOW`). Given regexes alone can't realistically cover open-ended paraphrase, consider a second pass (a small classifier prompt, or a stricter output-format constraint) rather than trying to enumerate every phrasing.
- **Note:** This gap has never been exercised in practice because `AI_PROVIDER=mock` in every environment tested this session — the mock provider only echoes scripted text, never generates creative language. The risk is dormant until a real model is configured.

### VAL-002 — FundedNext daily-loss anchor can silently understate today's actual loss
- **Status: Resolved in Stage 19** (see this file's own commit in `git log` for the exact hash).
- **Subsystem:** `risk/day_tracker.py:20-28`, consumed by `risk/fundednext.py:28-34`.
- **Expected:** The daily-loss floor is anchored to the account balance at server midnight (per the module's own docstring).
- **Actual:** The anchor is whatever balance `compute_status()` first observes on a new server-calendar-day — if the app/monitoring loop wasn't running at exactly midnight (laptop asleep, app started late, MT5 disconnected), trades already closed earlier that day are silently absorbed into the anchor.
- **Reproduction (concrete scenario):** $50k account, 5% daily limit ($2,500). Trader loses $2,000 before opening the app for the first time that day. The anchor becomes the already-reduced balance; the app reports `daily_loss_used_pct ≈ 0`, SAFE, "$2,500 remaining" — when only $500 actually remains.
- **Potential fix:** Anchor as `current_balance − today's realized P&L so far` (from `get_daily_pnl_history`), or mark the anchor as unverified/flag a warning when it's first observed mid-day rather than at a clean day boundary.

### VAL-003 — MT5 candle/tick timestamps are labeled UTC but are actually broker server time
- **Status: Resolved in Stage 19** (see this file's own commit in `git log` for the exact hash).
- **Subsystem:** `mt5/market_data.py:55,78`.
- **Expected:** Per `README.md`'s own claim ("All candle timestamps are handled in UTC internally") and the stale-check/sweep-window/session logic, which all assume UTC.
- **Actual:** MT5 bar/tick times are tagged `utc=True` without any broker-offset correction, but the project's own `FUNDEDNEXT_SERVER_TIMEZONE` default (`Europe/Nicosia`, UTC+2/+3) documents that the broker is *not* UTC. On a non-UTC server: the staleness check (`is_stale()`) can compute a negative age and never fire on a frozen feed; the sweep-window expiry (`is_within_sweep_window`) can likewise never expire a stale candidate; Asian/London session masks and day boundaries (Previous Day High/Low, VWAP session) shift by the server's UTC offset.
- **Potential fix:** Apply the broker's actual UTC offset (or query it from the terminal) before tagging candle/tick times as UTC, or explicitly document and test against the specific broker's offset if it's always fixed for this account.
- **Note:** Severity depends on the real broker's timezone, which can't be confirmed against `MODE=mock` — flagged for confirmation once a live MT5 connection is available.

---

## P1 — High

### VAL-004 — Periodic Digest reports the period that just started, not the one that just ended
- **Status: Resolved in Stage 20** (see this file's own commit in `git log` for the exact hash).
- **Subsystem:** `ai/digest/service.py::run_digest_cycle()`/`attempt_send()` (Stage 18, this session's own build).
- **Expected:** Per the spec's own worked example ("Period: Sep 21-27" shown in a digest whose scheduling example implies it fires the following Monday), a scheduled or previewed digest should summarize the week/month that just **completed**.
- **Actual:** `run_digest_cycle()` calls `attempt_send(digest_type, reference=now.date())`, and `build_digest()`'s `compute_period_bounds()` returns the period **containing** `reference` — i.e. today. On the Monday the weekly digest is scheduled to fire, the "current period" it reports on is Monday-Sunday of the week that just began (almost no trades yet), while the week the user actually wants is only shown as the "previous period" comparison line. The same applies to `POST /api/digest/preview`/`/send` with no explicit reference — both always describe the in-progress period, never the last completed one.
- **Evidence:** `ai/digest/service.py` — `reference or _now().date()` feeding directly into `compute_period_bounds`, with no "step back one period" logic anywhere in the scheduled path.
- **Root cause (confirmed in Stage 20):** exactly as diagnosed above — `build_digest()` computed the
  in-progress period containing `reference` instead of the last completed one. Not a scheduler bug (it only
  ever decides *when* to fire) and not a bug in `strategy_analytics`/`trade_review`/delivery/dedup (all
  correctly period-agnostic).
- **Fix:** `ai/digest/service.py`'s period-bounds functions now use an explicit half-open `[start, end)`
  interval (`end` = first day of the *next* period, exclusive — previously `end` was the inclusive last day,
  which is what made "is this period done yet" ambiguous). A new `completed_period_bounds(digest_type,
  reference)` steps back one day from the period containing `reference` and returns *that* period's bounds
  — `build_digest()` now calls this instead of `compute_period_bounds()` directly, so both the scheduler
  and manual `/preview`/`/send` (which share the exact same code path, no second implementation) always
  report the last completed period. `trades_in_period()`'s filter became half-open
  (`start <= trade_date < end`) to match. `ai/digest/formatter.py::_format_period_range()` converts the
  exclusive `end` back to an inclusive last day (`end - 1 day`) for the human-readable "Sep 21-27" display
  line — the only place the boundary needed to become inclusive again. No changes to `ai/digest/store.py`,
  `api/routes/digest.py`, or the scheduler's own day/time-matching logic (`should_send_now()`) — none of
  those needed to change.
- **Regression coverage:** 11 new tests across `tests/test_digest_service.py` (half-open bounds for both
  digest types, the exact Monday-trigger / Sunday-still-in-progress / December→January / first-of-month
  boundary cases named in the spec, a `SESSION_TIMEZONE`-anchoring case using a UTC instant that falls on a
  different local calendar date, and a proof the "previous period" comparison still populates one period
  further back than the newly-corrected anchor), `tests/test_digest_formatter.py` (inclusive display-range
  rendering from the half-open bounds), and `tests/test_digest_api.py` (`/preview` and `/send` report
  byte-identical `period_start`/`period_end` for the same underlying "now" — proving the "no second
  implementation" requirement structurally). All existing digest tests that encoded the old, buggy
  in-progress-period semantics were updated to the corrected expected values (not merely left passing by
  coincidence).
- **Verification result:** live-verified against the real dev server on 2026-09-29 (a Tuesday):
  `POST /api/digest/preview {"digest_type":"WEEKLY"}` returned `period_start=2026-09-21, period_end=2026-09-28`
  (the completed prior week, correctly excluding the in-progress Sep 28–Oct 4 week); MONTHLY returned
  `period_start=2026-08-01, period_end=2026-09-01` (completed August, correctly excluding in-progress
  September). Full suite: 1076/1076 backend (1065 baseline + 11 new), 133/133 frontend, 14/14 E2E
  checklists, lint/typecheck/build all clean — zero regressions elsewhere.
- **Potential fix (superseded by the above):** ~~When firing from the scheduler (and as the default for
  `/preview` and `/send`), compute the period ending most recently before `reference`...~~ — this is exactly
  what was implemented.

### VAL-005 — `float` NaN silently defeats every `is None` check on numeric journal fields
- **Status: Resolved in Stage 19** (see this file's own commit in `git log` for the exact hash).
- **Subsystem:** `ai/trade_review/patterns.py::closed_trades()` (Stage 16), consumed by `ai/trade_review/rules.py` (Stage 16), `ai/strategy_analytics/metrics.py` (Stage 17), `ai/digest/service.py` (Stage 18).
- **Expected:** A trade with no recorded `planned_rr`/`r_multiple`/`duration_minutes` is treated as missing data (`None`) throughout the deterministic pipeline, per this project's own repeated "UNKNOWN, never assumed" convention.
- **Actual:** `closed_trades()`'s `df.where(df.notnull(), None)` is a documented pandas no-op on `float64` columns — pandas re-coerces the replacement back to `NaN` rather than actually storing `None`, since a float64 array can't hold a Python `None`. **Verified by direct reproduction**: a DataFrame with a float column containing real `None`/`NaN` input, after `.where(df.notnull(), None)`, still reports `is None: False` for every row. Concretely, on the live dev DB, 4 of 8 trades in one dimension-breakdown group had `r_multiple = nan` (not `None`), which:
  - Made `ai/strategy_analytics/metrics.py::compute_dimension_breakdown()`'s `avg_r`/`total_r` compute to `NaN` (serialized as JSON `null`) instead of the intended `None`/`0.0`, even though the group had real wins/losses.
  - Would make `ai/trade_review/rules.py::classify_execution_alignment()`'s `if planned_rr is None: return UNKNOWN` **not fire** for a trade with unrecorded `planned_rr` — falling through to `planned_rr >= config.AI_STRATEGY_MIN_RR`, which for `NaN >= 3.0` is always `False` in Python, misclassifying the trade as **NOT_ALIGNED** instead of the honest **UNKNOWN**.
- **Reproduction:** `ai.trade_review.patterns.closed_trades()` on any DB containing a `CLOSED` trade with no `r_multiple`/`planned_rr`/`duration_minutes` recorded, then inspect `trade.get("r_multiple") is None` (`False`) vs `math.isnan(trade.get("r_multiple"))` (`True`).
- **Potential fix:** `df.astype(object).where(df.notnull(), None)` (cast to `object` dtype before `.where()`, which does allow `None`), or check `pd.isna(value)` instead of `value is None` at every consumer.

### VAL-006 — The live (forming) candle is read as if it were closed everywhere
- **Status: Resolved in Stage 21** (see this file's own commit in `git log` for the exact hash).
- **Subsystem:** `mt5/market_data.py:50` (`copy_rates_from_pos(..., 0, count)` never drops position 0, the still-forming bar) → `analysis/structure.py` (MSS/BOS at `.iloc[-1]`, swing confirmation window can include the forming bar), `analysis/structure.py` displacement, `analysis/liquidity.py` sweeps, `analysis/setup.py` retracement/entry.
- **Actual:** An MSS, a displacement candle, a liquidity sweep resolution, and a retracement/entry can all be computed from a bar that hasn't closed yet, then silently change or vanish once it does. A VALID/A+ result can appear and disappear within a single bar.
- **Root cause (confirmed in Stage 21, traced through every consumer, not assumed to be one
  file):** `mt5/market_data.py::get_candles()`'s live branch never marked or dropped the still-forming bar
  at position 0, and mock mode's `_mock_candles()` always generates its own last row as the current,
  still-open bar by construction. The bug reached **six independent call sites** that each call
  `analyze_structure()`/`compute_zones()`/`detect_sweeps()`/`detect_equal_levels()`/`detect_displacement()`/
  `classify_regime()` directly on the raw, unfiltered candle dict: `analysis/setup.py::detect_setup()`,
  `ai/strategy/evaluator.py::evaluate_deterministic()`, `api/snapshot.py::build_snapshot()`, three of
  `api/routes/market.py`'s four handlers (`/structure`, `/zones`, `/liquidity`, `/regime`), and `app.py` (the
  legacy Streamlit UI, still present, mirrors `build_snapshot()`'s wiring exactly). `ai/monitoring/engine.py`
  had no bug of its own — it only ever calls `detect_setup()`/`evaluate_deterministic()`.
- **Affected code path:** every structural read in the deterministic engine — swing/HH-HL-LH-LL labeling,
  MSS, BOS, liquidity sweep confirmation, displacement confirmation, retracement, and all zone
  computation (Previous Day/session highs-lows, VWAP, H1/H4 Swing High/Low) — for every timeframe (M5,
  M15, H1, H4), through every one of the six call sites named above.
- **Fix:** `mt5/market_data.py` now attaches `close_time` (open `time` + the timeframe's own duration) and
  `is_closed` (`close_time <= ` the authoritative current time, boundary inclusive) columns to every candle
  DataFrame — a candle's state is always derived from its own timestamp, never assumed from row position or
  count. A new `analysis/structure.py::closed_only(candles)` filters a `{timeframe: df}` dict down to closed
  rows only — the one place the filter logic lives, called explicitly at each of the six structural call
  sites (making the forming/closed distinction visible at the point of use, not hidden behind a changed
  default). None of the structural functions themselves changed — only *which* DataFrame reaches them.
  `current_price` (zone proximity, entry planning) is the one deliberate, explicitly-named exception,
  reading the unfiltered set's last close — real trading semantics: you enter at the live price, not the
  price as of the last confirmed 5-minute close. `analysis/setup.py::_plan_trade()`'s signature now takes
  the closed-only range and `current_price` as separate parameters, making that split explicit at the one
  place it's needed. `api/snapshot.py`'s `latest_m5_candle` display field and `/api/market/candles`
  (charting) are unchanged — legitimate forming-candle consumers, per the stage's own list.
- **Regression coverage:** 25 new tests. `tests/test_candle_state.py` — `is_closed`/`close_time` correctness
  (future/past/exact-boundary, all four timeframes, live via a `FakeMT5` and mock mode, mock-mode
  determinism). `tests/test_structure.py` — a real (unmocked) structural scenario reusing the file's own
  known-good bullish HH/HL fixture, proving a forming candle that WOULD flip the state to PULLBACK (proven
  via the unfiltered read) is correctly ignored once filtered to closed candles (the no-lookahead guard).
  `tests/test_setup.py` and `tests/test_strategy_evaluator.py` — argument-capture proofs that
  `detect_setup()`/`evaluate_deterministic()` pass only closed candles to sweep/displacement/retracement
  checks, plus a proof that `entry`/zone-proximity still correctly reflects the forming candle's current
  price (the legitimate exception). `tests/test_monitoring_engine.py` — two monitoring cycles whose candle
  histories differ only in a forming last bar (engineered to flip structure if leaked) produce zero alerts.
  Three pre-existing `tests/test_api.py` tests (`test_structure_endpoint_matches_analyze_structure`,
  `test_zones_endpoint_matches_compute_zones`, `test_regime_endpoint_matches_classify_regime`) were updated
  to compare against the same closed-only set the fixed routes now use — their prior assertions compared
  against an unfiltered computation, which is exactly the bug being fixed, not a correct baseline.
- **Verification result:** full suite 1101/1101 backend (1076 baseline + 25 new), 133/133 frontend, 14/14 E2E
  checklists, lint/typecheck/build all clean — zero regressions elsewhere.
- **Potential fix (superseded by the above):** ~~Drop the forming bar (fetch from position 1, or trim the
  last row when its close time is in the future) before any structural computation.~~ — implemented via
  explicit timestamp-derived state instead of a positional drop, per the stage's own instruction not to
  infer state from row position.

### VAL-007 — Previous Day High/Low is computed from an incomplete prior day
- **Status: Resolved in Stage 23A** (see this file's own commit in `git log` for the exact hash).
- **Subsystem:** `analysis/zones.py:29-33`, fed by `get_all_candles(300)` (300 M5 bars ≈ 25 hours).
- **Actual:** Early in the trading day, the M5 window only reaches a few hours into "yesterday," so Previous Day High/Low — a sweepable level and an R:R target source — is computed from a fraction of the actual prior session, worse the earlier in the day it's checked.
- **Potential fix:** Fetch enough M5 history to always cover the full prior calendar day (e.g. via a dedicated D1/H1 lookback), independent of the 300-bar window used for structure.
- **Root cause (confirmed):** `analysis/zones.py::compute_zones()` built Previous Day High/Low from the
  same 300-bar M5 window every caller fetches (`get_all_candles(300)` ≈ 25 h), so before ~01:00 of the next
  day the "previous day" was only its last few hours.
- **Fix:** Previous Day High/Low now come from the closed **H1** candles every caller already passes in
  (300 H1 bars ≈ 12 days, so the prior day is always complete — no new fetch, no wider M5 window).
  `_previous_trading_day_range()` is the one place this lives. Current Day High/Low and the session levels
  still come from M5.
- **Regression coverage:** `tests/test_zones.py` — an M5 window holding only yesterday's last 3 h (whose
  M5-only high is 100.5) yields the true 115.5 prior-day high from H1; the existing PDH/PDL test now feeds H1.

### VAL-008 — The "opposing M5 structure" invalidation check fires on the setup's own normal precursor state, and INVALIDATED isn't sticky
- **Status: Resolved in Stage 23A** (see this file's own commit in `git log` for the exact hash).
- **Subsystem:** `analysis/setup.py:115-120`, `ai/strategy/rules.py:62-67`.
- **Actual:** A bullish M5 MSS can only occur when M5 was previously in a BEARISH (LH+LL) structure — that's the expected state right after a low sweep, while a candidate is waiting for its MSS. The invalidation check reads `m5.state == "BEARISH"` at face value and can mark a fresh, otherwise-valid candidate INVALIDATED immediately instead of DEVELOPING. Separately, `detect_setup`/`evaluate_deterministic` keep no state between calls, so an INVALIDATED candidate can reappear as DEVELOPING/VALID on the very next evaluation with the same sweep.
- **Potential fix:** Check that the opposing structure break occurred *after* the MSS that validated the candidate, not just its current state; persist an explicit invalidated-candidate marker if INVALIDATED is meant to be sticky.
- **Root cause (confirmed):** both the Stage 1 INVALIDATED branch and the Stage 4
  `is_opposing_mss_invalidated()` read `m5.state` at face value. A BUY candidate's own precursor (a
  bearish M5 leg into the low sweep, before its MSS) is exactly `m5.state == "BEARISH"`, so a fresh
  candidate could be INVALIDATED immediately; and nothing tied an invalidation to the candidate.
- **Fix:** new `analysis/sequence.py::evaluate_sequence()` (shared by `detect_setup()` and
  `evaluate_deterministic()`). Invalidation is defined only *after* the candidate's MSS: any closed M5 bar
  after the MSS bar closing back beyond the sweep bar's extreme. Stickiness needs no persisted state — the
  inputs are closed bars, which never change, so the same sweep stays invalidated for as long as it is the
  candidate (a later recovery bar doesn't resurrect it). The deliberate consequence: an opposing M5 state
  *before* the MSS is DEVELOPING, not INVALIDATED/INVALID.
- **Regression coverage:** `tests/test_sequence.py` (precursor ≠ invalidation; close below the swept low
  after the MSS invalidates and stays invalidated after a recovery; wick-only break doesn't),
  `tests/test_setup.py::test_bearish_m5_precursor_after_a_low_sweep_is_not_invalidation` (real sequence, the
  exact old failing case), `tests/test_strategy_evaluator.py::test_bearish_m5_precursor_before_the_mss_is_not_invalid`.

### VAL-009 — MSS, displacement, and retracement must all be true on the literal same latest bar
- **Status: Resolved in Stage 23A** (see this file's own commit in `git log` for the exact hash).
- **Subsystem:** `analysis/setup.py:128-163`, `analysis/structure.py:154` (`last = df.iloc[-1]`).
- **Actual:** The documented sequence is sweep → MSS → displacement → retracement (separate, sequential steps), but the code requires the current bar to simultaneously be the MSS-confirming close, a >1.5×ATR displacement body, and a 20-79%-retraced close — a materially narrower condition than documented. A retracement occurring on any bar after the displacement bar can never be recognized.
- **Potential fix:** Track the displacement bar once detected and evaluate retracement against subsequent bars relative to it, rather than requiring all three conditions on `iloc[-1]`.
- **Root cause (confirmed):** `detect_setup()`/`evaluate_deterministic()` read MSS (`m5.last_mss`),
  displacement (`detect_displacement()` on `iloc[-1]`) and retracement (`_check_retracement()` on
  `iloc[-1]`) all off the latest bar, so the documented sweep → MSS → displacement → retracement sequence
  could only be seen if the latest bar was simultaneously the break, the impulse and the pullback.
- **Fix:** `analysis/sequence.py` locates each step on its own closed bar, in order, from the sweep bar:
  MSS = first close at/after the sweep beyond the last opposing swing confirmed before it; displacement =
  first ATR-outsized body at/after the sweep (via the new `structure.displacement_at(df, i)`, which
  `detect_displacement()` now wraps unchanged); retracement = the latest bar only if it is strictly after
  both the MSS and displacement bars, measured from the sweep extreme to the best price since. The
  checklist/criterion names are unchanged; `_check_retracement()` is removed. `context["displacement"]`
  (latest-bar display) is kept.
- **Regression coverage:** `tests/test_sequence.py` (full sequence spread over bars 30/32/34 is recognized;
  retracement on the displacement bar itself doesn't count; SELL mirror), and
  `tests/test_setup.py::test_sequence_spread_over_separate_bars_reaches_valid` end to end (VALID while the
  latest bar alone shows no displacement — impossible before this fix).

### VAL-010 — R:R risk uses `abs(entry − stop_loss)` with no check that the stop is on the correct side of entry, and the A+ gate rounds before comparing
- **Status: Resolved in Stage 23A** (see this file's own commit in `git log` for the exact hash).
- **Subsystem:** `ai/strategy/rules.py:127` (risk calc), `:131,136` (`round(reward/risk, 2)` then `rr >= min_rr`).
- **Actual:** If price has traded back through the stop level before the evaluator runs, `abs()` still yields a positive "risk" and a plausible-looking R:R for a trade whose stop has effectively already been hit. Separately, `round(reward/risk, 2) >= min_rr` lets a true ratio like 2.996 round to 3.0 and pass a locked 1:3 minimum it doesn't actually meet.
- **Potential fix:** Use a signed risk (`entry − SL` for BUY, `SL − entry` for SELL) and reject `<= 0`; compare the unrounded ratio against `min_rr`, rounding only for display.
- **Root cause (confirmed):** `rules.compute_risk_reward()` used `abs(entry − stop_loss)` and
  `passes_min_rr()` compared `round(reward/risk, 2)`. This was live in the test suite itself:
  `tests/test_strategy_evaluator.py::test_full_a_plus_sell`'s fixture had its SELL stop (100.60) *below*
  entry (101.5) and only rated A+ through the `abs()`.
- **Fix:** `rules.signed_risk()` — `entry − SL` for BUY, `SL − entry` for SELL; `≤ 0` → no R:R, with its
  own evidence line ("already beyond the stop level … effectively been hit") instead of "no target".
  `compute_risk_reward()` returns the unrounded ratio, `passes_min_rr()` compares it unrounded, and
  `display_rr()` floors to 2 dp for display, so a shown ratio never overstates the real one. The SELL
  fixture above was corrected to a swept high above entry. `analysis/setup.py::_plan_trade()` already used
  signed risk — unchanged.
- **Regression coverage:** `tests/test_strategy_rules.py` (2.996 fails 1:3 and displays 2.99; wrong-side
  stop → None for BUY and SELL), `tests/test_strategy_evaluator.py::test_stop_already_breached_yields_no_rr_and_says_so`
  and `::test_rr_just_under_minimum_is_not_rounded_up_to_pass`.

### VAL-011 — No staleness check before deterministic analysis runs
- **Status: Resolved in Stage 23A** (see this file's own commit in `git log` for the exact hash).
- **Subsystem:** `analysis/setup.py`/`ai/strategy/evaluator.py::evaluate_current_setup()` — neither calls `mt5.market_data.is_stale()`, which exists but is only wired into the UI header/snapshot display.
- **Actual:** A frozen/disconnected feed keeps producing a VALID/A+ result indefinitely (over a weekend, or during an MT5 outage) since nothing in the analysis path itself checks candle recency (and VAL-003's UTC mislabeling would defeat the check even if it were added naively).
- **Potential fix:** Thread an explicit staleness check into `evaluate_current_setup()`/`detect_setup()`, surfaced as part of the result rather than only in a separate UI badge.
- **Root cause (confirmed):** `mt5.market_data.is_stale()` (tick age, mock-exempt) was only wired
  into the header/snapshot display; the analysis path never checked data recency.
- **Fix:** `analysis/structure.py::is_feed_stale(m5, now)` — the newest M5 row (closed or forming) opened
  more than one bar + `DATA_STALE_SECONDS` ago. It reads the candles themselves, so it guards analysis
  directly, and relies on VAL-003's UTC fix (Stage 19). `evaluate_deterministic()` adds a **Data Freshness**
  criterion (a stale feed can never rate A+ — it becomes DEVELOPING with the condition missing);
  `detect_setup(candles, now=None)` downgrades VALID → DEVELOPING with a stale reason and
  `context["data_stale"]`. Both default `now` to the wall clock, so the live routes are covered with no
  caller change; `ai/monitoring/engine.py` passes its own `now` to `evaluate_deterministic()` already.
  **Follow-up:** `ai/monitoring/engine.py` should also pass `now` to `detect_setup()` (it defaults to the
  wall clock today, which is correct but not the cycle's own clock) — left untouched here because that file
  belonged to the parallel monitoring lane.
- **Regression coverage:** `tests/test_structure.py::test_is_feed_stale_uses_the_newest_candle_time`
  (exact boundary), `tests/test_setup.py::test_stale_feed_never_reports_valid`,
  `tests/test_strategy_evaluator.py::test_stale_feed_never_rates_a_plus`. `tests/test_strategy_api.py`'s
  candle fixture is now anchored to the real clock (it goes through the live route's wall-clock `now`).

### VAL-012 — Journal `trade_date` (UTC) and `trade_time` (local) are captured inconsistently, and can misdate a trade permanently
- **Status: Resolved in Stage 22** (see this file's own commit in `git log` for the exact hash).
- **Subsystem:** `frontend/components/journal/new-trade-form.tsx` (`trade_date: now.toISOString().slice(0,10)` — UTC; `trade_time: now.toTimeString().slice(0,8)` — local).
- **Actual:** For a user outside UTC, a trade entered in the evening (behind UTC) or early morning (ahead of UTC) can be stored a full calendar day off from when it actually happened. Since entry-time journal fields are immutable by design, this is permanent, and it also skews which digest period (VAL-004) a trade falls into. The Streamlit UI (`ui/journal.py`) uses local date and local time for the same fields — the two entry paths disagree with each other and with "Today P/L" (which uses UTC date elsewhere).
- ~~**Potential fix:** Use one consistent timezone (UTC, matching the rest of the system's internal-UTC convention) for both `trade_date` and `trade_time` capture in the Next.js form.~~ *(Superseded by the Stage 22 fix below — the project's existing session timezone, not hardcoded UTC, and all three write/read points, not only the Next.js form.)*
- **Root cause (confirmed in Stage 22, traced through every write and read of `trade_date`/`trade_time`):**
  three independent points resolved "now" against four different clocks, none of them the project's
  configured session timezone: (1) `frontend/components/journal/new-trade-form.tsx` sent the browser's UTC
  calendar date with the browser's local wall-clock time; (2) `ui/journal.py` defaulted both fields to the
  Streamlit machine's local date/time; (3) `journal/trades.py::today_r_total()` defaulted "today" to the UTC
  date. The backend (`api/routes/journal.py::create_trade()` → `journal.trades.create_trade()`) stored
  whatever it was given verbatim. Meanwhile `ai/digest/service.py` already interprets `trade_date` as a
  `config.SESSION_TIMEZONE`-local date (its `_now()` and period bounds use that zone), so the writers never
  honored the convention the reader assumed. Note: the stage brief's "MT5 deal time → journal creation" step
  does not exist in this codebase — `journal.trades.create_trade()` has exactly two production callers (the
  Next.js route and the Streamlit form), neither derived from `mt5.history_deals_get()`.
- **Fix:** one journal clock, `journal/trades.py::session_now()` =
  `datetime.now(ZoneInfo(config.SESSION_TIMEZONE))` (the same boundary as the digest's `_now()`).
  `api/routes/journal.py::create_trade()` now captures `trade_date`/`trade_time` server-side from a single
  `session_now()` call (both fields split from the same aware instant) whenever the client omits them, and
  `new-trade-form.tsx` no longer computes them (the form was already documented as fully automatic capture).
  For API compatibility (the E2E checklists and any backfill client), `TradeCreateIn`/`TradeCreateInput`
  keep both fields as optional: an explicit pair is stored as a session-local backfill, and supplying only
  one is rejected with 422, since it would mix client and server clocks. `today_r_total()`'s default uses
  `session_now().date()`. `ui/journal.py`'s date/time pickers stay
  editable (backfilling is legitimate) but default to `session_now()` instead of the machine clock. No schema
  change, no change to `create_trade()`/`close_trade()`/`list_trades()`/`get_trade()`, analytics formulas,
  digest period math, or strategy logic.
- **Regression coverage:** new `tests/test_journal_timezone.py` (all instants frozen via monkeypatched
  `session_now`): `session_now()` is aware and in the configured zone across UTC/New York/Tokyo/Nicosia and
  matches the digest clock; API-created trades get the session-local date when UTC is already tomorrow
  (New York 23:55) and when UTC is still yesterday (Tokyo 00:05); date+time reconstruct the exact original
  instant; an explicit date+time pair is stored as given, a lone date or time is rejected (422, nothing
  stored); the Next.js form no longer computes either field; one second either side of session midnight;
  `today_r_total()` default follows the session-local day, not UTC; end-to-end API → `build_digest()` proves
  a Sunday 23:55 New York trade lands in its own week and a Monday 00:05 trade in the next; Streamlit form
  defaults come from `session_now()`, never the machine clock.

---

## P2 — Medium

| ID | Subsystem | Summary | Evidence | Suggested fix direction |
|---|---|---|---|---|
| VAL-013 | `analysis/structure.py:108-118` | **Resolved in Stage 23A** (see below) — BOS reported against an already-superseded prior swing (off-by-one) — can fire "bullish BOS" while price is retracing below the latest confirmed high. | `prior_high.price < last_high.price` always holds since `last_high` is the labeled HH, so `last_close > prior_high.price` is too easy to satisfy. | Compare against `last_high.price`, not `prior_high.price`. |
| VAL-014 | `analysis/zones.py:39-47`, `analysis/liquidity.py:43-55` | **Resolved in Stage 23A** (see below) — Session-level (Asian/London H/L) includes the bar under test and later bars — an in-session sweep of the session's own current extreme can never register, and an earlier genuine sweep can "disappear" once a later bar extends the extreme. | Levels recomputed from the full session including future bars relative to the sweep check. | Compute session levels only from bars strictly before the one being tested for a sweep. |
| VAL-015 | `analysis/zones.py:29` | **Resolved in Stage 23A** (see below) — On a Monday, "Previous Day" resolves to Sunday (near-empty/no bars), never Friday. | `today - 1 day` with no weekend skip. | Skip back to the last day with real session data. |
| VAL-016 | `mt5/account.py:83-106`, `risk/fundednext.py:52-61` | **Status: Resolved (Lane C).** The deal-type filter landed in Stage 19; Lane C adds commission, swap and fee to each trade deal's realized P/L (`mt5/account.py::_realized_pnl`), so `day_start_balance` matches the real balance change. Regression: `tests/test_mt5_risk_hardening.py`. Original finding: Daily P&L / trading-days-completed sums *every* deal type from `history_deals_get`, including deposits/balance adjustments — can misclassify a deposit as a "profitable trading day" and falsely trigger the FundedNext consistency-rule warning. | No filter on `d.type`/`d.entry`; commission/swap also excluded. | Filter to actual trade-close deals only; include commission/swap in realized P&L. |
| VAL-017 | `mt5/account.py` | **Status: Not reproducible in current code; adjacent gap fixed (Lane C).** Since Stage 19 every deal time goes through `mt5/timeutil.to_utc()` once and back to the server zone once. A test pins a 23:30 Nicosia deal to its own server day, which a double shift would move to the next day. While checking, Lane C found that `history_deals_get()`'s window ended at true-UTC now, although deal epochs are server wall-clock (ahead of UTC). That dropped the last 2-3 hours of deals from today's realized P/L, so the window now ends a day ahead. Still needs confirming against a live terminal. Original finding: Suspected double timezone application on deal timestamps (UTC tag then `Europe/Nicosia` conversion) — **inference only, not verified against a live terminal** since `MODE=mock` throughout this pass. | Flagged by code inspection, not reproduced live. | Confirm against a real MT5 connection before treating as confirmed. |
| VAL-018 | `analysis/structure.py:104-116` | **Resolved in Stage 23A** (see below) — `last_mss` means "close is currently beyond the last confirmed swing," not "a shift just happened" — no recency bound, can flicker on/off bar to bar (compounded by VAL-006). | Docstring/comment at `setup.py:91-95` calls it a "did a shift just happen" signal; code doesn't check recency. | Add an explicit recency window or a "shift bar index" the MSS is tied to. |
| VAL-019 | `ai/monitoring/rules.py` (4 of 6 dedup keys), `ai/monitoring/engine.py:115-122` | **Resolved in Stage 23B** (see below) — Dedup keys for SETUP_STATE_CHANGED/APLUS_SETUP_INVALIDATED/RISK_STATUS_CHANGED/MI_QUALITY_CHANGED embed the cycle timestamp; if a cycle partially fails after inserting alerts but before `_last_snapshot` updates, the next cycle can re-detect and re-send the same transition (duplicate Telegram message too). Contradicts the store's own "never insert two rows for the same transition" docstring for these 4 types. | `ai/monitoring/store.py:9-13`'s claim only actually holds for APLUS_SETUP_DETECTED/HIGH_IMPACT_EVENT_NEAR. | Update `_last_snapshot` before persisting, or make the timestamp component coarser/omit it from the dedup key. |
| VAL-020 | `ai/notifications/delivery.py:96-118` | **Resolved in Stage 23B** (see below) — A message that sends successfully but whose `mark_sent()` write then fails stays PENDING and resends next cycle; a provider exception type not explicitly handled (e.g. `httpx.InvalidURL`) can wedge the whole delivery cycle, bypassing `TELEGRAM_MAX_RETRIES` entirely for every queued item. | Code reads `except httpx.TimeoutException / httpx.HTTPError` specifically. | Broaden the caught exception type or wrap per-delivery; make `mark_sent` failure non-fatal to the loop. |
| VAL-021 | `ai/monitoring/engine.py`, `ai/notifications/delivery.py`, `ai/digest/service.py` | **Resolved in Stage 23B** (see below) — All three `asyncio.create_task`-scheduled background loops perform blocking I/O (MT5 reads, HTTP calls, SQLite) directly inside their coroutine with no `asyncio.to_thread` — freezes every other `async` handler (including the WebSocket) for the duration of a cycle. | `run_monitoring_cycle()`/`attempt_deliveries()`/`run_digest_cycle()` bodies. | Wrap the synchronous work in `asyncio.to_thread(...)`. |
| VAL-022 | `ai/notifications/delivery.py:49-58` | **Resolved in Stage 23B** (see below) — Turning Telegram on (or re-enabling after downtime) immediately queues up to 100 historical alerts for delivery, including long-stale A+ setups, none marked as historical. | `monitoring_store.list_alerts(limit=100)` with no time/acknowledged filter. | Filter to alerts created after the delivery worker's own start time, or exclude already-acknowledged ones. |
| VAL-023 | `ai/monitoring/rules.py:51,71` | **Resolved in Stage 23B** (see below) — Some A+→A+ transitions (opposite direction; a new sweep replacing the prior one without an intervening non-A+ state) produce no alert at all — the new entry/SL/TP is never announced. | Both rules only fire on a *cross into* A+, not a change while already A+. | Also fire when `aplus_direction` or the candidate identity changes while `aplus_rating` stays A+. |
| VAL-024 | `journal/trades.py::close_trade`, `api/routes/journal.py` | **Status: Resolved (Lane D).** Fix: `close_trade()`'s UPDATE now carries `AND status = 'OPEN'` and returns whether a row was closed; the route answers 409 for a trade that isn't OPEN (also covering two concurrent closes). Regression: `tests/test_journal_hardening.py`. Original finding: Re-submitting `PATCH .../close` on an already-closed trade silently overwrites `result`/`pnl`/`r_multiple` (no `WHERE status='OPEN'` guard) — any omitted optional field on the second call gets nulled out. | Route only checks the trade exists, not its current status. | Reject (409/400) a close attempt on a trade whose status isn't OPEN. |

---

### Stage 23A resolutions (P2)

- **VAL-013** — `analysis/structure.py::analyze_structure()` now measures BOS against the latest confirmed
  swing (`last_high`/`last_low`); the superseded `prior_high`/`prior_low` comparison is gone. Coverage:
  `tests/test_structure.py::test_bos_not_reported_against_superseded_prior_swing_high` (the exact old false
  positive: 120 < close 122 < HH 128), `::test_bos_confirmed_on_close_beyond_latest_swing_high`,
  `::test_bearish_bos_measured_against_latest_swing_low`. The old BOS test — and
  `tests/test_regime.py::test_bullish_bos_yields_breakout_regime`, which reused its fixture — documented the
  buggy definition and were rewritten to the corrected one.
- **VAL-014** — `analysis/liquidity.py::detect_sweeps()` now tests each bar against the Asian/London
  session extreme from bars **strictly before it** (same date, same `zones._session_mask`), and the
  resulting `LiquidityEvent.level_price` is that pre-sweep level, so the A+ stop buffer anchors to the level
  actually swept. `compute_zones()`'s displayed session levels are unchanged. PDH/PDL and H1/H4-swing
  levels were already prior-only. Coverage: `tests/test_liquidity.py` (in-session sweep of the session's own
  prior low registers at 99.8; an earlier sweep survives a later bar extending the low).
- **VAL-015** — Previous Day now resolves to the most recent **weekday** before today that has bars (see
  VAL-007's fix — the same function), so Monday → Friday and the Sunday re-open stub is skipped. Coverage:
  `tests/test_zones.py::test_previous_day_on_monday_is_friday_not_sunday_stub`,
  `::test_no_previous_day_zone_without_prior_weekday_history`.
- **VAL-018** — the M5 MSS used by the setup/A+ checklist is now tied to a concrete shift bar at/after
  the sweep (`SequenceResult.mss_index`, see VAL-009). `StructureResult.last_mss` keeps its meaning
  (H1 direction gating relies on it) but its field comment now states it honestly as a no-recency *state*;
  the misleading "did a shift just happen" comment in `analysis/setup.py` is gone. Coverage:
  `tests/test_setup.py::test_mss_case_d_current_close_beyond_swing_without_a_shift_bar_is_not_confirmed`,
  `tests/test_strategy_rules.py::test_m5_mss_confirmation_requires_a_shift_bar_after_the_sweep`.
  Behavior change to note: since the sequence starts at the sweep, an M5 MSS/displacement with no qualifying
  sweep behind it no longer counts as a checklist step (`test_mss_alone_does_not_create_valid_setup` now
  expects NO SETUP rather than DEVELOPING).

### Stage 23B resolutions

- **VAL-019** — Root cause: four transition dedup keys ended in the *current* cycle's timestamp, so a
  retry of a partially failed cycle (alerts inserted, baseline not yet advanced) built new keys and slipped
  past the UNIQUE index. Fix: `ai/monitoring/rules.py` keys those four transitions on the *previous*
  (baseline) snapshot's timestamp. A retry diffs against the same baseline, rebuilds identical keys, and
  the index absorbs it; a genuine later repeat still gets a new key because the baseline has moved on.
  `ai/monitoring/engine.py` also advances `_last_snapshot` once every alert is persisted, before the
  retention purge, so a failing purge can't pin the diff to a stale baseline. Coverage:
  `tests/test_monitoring_rules.py::test_transition_dedup_keys_are_anchored_to_the_baseline_not_the_cycle`,
  `::test_same_transition_from_a_later_baseline_is_a_new_alert`,
  `tests/test_monitoring_engine.py::test_insert_that_fails_mid_cycle_does_not_duplicate_on_retry`,
  `::test_failing_purge_still_advances_the_baseline`.
- **VAL-020** — Root cause: `attempt_deliveries()` had no per-delivery isolation, and it treated a
  failed `mark_sent()` like a failed send. Fix: each delivery runs in its own try. A provider exception
  `send()` doesn't classify (e.g. `httpx.InvalidURL`) marks only that delivery FAILED and retryable, so
  `TELEGRAM_MAX_RETRIES` applies; only the exception *type* goes into the error, never its text, which can
  carry the token-bearing URL. A delivery Telegram accepted but that couldn't be marked SENT is remembered
  in-process (`_sent_unrecorded`), and the next cycle retries the write instead of the send. Coverage:
  `tests/test_notifications_delivery.py::test_mark_sent_failure_never_causes_a_resend`,
  `::test_unexpected_provider_exception_fails_only_that_delivery`.
- **VAL-021** — Root cause: each `run_forever()` called its synchronous cycle directly on the event loop.
  Fix: the monitoring, delivery and digest loops now `await asyncio.to_thread(<cycle>)`. Coverage:
  `tests/test_monitoring_engine.py::test_run_forever_runs_the_cycle_off_the_event_loop_thread`,
  `tests/test_notifications_delivery.py::test_delivery_loop_runs_off_the_event_loop_and_logs_failures`,
  `::test_digest_loop_runs_off_the_event_loop_and_logs_failures` (the cycle must run on a different thread
  from the loop).
- **VAL-022** — Root cause: discovery queued anything in `list_alerts(limit=100)` without a delivery row.
  Fix: the delivery `run_forever()` records its own start time (`mark_worker_started()`), and discovery
  only queues alerts created at or after it. Alerts raised while delivery was off stay visible in the app
  but are never sent to Telegram. Coverage:
  `tests/test_notifications_delivery.py::test_discovery_only_queues_alerts_after_worker_start`.
- **VAL-023** — Root cause: `aplus_setup_detected()` fired only on a cross into A+. Fix: it also fires
  when the rating stays A+ but the direction or the candidate identity changes. `MonitoringSnapshot` gains
  `aplus_candidate_key` (the strategy result's `candidate_sweep_time`). The existing
  `APLUS_SETUP_DETECTED:{direction}:{sweep_time}` key already tells the new setup apart from the one it
  replaces, and no invalidation alert is emitted, because the rating never left A+. Coverage:
  `tests/test_monitoring_rules.py::test_aplus_setup_detected_fires_when_direction_flips_while_a_plus`,
  `::test_aplus_setup_detected_fires_when_a_new_candidate_replaces_the_prior_one`,
  `::test_aplus_setup_detected_stays_quiet_for_the_same_a_plus_candidate`.
- **Stage 23A follow-up** — `ai/monitoring/engine.py` now calls `detect_setup(candles, now=now)` with the
  same cycle clock it passes to `evaluate_deterministic()`. Coverage:
  `tests/test_monitoring_engine.py::test_detect_setup_receives_the_cycles_own_now`.
- **VAL-024** is not addressed here. Its fix belongs in `journal/trades.py`/`api/routes/journal.py`,
  which were outside Stage 23B's scope.

## P3 — Low

- **VAL-025** `analysis/liquidity.py:69-80` — a run of 3+ equal highs/lows emits a duplicate event for the shared middle point (display-only impact, `[-3:]` slicing in evidence text).
  - **Status: Resolved in Stage 23A.** Fix: `detect_equal_levels()` emits at most one event per swing point that equals any earlier one, so a run of 3+ equal highs/lows no longer duplicates the shared later points. Regression coverage: `tests/test_liquidity.py::test_run_of_three_equal_highs_emits_one_event_per_later_swing`.
- **VAL-026** `analysis/liquidity.py:39-55` — two named levels sharing a price (e.g. Asian Low == H1 Swing Low) produce two sweep events for one wick; `select_candidate`'s tie-break picks one arbitrarily, so the displayed `level_name` is arbitrary.
  - **Status: Resolved in Stage 23A.** Fix: `detect_sweeps()` merges sweeps of the same kind, bar and price into one event (`_merge_coincident_sweeps`); `level_name` is always the first name in `SWEEPABLE_*_LEVELS` order (deterministic) and the label lists every level swept (e.g. "Previous Day Low + H1 Swing Low swept"). Regression coverage: `tests/test_liquidity.py::test_two_levels_at_one_price_swept_by_one_wick_are_one_event`, `::test_levels_at_different_prices_stay_separate_events`.
- **VAL-027** `mt5/market_data.py`, `mt5/account.py` — mock data uses Python's randomized `hash()` with no `PYTHONHASHSEED` pinned, so it is *not* actually deterministic across restarts despite the docstrings' claim (mock mode only).
  - **Status: Resolved (Lane C).** Fix: new `stable_seed.py` (SHA-256 of the seed parts) replaces `hash()` in the mock seeds of `mt5/market_data.py`, `mt5/account.py`, and also `ai/market_intelligence/providers/mock.py`, which had the same bug. A test runs the seed functions under three different `PYTHONHASHSEED` values and gets identical seeds. Regression coverage: `tests/test_mt5_risk_hardening.py`.
- **VAL-028** `mt5/connection.py:62-68` — `connect()` returns success even when the configured symbol isn't available in the terminal; surfaces later only as a generic "no candle data" error.
  - **Status: Resolved (Lane C).** Fix: `mt5/market_data.py`'s "No candle data"/"No tick data" errors now append `connection.last_error()` (e.g. "Symbol 'XAUUSD' not found or unavailable from this broker.") whenever `symbol_ready()` is false, so the snapshot's `data_error` names the real cause. `connect()` itself is unchanged (frozen file), and it still correctly reports that the terminal is up. Regression coverage: `tests/test_mt5_risk_hardening.py`.
- **VAL-029** `api/routes/journal.py` — trade insert and its FundedNext snapshot write are two separate DB connections/statements; a failure between them leaves a trade with no risk snapshot and a bare 500.
  - **Status: Resolved (Lane D).** Fix: `api/routes/journal.py::create_trade` computes the FundedNext status and rules BEFORE writing anything, then inserts the trade, its context and its snapshot on one connection with one commit (`create_trade`/`save_snapshot` take an optional `conn`); any failure rolls everything back and returns a 500 that says nothing was saved. Regression coverage: `tests/test_journal_hardening.py`.
- **VAL-030** `risk/fundednext_journal.py` — `fundednext_context` has no `UNIQUE(trade_id)` constraint; "never updated after creation" is a convention, not structurally enforced.
  - **Status: Resolved (Lane D).** Fix: `init_table()` adds `CREATE UNIQUE INDEX IF NOT EXISTS idx_fundednext_context_trade_id`; an existing DB is first deduplicated (keeping the earliest row per trade, the genuine creation-time snapshot, and logging a warning), so the index also applies to old dev DBs without crashing startup. Regression coverage: `tests/test_journal_hardening.py`.
- **VAL-031** `risk/fundednext.py`, `risk/models.py` — `Phase` only has CHALLENGE/FUNDED; a Stellar 2-Step phase-2 trader would see the phase-1 (8%) profit target rather than phase-2's, since no phase-2 case exists.
  - **Status: Resolved (Lane C).** Fix: new `Phase.CHALLENGE_PHASE2` (`"challenge_phase2"`); `compute_status()` uses `profit_target_phase2_pct` (2-Step 5%, Lite 4%) and the 5-day minimum for it; the account selector offers "Challenge · Phase 1 / Phase 2". The stored `"challenge"` value still means phase 1. Known limit: completed trading days come from recent deal history, not the phase start date, which MT5 doesn't expose. Regression coverage: `tests/test_mt5_risk_hardening.py`.
- **VAL-032** `api/schemas.py`, `journal/trades.py::compute_analytics` — `result` isn't validated against WIN/LOSS/BE at the API layer; an unexpected value (e.g. lowercase `"win"`) would count toward `total_trades` but not toward wins/losses/breakeven, silently deflating the win rate. Not reachable via the shipped UI's fixed WIN/LOSS/BE buttons.
  - **Status: Resolved (Lane D).** Fix: `TradeCloseIn.result` is `Literal["WIN","LOSS","BE"]` after a before-validator strips and uppercases it (`"win"` is accepted and stored as `WIN`, `"WON"` gets a 422); `compute_analytics()` also normalizes case, so rows stored before this still count. Regression coverage: `tests/test_journal_hardening.py`.
- **VAL-033** All three background loops — bare `except Exception: pass` with no logging; a persistently failing loop has no operator-visible signal it died.
  - **Status: Resolved in Stage 23B.** Fix: the monitoring, delivery and digest loops (and the digest's per-type send) now call `logger.exception(...)` on a failed cycle, so the traceback is logged and the loop carries on. Regression coverage: `tests/test_monitoring_engine.py::test_run_forever_logs_a_failed_cycle`, `tests/test_notifications_delivery.py::test_delivery_loop_runs_off_the_event_loop_and_logs_failures`, `::test_digest_loop_runs_off_the_event_loop_and_logs_failures`.
- **VAL-034** `ai/notifications/providers/telegram.py` — Telegram's `retry_after` on a 429 isn't honored; the fixed linear backoff can exhaust `TELEGRAM_MAX_RETRIES` before a real rate limit clears.
  - **Status: Resolved in Stage 23B.** Fix: on a 429 the provider reads `parameters.retry_after`, or the `Retry-After` header as a fallback, into `DeliveryResult.retry_after_seconds`. The delivery worker then pauses the whole channel until that time passes, since Telegram's limit is per bot, and stops the current cycle, so the other queued deliveries don't burn retries on further 429s. Regression coverage: `tests/test_notifications_providers.py::test_rate_limit_surfaces_telegrams_retry_after`, `::test_rate_limit_falls_back_to_the_retry_after_header`, `::test_non_rate_limit_errors_carry_no_retry_after`, `tests/test_notifications_delivery.py::test_rate_limit_retry_after_pauses_the_whole_channel`.
- **VAL-035** `ai/notifications/formatter.py:78-79` — cosmetic: an UNKNOWN risk status renders as `"Daily loss used: unavailable%"`.
  - **Status: Resolved in Stage 23B.** Fix: a new `_fmt_pct()` adds `%` only to a real number, so a missing value renders as plain `unavailable`. Regression coverage: `tests/test_notifications_formatter.py::test_risk_status_unknown_renders_unavailable_without_a_percent_sign`.
- **VAL-036** Logging config — nothing currently sets `httpx`'s logger below INFO explicitly; if any future logging config raises the root/httpx logger to INFO, its own request-URL log line (which embeds the bot token) would start leaking it. No active leak found in any currently-reachable code path.
  - **Status: Resolved (Lane C).** Fix: new `log_safety.py`, installed from `api/main.py`, pins the `httpx`/`httpcore` loggers to WARNING and adds a filter that rewrites any `/bot<token>` path segment to `/bot<redacted>`, so the token stays out of the log even if a later config lowers the level again. Regression coverage: `tests/test_ai_text_hardening.py`.
- **VAL-037** `ai/knowledge/retrieval.py` + `api/routes/knowledge.py` — a user-submitted knowledge note's title/content is rendered into the system prompt with the same `### Label ###` framing as the CONTEXT block, with no escaping; ground rule 6 instructs the model to treat it as inert, so this is a structural weakness rather than a demonstrated exploit under `AI_PROVIDER=mock`.
  - **Status: Resolved (Lane C).** Fix: `ai/prompts.py` collapses a knowledge note's title/source/version to one line and breaks up `###` runs, and prefixes every line of a knowledge or memory body with `> `, so user text can no longer start a line that looks like a CONTEXT/section header. Regression coverage: `tests/test_ai_text_hardening.py`.
- **VAL-038** `ai/context.py` — the STALE freshness label reaches the LLM's price line only; structure/zones/sweep/setup sections built from the same candles, and the A+ evaluator's own output, carry no freshness marker at all.
  - **Status: Resolved (Lane C).** Fix: `ai/context.py` now puts an explicit `DATA FRESHNESS: STALE` line at the top of both the Market Structure and Setup sections (and `STALE data` in their UI detail) whenever the snapshot's price is stale, not just on the price line. The A+ evaluator's own freshness handling belongs to VAL-011. Regression coverage: `tests/test_ai_text_hardening.py`.
- **VAL-039** `ai/knowledge/chunking.py` — splits on a fixed character window rather than paragraph boundaries (contradicting its own docstring); can split a sentence — and a negation — across two chunks.
  - **Status: Resolved (Lane C).** Fix: `ai/knowledge/chunking.py` now packs whole paragraphs, then whole sentences, and hard-wraps on word boundaries only for a single sentence longer than the chunk size, so a sentence and its negation always stay in one chunk. Already-stored chunks are unchanged until their document is re-ingested. Regression coverage: `tests/test_ai_text_hardening.py`.
- **VAL-040** `ai/strategy/evidence.py:184,257` — a closed trade's outcome renders as its stored uppercase result (`WIN`/`LOSS`/`BE`) but an open trade renders as the hardcoded lowercase literal `"open"` — a cosmetic casing inconsistency, present in both AI explanations and Trade Review's historical-similarity text (both reuse this function).
  - **Status: Resolved (Lane C).** Fix: `ai/strategy/evidence.py`'s `_outcome_label()` renders every outcome uppercase (`WIN`/`LOSS`/`BE`/`OPEN`/`UNKNOWN`) in both `historical_context()` and `render_for_llm()`. Regression coverage: `tests/test_ai_text_hardening.py`.

---

## Coverage note

Three parallel code-level review passes were run in isolated git worktrees; two (risk/journal/monitoring/Telegram, and the deterministic core) correctly read the current branch (`837f8b5`). The third (AI/RAG/memory/analytics layer) was given a worktree that had checked out a stale ref (Stage 5, `3d5b0ea`) and could not reach `ai/memory/`, `ai/similarity/`, `ai/market_intelligence/`, `ai/explanations/`, `ai/trade_review/`, `ai/strategy_analytics/`, or `ai/digest/` at all — its findings on `ai/prompts.py` were independently re-verified directly against the real current branch (confirmed identical, findings stand); its claim that `contains_predictive_probability_claim()` doesn't exist is **false on the current branch** (it exists, added in Stage 8/9, and is covered above). Its coverage gap on `ai/similarity/`, `ai/market_intelligence/`, `ai/trade_review/`, `ai/strategy_analytics/`, and `ai/digest/` was partially offset by: (a) this session having built and extensively unit-tested those five packages directly (966+ tests specifically targeting no-lookahead, alignment/outcome independence, and UNKNOWN-never-assumed properties), and (b) one direct spot-check of `ai/similarity/features.py`'s no-lookahead boundary (confirmed holding), plus VAL-005/VAL-004 above, both found through live testing rather than static review. A dedicated re-audit of `ai/market_intelligence/quality.py`'s stale-vs-current propagation and `ai/explanations/service.py` was not completed and is recommended as follow-up.
