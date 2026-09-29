# XAU Sentinel — Validation & Testing Phase — Issue Log

Severity: **P0** critical · **P1** high · **P2** medium · **P3** low. Status for every item below is
**Open** — no fixes were made during this phase (feature freeze; see `TEST_PLAN.md`). All line numbers refer
to the codebase at commit `837f8b5` (Stage 18).

---

## P0 — Critical

### VAL-001 — Both LLM safety-filter regexes miss almost every realistic unsafe phrasing
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
- **Subsystem:** `risk/day_tracker.py:20-28`, consumed by `risk/fundednext.py:28-34`.
- **Expected:** The daily-loss floor is anchored to the account balance at server midnight (per the module's own docstring).
- **Actual:** The anchor is whatever balance `compute_status()` first observes on a new server-calendar-day — if the app/monitoring loop wasn't running at exactly midnight (laptop asleep, app started late, MT5 disconnected), trades already closed earlier that day are silently absorbed into the anchor.
- **Reproduction (concrete scenario):** $50k account, 5% daily limit ($2,500). Trader loses $2,000 before opening the app for the first time that day. The anchor becomes the already-reduced balance; the app reports `daily_loss_used_pct ≈ 0`, SAFE, "$2,500 remaining" — when only $500 actually remains.
- **Potential fix:** Anchor as `current_balance − today's realized P&L so far` (from `get_daily_pnl_history`), or mark the anchor as unverified/flag a warning when it's first observed mid-day rather than at a clean day boundary.

### VAL-003 — MT5 candle/tick timestamps are labeled UTC but are actually broker server time
- **Subsystem:** `mt5/market_data.py:55,78`.
- **Expected:** Per `README.md`'s own claim ("All candle timestamps are handled in UTC internally") and the stale-check/sweep-window/session logic, which all assume UTC.
- **Actual:** MT5 bar/tick times are tagged `utc=True` without any broker-offset correction, but the project's own `FUNDEDNEXT_SERVER_TIMEZONE` default (`Europe/Nicosia`, UTC+2/+3) documents that the broker is *not* UTC. On a non-UTC server: the staleness check (`is_stale()`) can compute a negative age and never fire on a frozen feed; the sweep-window expiry (`is_within_sweep_window`) can likewise never expire a stale candidate; Asian/London session masks and day boundaries (Previous Day High/Low, VWAP session) shift by the server's UTC offset.
- **Potential fix:** Apply the broker's actual UTC offset (or query it from the terminal) before tagging candle/tick times as UTC, or explicitly document and test against the specific broker's offset if it's always fixed for this account.
- **Note:** Severity depends on the real broker's timezone, which can't be confirmed against `MODE=mock` — flagged for confirmation once a live MT5 connection is available.

---

## P1 — High

### VAL-004 — Periodic Digest reports the period that just started, not the one that just ended
- **Subsystem:** `ai/digest/service.py::run_digest_cycle()`/`attempt_send()` (Stage 18, this session's own build).
- **Expected:** Per the spec's own worked example ("Period: Sep 21-27" shown in a digest whose scheduling example implies it fires the following Monday), a scheduled or previewed digest should summarize the week/month that just **completed**.
- **Actual:** `run_digest_cycle()` calls `attempt_send(digest_type, reference=now.date())`, and `build_digest()`'s `compute_period_bounds()` returns the period **containing** `reference` — i.e. today. On the Monday the weekly digest is scheduled to fire, the "current period" it reports on is Monday-Sunday of the week that just began (almost no trades yet), while the week the user actually wants is only shown as the "previous period" comparison line. The same applies to `POST /api/digest/preview`/`/send` with no explicit reference — both always describe the in-progress period, never the last completed one.
- **Evidence:** `ai/digest/service.py` — `reference or _now().date()` feeding directly into `compute_period_bounds`, with no "step back one period" logic anywhere in the scheduled path.
- **Potential fix:** When firing from the scheduler (and as the default for `/preview` and `/send`), compute the period ending most recently before `reference` (i.e. what today's code computes as `previous_period_bounds` should become the primary period), or add an explicit `for_previous_period` flag distinguishing "summarize now" from "summarize what just ended."

### VAL-005 — `float` NaN silently defeats every `is None` check on numeric journal fields
- **Subsystem:** `ai/trade_review/patterns.py::closed_trades()` (Stage 16), consumed by `ai/trade_review/rules.py` (Stage 16), `ai/strategy_analytics/metrics.py` (Stage 17), `ai/digest/service.py` (Stage 18).
- **Expected:** A trade with no recorded `planned_rr`/`r_multiple`/`duration_minutes` is treated as missing data (`None`) throughout the deterministic pipeline, per this project's own repeated "UNKNOWN, never assumed" convention.
- **Actual:** `closed_trades()`'s `df.where(df.notnull(), None)` is a documented pandas no-op on `float64` columns — pandas re-coerces the replacement back to `NaN` rather than actually storing `None`, since a float64 array can't hold a Python `None`. **Verified by direct reproduction**: a DataFrame with a float column containing real `None`/`NaN` input, after `.where(df.notnull(), None)`, still reports `is None: False` for every row. Concretely, on the live dev DB, 4 of 8 trades in one dimension-breakdown group had `r_multiple = nan` (not `None`), which:
  - Made `ai/strategy_analytics/metrics.py::compute_dimension_breakdown()`'s `avg_r`/`total_r` compute to `NaN` (serialized as JSON `null`) instead of the intended `None`/`0.0`, even though the group had real wins/losses.
  - Would make `ai/trade_review/rules.py::classify_execution_alignment()`'s `if planned_rr is None: return UNKNOWN` **not fire** for a trade with unrecorded `planned_rr` — falling through to `planned_rr >= config.AI_STRATEGY_MIN_RR`, which for `NaN >= 3.0` is always `False` in Python, misclassifying the trade as **NOT_ALIGNED** instead of the honest **UNKNOWN**.
- **Reproduction:** `ai.trade_review.patterns.closed_trades()` on any DB containing a `CLOSED` trade with no `r_multiple`/`planned_rr`/`duration_minutes` recorded, then inspect `trade.get("r_multiple") is None` (`False`) vs `math.isnan(trade.get("r_multiple"))` (`True`).
- **Potential fix:** `df.astype(object).where(df.notnull(), None)` (cast to `object` dtype before `.where()`, which does allow `None`), or check `pd.isna(value)` instead of `value is None` at every consumer.

### VAL-006 — The live (forming) candle is read as if it were closed everywhere
- **Subsystem:** `mt5/market_data.py:50` (`copy_rates_from_pos(..., 0, count)` never drops position 0, the still-forming bar) → `analysis/structure.py` (MSS/BOS at `.iloc[-1]`, swing confirmation window can include the forming bar), `analysis/structure.py` displacement, `analysis/liquidity.py` sweeps, `analysis/setup.py` retracement/entry.
- **Actual:** An MSS, a displacement candle, a liquidity sweep resolution, and a retracement/entry can all be computed from a bar that hasn't closed yet, then silently change or vanish once it does. A VALID/A+ result can appear and disappear within a single bar.
- **Potential fix:** Drop the forming bar (fetch from position 1, or trim the last row when its close time is in the future) before any structural computation.

### VAL-007 — Previous Day High/Low is computed from an incomplete prior day
- **Subsystem:** `analysis/zones.py:29-33`, fed by `get_all_candles(300)` (300 M5 bars ≈ 25 hours).
- **Actual:** Early in the trading day, the M5 window only reaches a few hours into "yesterday," so Previous Day High/Low — a sweepable level and an R:R target source — is computed from a fraction of the actual prior session, worse the earlier in the day it's checked.
- **Potential fix:** Fetch enough M5 history to always cover the full prior calendar day (e.g. via a dedicated D1/H1 lookback), independent of the 300-bar window used for structure.

### VAL-008 — The "opposing M5 structure" invalidation check fires on the setup's own normal precursor state, and INVALIDATED isn't sticky
- **Subsystem:** `analysis/setup.py:115-120`, `ai/strategy/rules.py:62-67`.
- **Actual:** A bullish M5 MSS can only occur when M5 was previously in a BEARISH (LH+LL) structure — that's the expected state right after a low sweep, while a candidate is waiting for its MSS. The invalidation check reads `m5.state == "BEARISH"` at face value and can mark a fresh, otherwise-valid candidate INVALIDATED immediately instead of DEVELOPING. Separately, `detect_setup`/`evaluate_deterministic` keep no state between calls, so an INVALIDATED candidate can reappear as DEVELOPING/VALID on the very next evaluation with the same sweep.
- **Potential fix:** Check that the opposing structure break occurred *after* the MSS that validated the candidate, not just its current state; persist an explicit invalidated-candidate marker if INVALIDATED is meant to be sticky.

### VAL-009 — MSS, displacement, and retracement must all be true on the literal same latest bar
- **Subsystem:** `analysis/setup.py:128-163`, `analysis/structure.py:154` (`last = df.iloc[-1]`).
- **Actual:** The documented sequence is sweep → MSS → displacement → retracement (separate, sequential steps), but the code requires the current bar to simultaneously be the MSS-confirming close, a >1.5×ATR displacement body, and a 20-79%-retraced close — a materially narrower condition than documented. A retracement occurring on any bar after the displacement bar can never be recognized.
- **Potential fix:** Track the displacement bar once detected and evaluate retracement against subsequent bars relative to it, rather than requiring all three conditions on `iloc[-1]`.

### VAL-010 — R:R risk uses `abs(entry − stop_loss)` with no check that the stop is on the correct side of entry, and the A+ gate rounds before comparing
- **Subsystem:** `ai/strategy/rules.py:127` (risk calc), `:131,136` (`round(reward/risk, 2)` then `rr >= min_rr`).
- **Actual:** If price has traded back through the stop level before the evaluator runs, `abs()` still yields a positive "risk" and a plausible-looking R:R for a trade whose stop has effectively already been hit. Separately, `round(reward/risk, 2) >= min_rr` lets a true ratio like 2.996 round to 3.0 and pass a locked 1:3 minimum it doesn't actually meet.
- **Potential fix:** Use a signed risk (`entry − SL` for BUY, `SL − entry` for SELL) and reject `<= 0`; compare the unrounded ratio against `min_rr`, rounding only for display.

### VAL-011 — No staleness check before deterministic analysis runs
- **Subsystem:** `analysis/setup.py`/`ai/strategy/evaluator.py::evaluate_current_setup()` — neither calls `mt5.market_data.is_stale()`, which exists but is only wired into the UI header/snapshot display.
- **Actual:** A frozen/disconnected feed keeps producing a VALID/A+ result indefinitely (over a weekend, or during an MT5 outage) since nothing in the analysis path itself checks candle recency (and VAL-003's UTC mislabeling would defeat the check even if it were added naively).
- **Potential fix:** Thread an explicit staleness check into `evaluate_current_setup()`/`detect_setup()`, surfaced as part of the result rather than only in a separate UI badge.

### VAL-012 — Journal `trade_date` (UTC) and `trade_time` (local) are captured inconsistently, and can misdate a trade permanently
- **Subsystem:** `frontend/components/journal/new-trade-form.tsx` (`trade_date: now.toISOString().slice(0,10)` — UTC; `trade_time: now.toTimeString().slice(0,8)` — local).
- **Actual:** For a user outside UTC, a trade entered in the evening (behind UTC) or early morning (ahead of UTC) can be stored a full calendar day off from when it actually happened. Since entry-time journal fields are immutable by design, this is permanent, and it also skews which digest period (VAL-004) a trade falls into. The Streamlit UI (`ui/journal.py`) uses local date and local time for the same fields — the two entry paths disagree with each other and with "Today P/L" (which uses UTC date elsewhere).
- **Potential fix:** Use one consistent timezone (UTC, matching the rest of the system's internal-UTC convention) for both `trade_date` and `trade_time` capture in the Next.js form.

---

## P2 — Medium

| ID | Subsystem | Summary | Evidence | Suggested fix direction |
|---|---|---|---|---|
| VAL-013 | `analysis/structure.py:108-118` | BOS reported against an already-superseded prior swing (off-by-one) — can fire "bullish BOS" while price is retracing below the latest confirmed high. | `prior_high.price < last_high.price` always holds since `last_high` is the labeled HH, so `last_close > prior_high.price` is too easy to satisfy. | Compare against `last_high.price`, not `prior_high.price`. |
| VAL-014 | `analysis/zones.py:39-47`, `analysis/liquidity.py:43-55` | Session-level (Asian/London H/L) includes the bar under test and later bars — an in-session sweep of the session's own current extreme can never register, and an earlier genuine sweep can "disappear" once a later bar extends the extreme. | Levels recomputed from the full session including future bars relative to the sweep check. | Compute session levels only from bars strictly before the one being tested for a sweep. |
| VAL-015 | `analysis/zones.py:29` | On a Monday, "Previous Day" resolves to Sunday (near-empty/no bars), never Friday. | `today - 1 day` with no weekend skip. | Skip back to the last day with real session data. |
| VAL-016 | `mt5/account.py:83-106`, `risk/fundednext.py:52-61` | Daily P&L / trading-days-completed sums *every* deal type from `history_deals_get`, including deposits/balance adjustments — can misclassify a deposit as a "profitable trading day" and falsely trigger the FundedNext consistency-rule warning. | No filter on `d.type`/`d.entry`; commission/swap also excluded. | Filter to actual trade-close deals only; include commission/swap in realized P&L. |
| VAL-017 | `mt5/account.py` | Suspected double timezone application on deal timestamps (UTC tag then `Europe/Nicosia` conversion) — **inference only, not verified against a live terminal** since `MODE=mock` throughout this pass. | Flagged by code inspection, not reproduced live. | Confirm against a real MT5 connection before treating as confirmed. |
| VAL-018 | `analysis/structure.py:104-116` | `last_mss` means "close is currently beyond the last confirmed swing," not "a shift just happened" — no recency bound, can flicker on/off bar to bar (compounded by VAL-006). | Docstring/comment at `setup.py:91-95` calls it a "did a shift just happen" signal; code doesn't check recency. | Add an explicit recency window or a "shift bar index" the MSS is tied to. |
| VAL-019 | `ai/monitoring/rules.py` (4 of 6 dedup keys), `ai/monitoring/engine.py:115-122` | Dedup keys for SETUP_STATE_CHANGED/APLUS_SETUP_INVALIDATED/RISK_STATUS_CHANGED/MI_QUALITY_CHANGED embed the cycle timestamp; if a cycle partially fails after inserting alerts but before `_last_snapshot` updates, the next cycle can re-detect and re-send the same transition (duplicate Telegram message too). Contradicts the store's own "never insert two rows for the same transition" docstring for these 4 types. | `ai/monitoring/store.py:9-13`'s claim only actually holds for APLUS_SETUP_DETECTED/HIGH_IMPACT_EVENT_NEAR. | Update `_last_snapshot` before persisting, or make the timestamp component coarser/omit it from the dedup key. |
| VAL-020 | `ai/notifications/delivery.py:96-118` | A message that sends successfully but whose `mark_sent()` write then fails stays PENDING and resends next cycle; a provider exception type not explicitly handled (e.g. `httpx.InvalidURL`) can wedge the whole delivery cycle, bypassing `TELEGRAM_MAX_RETRIES` entirely for every queued item. | Code reads `except httpx.TimeoutException / httpx.HTTPError` specifically. | Broaden the caught exception type or wrap per-delivery; make `mark_sent` failure non-fatal to the loop. |
| VAL-021 | `ai/monitoring/engine.py`, `ai/notifications/delivery.py`, `ai/digest/service.py` | All three `asyncio.create_task`-scheduled background loops perform blocking I/O (MT5 reads, HTTP calls, SQLite) directly inside their coroutine with no `asyncio.to_thread` — freezes every other `async` handler (including the WebSocket) for the duration of a cycle. | `run_monitoring_cycle()`/`attempt_deliveries()`/`run_digest_cycle()` bodies. | Wrap the synchronous work in `asyncio.to_thread(...)`. |
| VAL-022 | `ai/notifications/delivery.py:49-58` | Turning Telegram on (or re-enabling after downtime) immediately queues up to 100 historical alerts for delivery, including long-stale A+ setups, none marked as historical. | `monitoring_store.list_alerts(limit=100)` with no time/acknowledged filter. | Filter to alerts created after the delivery worker's own start time, or exclude already-acknowledged ones. |
| VAL-023 | `ai/monitoring/rules.py:51,71` | Some A+→A+ transitions (opposite direction; a new sweep replacing the prior one without an intervening non-A+ state) produce no alert at all — the new entry/SL/TP is never announced. | Both rules only fire on a *cross into* A+, not a change while already A+. | Also fire when `aplus_direction` or the candidate identity changes while `aplus_rating` stays A+. |
| VAL-024 | `journal/trades.py::close_trade`, `api/routes/journal.py` | Re-submitting `PATCH .../close` on an already-closed trade silently overwrites `result`/`pnl`/`r_multiple` (no `WHERE status='OPEN'` guard) — any omitted optional field on the second call gets nulled out. | Route only checks the trade exists, not its current status. | Reject (409/400) a close attempt on a trade whose status isn't OPEN. |

---

## P3 — Low

- **VAL-025** `analysis/liquidity.py:69-80` — a run of 3+ equal highs/lows emits a duplicate event for the shared middle point (display-only impact, `[-3:]` slicing in evidence text).
- **VAL-026** `analysis/liquidity.py:39-55` — two named levels sharing a price (e.g. Asian Low == H1 Swing Low) produce two sweep events for one wick; `select_candidate`'s tie-break picks one arbitrarily, so the displayed `level_name` is arbitrary.
- **VAL-027** `mt5/market_data.py`, `mt5/account.py` — mock data uses Python's randomized `hash()` with no `PYTHONHASHSEED` pinned, so it is *not* actually deterministic across restarts despite the docstrings' claim (mock mode only).
- **VAL-028** `mt5/connection.py:62-68` — `connect()` returns success even when the configured symbol isn't available in the terminal; surfaces later only as a generic "no candle data" error.
- **VAL-029** `api/routes/journal.py` — trade insert and its FundedNext snapshot write are two separate DB connections/statements; a failure between them leaves a trade with no risk snapshot and a bare 500.
- **VAL-030** `risk/fundednext_journal.py` — `fundednext_context` has no `UNIQUE(trade_id)` constraint; "never updated after creation" is a convention, not structurally enforced.
- **VAL-031** `risk/fundednext.py`, `risk/models.py` — `Phase` only has CHALLENGE/FUNDED; a Stellar 2-Step phase-2 trader would see the phase-1 (8%) profit target rather than phase-2's, since no phase-2 case exists.
- **VAL-032** `api/schemas.py`, `journal/trades.py::compute_analytics` — `result` isn't validated against WIN/LOSS/BE at the API layer; an unexpected value (e.g. lowercase `"win"`) would count toward `total_trades` but not toward wins/losses/breakeven, silently deflating the win rate. Not reachable via the shipped UI's fixed WIN/LOSS/BE buttons.
- **VAL-033** All three background loops — bare `except Exception: pass` with no logging; a persistently failing loop has no operator-visible signal it died.
- **VAL-034** `ai/notifications/providers/telegram.py` — Telegram's `retry_after` on a 429 isn't honored; the fixed linear backoff can exhaust `TELEGRAM_MAX_RETRIES` before a real rate limit clears.
- **VAL-035** `ai/notifications/formatter.py:78-79` — cosmetic: an UNKNOWN risk status renders as `"Daily loss used: unavailable%"`.
- **VAL-036** Logging config — nothing currently sets `httpx`'s logger below INFO explicitly; if any future logging config raises the root/httpx logger to INFO, its own request-URL log line (which embeds the bot token) would start leaking it. No active leak found in any currently-reachable code path.
- **VAL-037** `ai/knowledge/retrieval.py` + `api/routes/knowledge.py` — a user-submitted knowledge note's title/content is rendered into the system prompt with the same `### Label ###` framing as the CONTEXT block, with no escaping; ground rule 6 instructs the model to treat it as inert, so this is a structural weakness rather than a demonstrated exploit under `AI_PROVIDER=mock`.
- **VAL-038** `ai/context.py` — the STALE freshness label reaches the LLM's price line only; structure/zones/sweep/setup sections built from the same candles, and the A+ evaluator's own output, carry no freshness marker at all.
- **VAL-039** `ai/knowledge/chunking.py` — splits on a fixed character window rather than paragraph boundaries (contradicting its own docstring); can split a sentence — and a negation — across two chunks.
- **VAL-040** `ai/strategy/evidence.py:184,257` — a closed trade's outcome renders as its stored uppercase result (`WIN`/`LOSS`/`BE`) but an open trade renders as the hardcoded lowercase literal `"open"` — a cosmetic casing inconsistency, present in both AI explanations and Trade Review's historical-similarity text (both reuse this function).

---

## Coverage note

Three parallel code-level review passes were run in isolated git worktrees; two (risk/journal/monitoring/Telegram, and the deterministic core) correctly read the current branch (`837f8b5`). The third (AI/RAG/memory/analytics layer) was given a worktree that had checked out a stale ref (Stage 5, `3d5b0ea`) and could not reach `ai/memory/`, `ai/similarity/`, `ai/market_intelligence/`, `ai/explanations/`, `ai/trade_review/`, `ai/strategy_analytics/`, or `ai/digest/` at all — its findings on `ai/prompts.py` were independently re-verified directly against the real current branch (confirmed identical, findings stand); its claim that `contains_predictive_probability_claim()` doesn't exist is **false on the current branch** (it exists, added in Stage 8/9, and is covered above). Its coverage gap on `ai/similarity/`, `ai/market_intelligence/`, `ai/trade_review/`, `ai/strategy_analytics/`, and `ai/digest/` was partially offset by: (a) this session having built and extensively unit-tested those five packages directly (966+ tests specifically targeting no-lookahead, alignment/outcome independence, and UNKNOWN-never-assumed properties), and (b) one direct spot-check of `ai/similarity/features.py`'s no-lookahead boundary (confirmed holding), plus VAL-005/VAL-004 above, both found through live testing rather than static review. A dedicated re-audit of `ai/market_intelligence/quality.py`'s stale-vs-current propagation and `ai/explanations/service.py` was not completed and is recommended as follow-up.
