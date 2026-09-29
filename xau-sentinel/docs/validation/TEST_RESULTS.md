# XAU Sentinel — Validation & Testing Phase — Test Results

Environment: `MODE=mock`, `AI_PROVIDER=mock`, `NOTIFICATION_PROVIDER=telegram` (real bot configured).
Automated baseline: **1015/1015 backend tests, 133/133 frontend tests, 14/14 E2E checklists** — all passing,
unmodified, at commit `837f8b5` before this phase began. See `ISSUE_LOG.md` for every issue referenced below.

## Section-by-section results

| # | Section | Result | Notes |
|---|---|---|---|
| 3 | Market Data | **Issues found** | Candle retrieval, ticker, and analysis endpoints all function correctly in mock mode. VAL-003 (server-time-as-UTC), VAL-006 (forming candle treated as closed), VAL-011 (no staleness check before analysis) are real, unverified against real MT5 in this pass (mock mode only). |
| 4 | Deterministic Market Analysis | **Issues found** | Structure/liquidity/regime/setup-state machine logic reviewed in full. VAL-007 (partial Previous Day), VAL-008 (invalidation fires on precursor state, not sticky), VAL-013 (BOS off-by-one), VAL-014 (session-level lookahead), VAL-015 (Monday's "previous day"), VAL-018 (MSS recency), VAL-025/026 (duplicate events) all confirmed by code reading. No lookahead found in the swing-confirmation window logic itself (only via the forming-bar issue, VAL-006). |
| 5 | A+ Strategy Validation | **Issues found** | Deterministic rating **is reproducible** across repeated calls — verified live: two `/api/strategy/aplus` calls one second apart returned byte-identical `rating`/`direction`/`criteria`/`invalidation`/`fundednext` fields; only wall-clock-relative fields (timestamps, "minutes until event") differed, as expected. VAL-009 (MSS+displacement+retracement same-bar requirement), VAL-010 (R:R `abs()` + rounded-comparison gate) are real gaps against the documented sequential spec. LLM never alters `rating` — confirmed structurally (existing test suite) and by design (`attach_llm_explanation` only ever adds `llm_explanation`/`contextual_analysis.interpretation`). |
| 6 | FundedNext Risk Validation | **Issues found** | Live `/api/fundednext/status` returns a fully self-consistent SAFE snapshot with matching `reason` text. Safety-level classification thresholds/ordering (`SAFE/WARNING/CRITICAL/BREACHED`) read correctly (BREACHED checked first, correct comparison operators). VAL-002 (daily-loss anchor can silently understate loss) is the significant finding. VAL-016 (deposits counted as trading P&L), VAL-031 (phase-2 target never used) are secondary gaps. Server timezone handling uses timezone-aware `ZoneInfo`, correctly DST-safe. |
| 7 | Journal Validation | **Issues found** | Trade creation, immutable entry-time context, and FundedNext-snapshot-at-entry all confirmed by code reading — no UPDATE/DELETE path exists on `journal_context`/`fundednext_context` anywhere. VAL-012 (trade_date UTC vs trade_time local mismatch), VAL-024 (re-closing overwrites exit data), VAL-032 (unvalidated `result` value) are real gaps. |
| 8 | AI Assistant Validation | **Partially tested — mock-provider limited** | Ran a representative subset of the planned 20+ question set live against `/api/ai/chat`. FACT/CALCULATION/INTERPRETATION/UNKNOWN framing and evidence sourcing are correctly assembled (`context_used`/`sources`/`knowledge_used`/`tools_used` all populate correctly with FACT-tier labeling). A missing-data question ("trade #999999") did not trigger a tool call under the mock provider's keyword heuristic and fell back to a generic non-answer — **this is a mock-provider limitation** (the heuristic doesn't recognize every phrasing), not evidence about how a real model would behave; genuine tool-selection/evidence-quality assessment requires `AI_PROVIDER` pointed at a real model, which this environment doesn't have configured. VAL-001 (safety filter gaps) is the section's critical finding, confirmed by direct execution, independent of the mock-provider limitation. |
| 9 | RAG / Memory / Similarity | **Mostly confirmed, one structural weakness noted** | `ai/similarity/features.py`'s no-lookahead boundary re-confirmed directly (only mentions outcome fields in its own docstring, never reads them in code). RAG relevance filtering confirmed to reject off-topic queries by a real margin (not just rank). Archived-memory exclusion and "no automatic memory creation" were verified by this session's own Stage 7 test suite (unchanged since). VAL-037 (a crafted knowledge-note title could visually mimic a CONTEXT header) is a structural weakness, not a demonstrated exploit under the mock provider. |
| 10 | Market Intelligence | **Partially reviewed** | Not independently re-audited in this pass beyond what Stage 9-12's own extensive test suite (still passing) already covers; VAL-038 (freshness label reaching the LLM price line but not every other consumer of the same candles) is a real, confirmed gap. A full re-audit of `ai/market_intelligence/quality.py`'s stale-propagation is recommended follow-up (see `ISSUE_LOG.md`'s coverage note). |
| 11 | Monitoring / Alerts | **Issues found** | No LLM code path anywhere in `ai/monitoring/` reconfirmed (only Stage 4's evaluator module-level-imports `ai.providers` transitively; no call path). Acknowledge/acknowledge-all confirmed idempotent and correctly scoped. VAL-019 (dedup key includes timestamp for 4/6 alert types, defeating the store's own documented guarantee under a partial-cycle failure), VAL-022 (backlog flood on enabling Telegram), VAL-023 (some A+→A+ transitions produce no alert) are the real findings. One live alert in the dev DB (`RISK_STATUS_CHANGED`, `SAFE→CRITICAL`) showed a `reason` field inconsistent with its own `daily_loss_used_pct: 0.0`/`max_drawdown_used_pct: 0.0` payload — most likely explained by VAL-002/VAL-027 (mock account state and the day-tracker anchor both varying across the session's many server restarts), not a formatting bug in the alert itself (the alert correctly reuses `raw.fundednext_status.reason` verbatim). |
| 12 | Telegram | **PASS (mock) + PASS (one controlled real test)** | Every alert-type formatter, retry/backoff, and the retryable-vs-non-retryable distinction were re-confirmed via code reading; no token-leak path found in any currently-reachable code (VAL-036 is a latent, not active, risk). **One controlled real send was performed** via the existing `/api/notifications/telegram/test` endpoint (its fixed, pre-approved, non-trading message) — `{"success": true, "error": null}`, confirming real end-to-end delivery still works. No other real sends were made (digest/alert content was only ever exercised against the mock provider, per the test plan). VAL-020 (double-send on a `mark_sent` write failure) and VAL-021 (blocking I/O in the async loop) are the real findings. |
| 13 | AI Alert / Trade Explanation | **Structurally confirmed, not independently re-audited this pass** | Stage 15's own extensive test suite (structural "LLM never sets a deterministic field" tests, safety-filter tests) still passes unmodified; not re-read line-by-line in this pass given time budget — VAL-001's filter gaps apply here identically, since this path uses the same `contains_actionable_directive`/`contains_predictive_probability_claim` functions. |
| 14 | Trade Review | **Issues found** | Deterministic alignment rules read in full during Stage 16's own build and re-verified here; VAL-005 (NaN-vs-None) is the significant new finding — it can misclassify a trade with unrecorded `planned_rr` as **NOT_ALIGNED** rather than the honest **UNKNOWN**, a real violation of this project's own core design principle. Uses historical stored context only (verified: `ai/trade_review/context.py` never gathers Market Intelligence, by design, and `engine.py` takes an explicit `fundednext_snapshot` parameter rather than calling the live risk function). VAL-040 (outcome casing) is cosmetic. |
| 15 | Strategy Analytics | **Issues found** | Live-tested against the real accumulated dev DB (23 closed trades): overview/dimension-breakdown endpoints return correctly-shaped data, `INSUFFICIENT SAMPLE` labeling confirmed firing correctly at the configured threshold with the raw count still shown. VAL-005's NaN bug is the direct cause of `null` `avg_r`/`total_r` observed live for groups containing trades with unrecorded `r_multiple`. 0/1-4/5+ trade and missing-value scenarios are otherwise covered by the existing 21-test automated suite (unmodified, still passing). |
| 16 | Periodic Digest | **Issues found** | Weekly and monthly preview tested live against real data — correct structure, correct behavioral-pattern gating, correct Telegram-format rendering. VAL-004 (reports the just-started period, not the just-completed one) is a significant finding that affects both the scheduler and manual preview/send with no explicit reference date. Duplicate-prevention (`digest_deliveries` UNIQUE constraint) and the disabled-scheduler default (`DIGEST_ENABLED=false`) both confirmed correct by the existing automated suite; automatic scheduling was not force-enabled during this pass, per the test plan. |

## Section 17 — Real-World Shadow Testing

**Not performed as real-world observation** — this environment has no live MT5 connection (`MODE=mock`, no
`MT5_LOGIN`/`MT5_SERVER` configured) and no real LLM (`AI_PROVIDER=mock`). Recording "actual market outcome"
and "false positive/negative" columns against synthetic mock data would not be genuine evidence, and
fabricating it would directly violate this phase's own section 20 instruction. What this pass delivers
instead:

**Mechanism check (performed, mock data, explicitly not real evidence):** confirmed that a single coherent
snapshot — timestamp, Sentinel setup state, A+ result, FundedNext risk state, Market Intelligence summary,
and the monitoring alert log — can all be pulled from the existing `/api/market/analysis`,
`/api/strategy/aplus`, `/api/fundednext/status`, and `/api/monitoring/alerts` endpoints in one pass (each
exercised live during this session). The tooling needed for shadow logging already exists; no new
infrastructure is required to run it for real.

**Shadow-log template**, ready to use once a live MT5 connection is available:

```text
Timestamp | Sentinel State | A+ Result | Risk State | Market Intelligence | Alert Time | Actual Outcome | FP/FN | Notes
```

**Process to run it for real:** point `MODE=live` at a real (ideally demo/small) MT5 account, leave
`MONITORING_ENABLED=true`, and for each `APLUS_SETUP_DETECTED`/`INVALIDATED` alert the system raises, log a
row at detection time, then fill in "Actual Outcome"/"FP or FN" once the market has actually resolved —
never edit the detection-time columns after the fact. Recommended minimum: 2-3 weeks of live monitoring
across varied sessions before drawing any conclusion, given how easily a handful of trades overfits (see
section 20 of the original phase spec). This is a follow-up for the user to run with a live connection, not
something completable inside this single validation pass.

## Automated-suite re-confirmation

Re-run at the end of this phase (no code changed): **1015/1015 backend, 133/133 frontend, 14/14 E2E
checklists** — identical to the pre-phase baseline. This validation phase found issues the unit-level
automated suite structurally cannot catch (integration-level NaN propagation, live-server timezone
assumptions, cross-call scheduling logic, regex coverage against realistic — not just example — phrasing),
which is exactly the gap this phase exists to fill.
