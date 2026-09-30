# XAU Sentinel — Stage 24 Operational Issue Log

Found during real-world operational validation (see `OPERATIONAL_TEST.md`) against a live MT5 connection, real
Telegram delivery, and Docker Compose. Severity scale matches `ISSUE_LOG.md`: **P0** critical, **P1** high, **P2**
medium, **P3** low. Classification is one of **bug**, **limitation**, **configuration**, or **insufficient
validation**, per the stage's own instructions. **Nothing here was fixed during this stage** — per the spec,
issues are documented, not patched.

---

### OP-001 — In `MODE=live`, the monitoring loop fails every cycle with "MT5 not connected" until an unrelated HTTP request happens to trigger the lazy MT5 connect

- **Severity:** P1
- **Classification:** bug
- **Status: Resolved.** `ai/monitoring/engine.py::_build_bundle()` now carries the same `if config.IS_LIVE and not connection.is_connected(): connection.connect()` idiom as `app.py`/`api/snapshot.py`, checked every cycle (not just once at startup), so a genuine mid-session disconnect self-heals too. New tests `test_live_mode_connects_mt5_before_fetching_candles_when_not_already_connected`/`test_live_mode_does_not_reconnect_mt5_when_already_connected` in `tests/test_monitoring_engine.py`. Live-reconfirmed: a fresh `MODE=live` start with **zero** HTTP requests sent to the server still produced a `monitoring_baseline` row within one cycle interval, proving the loop connects entirely on its own.
- **Reproduction:** Start the host app fresh with `MODE=live` and no prior MT5 connection (`uvicorn api.main:app ...`). Do **not** load any page or call any endpoint that builds a market snapshot. Watch the log: `ai/monitoring/engine.py::run_forever()` calls `run_monitoring_cycle()` → `_build_bundle()` → `market_data.get_all_candles()` every `MONITORING_INTERVAL_SECONDS` (20s), and every single cycle raises `mt5.market_data.MarketDataError: MT5 not connected`, caught and logged as `Monitoring cycle failed; retrying in 20s` (`engine.py:198`). This repeated for 8+ consecutive cycles (~3 minutes) in tonight's run before any request happened to touch a connecting endpoint. The instant `GET /api/market/analysis` was called (which goes through `api/snapshot.py::build_snapshot()`, carrying the `if config.IS_LIVE and not connection.is_connected(): connection.connect()` idiom), the very next monitoring cycle succeeded and kept succeeding.
- **Expected:** In `MODE=live`, the monitoring loop — the app's core "watch the market and alert me" purpose — should be able to connect to MT5 on its own, independent of whether a browser tab happens to be open.
- **Actual:** `mt5/market_data.py::get_candles()` (`:76-78`) only checks `connection.is_connected()`, a Python-level flag that starts `False` and is only ever set by `connection.connect()`. Nothing in `api/main.py`'s FastAPI lifespan, nor `ai/monitoring/engine.py` itself, ever calls `connection.connect()`. The only two call sites that do (`app.py:27-28`, `api/snapshot.py:74-76`) are both request-driven (the legacy Streamlit UI and the Next.js `/api/market/*` routes), not startup-driven.
- **Evidence:** `docs/deployment` / this stage's own `OPERATIONAL_TEST.md` §3 row 5, 14; live log capture (`op_api.log`, this session) — 22 occurrences of `MT5 not connected` across the pre-connect window, zero after.
- **Likely cause:** MT5 connection was designed to be established lazily, as a side effect of building a UI-facing snapshot — reasonable when the only consumer was the dashboard itself, but the monitoring loop is a separate, independent background consumer with no such trigger of its own.
- **Note on resilience:** once connected, the loop **does** recover cleanly on its own (matches DEP-003's "never die on a bad cycle" requirement) — this is a startup/cold-start gap, not a crash or a permanent failure.

### OP-002 — FundedNext progress-to-target math silently assumes the connected MT5 account IS the configured challenge account, producing a nonsensical result when they don't match

- **Severity:** P2
- **Classification:** configuration
- **Status: Resolved.** `risk/fundednext.py::compute_status()` now checks `abs(snapshot.balance - initial_balance) > initial_balance * config.FUNDEDNEXT_BALANCE_MISMATCH_TOLERANCE_PCT` (new config value, default `0.5`) right after the existing `snapshot.available` check, before any loss/drawdown/progress math runs — following the same `data_available=False` / `safety_level=UNKNOWN` / explicit `reason` pattern already used twice in this function. New tests `test_mismatched_account_balance_returns_unknown_not_fabricated` (reproduces the exact real-world $50k/$100k ratio) and `test_in_tolerance_balance_change_from_real_trading_is_not_flagged_as_mismatched` in `tests/test_fundednext.py`. Live-reconfirmed: `GET /api/fundednext/status` against the still-connected mismatched account now returns `data_available: false`, `safety_level: "UNKNOWN"`, `progress_to_target_pct: null`, `reason: "Connected account balance (100,000.00) does not match the configured ACCOUNT_BALANCE (50,000.00) — check the connected MT5 account or ACCOUNT_BALANCE."` — no more silent 1250%.
- **Reproduction:** With `.env`'s `ACCOUNT_BALANCE=50000` (the user's configured FundedNext challenge size) and any MT5 terminal connected whose real account balance differs — tonight, the connected `MetaQuotes-Demo` account (login `112774667`) has a real balance of `$100,000`, an unrelated demo account, not the user's actual $50k FundedNext challenge. `GET /api/fundednext/status` then returns `progress_to_target_pct: 1250.0`.
- **Expected:** `progress_to_target_pct` should read as a sane percentage (0–100% under normal progress, negative if in loss) or the endpoint should signal that the connected account doesn't look like the configured one.
- **Actual:** `risk/fundednext.py:64-67`: `progress_to_target_pct = round((snapshot.equity - initial_balance) / profit_target * 100, 1)`, where `initial_balance = config.ACCOUNT_BALANCE` (`:16`, a static config value) and `snapshot.equity` is whatever the connected account's real equity happens to be. With `equity=100000`, `initial_balance=50000`, `profit_target=4000` (8% of 50000): `(100000-50000)/4000*100 = 1250%`. The formula itself is arithmetically correct; the inputs are two numbers from unrelated accounts.
- **Evidence:** `OPERATIONAL_TEST.md` §3 row 22; live `GET /api/fundednext/status` response, this session.
- **Likely cause:** `compute_status()` (`risk/fundednext.py:14`) has no way to verify "is the account I'm reading actually the FundedNext-sized account `config.ACCOUNT_BALANCE` describes" — it trusts the static config value unconditionally against whatever account happens to be connected. This is a real gap for exactly the situation tonight's testing hit: a demo/scratch MT5 terminal left open that isn't the user's actual funded account.
- **Suggested direction (not applied):** either cross-check `snapshot.balance` against `config.ACCOUNT_BALANCE` within some tolerance and surface a clear warning/`UNKNOWN` when they diverge sharply, or document explicitly that `ACCOUNT_BALANCE` must match whatever MT5 session is connected and this is an operator responsibility, not something the app verifies.

### OP-003 — A persisted `RISK_STATUS_CHANGED` alert from 2026-09-29 has an internally contradictory message (title says CRITICAL, body and payload both say safe) — historical dev-DB artifact, not reproducible against the current code

- **Severity:** P3
- **Classification:** insufficient validation (historical data, not a live defect)
- **Reproduction:** `GET /api/monitoring/alerts` on the persistent dev DB returns one row: `id: 7`, `type: RISK_STATUS_CHANGED`, `title: "FundedNext risk: SAFE → CRITICAL"`, `message: "FundedNext safety level moved from SAFE to CRITICAL. All FundedNext limits within safe range."`, `payload: {daily_loss_used_pct: 0.0, max_drawdown_used_pct: 0.0, reason: "All FundedNext limits within safe range."}`, `timestamp: 2026-09-29T05:46:45`.
- **Expected:** A `CRITICAL` classification should always be accompanied by a `reason`/`message` that actually explains why (a specific violation), not the generic "all limits safe" fallback string.
- **Actual:** The title and `current_status` say `CRITICAL`; the message body and payload's own `reason` field say everything was safe, and the payload's own loss percentages (`0.0%`/`0.0%`) independently confirm "safe."
- **Evidence:** raw DB row above, read directly via `GET /api/monitoring/alerts` tonight.
- **Root-cause check performed:** read the **current** `risk/fundednext.py::compute_status()` (`:82-134`) in full. `safety_level` is only ever escalated to `CRITICAL` inside an `elif` branch that also appends a `Violation` with a specific, non-generic message (`:89-94`, `:108-113`). `reason = violations[0].message if violations else "All FundedNext limits within safe range."` (`:132`) — the generic fallback is structurally reachable **only** when `violations` is empty, which can only happen when `safety_level` stayed `SAFE`. **Given the current code, `safety_level == CRITICAL` and `reason == "All FundedNext limits within safe range."` cannot occur together.** This means the alert is very likely a fossil from **before** Stage 19's VAL-002 fix (which reworked exactly this daily-loss-anchor logic) — generated by an earlier, buggy version of `compute_status()`, sitting harmlessly `acknowledged: true` in the dev DB ever since.
- **Positive finding alongside this:** this row IS valid evidence that alert persistence itself works correctly — it survived many hours and at least the several restarts performed elsewhere in this same session.
- **Suggested direction (not applied):** if a clean baseline for future operational testing matters, this dev DB carries pre-Stage-19 test residue that a fresh reset would clear; not urgent, since it's inert and correctly acknowledged.

### OP-004 — No explicit "monitoring loop started" (or periodic heartbeat) log line

- **Severity:** P3
- **Classification:** limitation
- **Status: Resolved.** `ai/monitoring/engine.py::run_forever()` now logs `"Monitoring loop started (cycle interval %ss)"` once at startup, and `"Monitoring loop alive: %d cycles completed"` every `HEARTBEAT_EVERY_N_CYCLES` (15, ~5 minutes at the default 20s interval) successful cycles — frequent enough to notice a hang, infrequent enough to stay within DEP-013's log-volume cap. New test `test_run_forever_logs_start_and_a_periodic_heartbeat` in `tests/test_monitoring_engine.py` drives the loop through a full heartbeat interval to prove the log line actually fires, not just that the code contains it.
- **Reproduction:** `docker compose logs api` (or the host uvicorn log) after a clean startup shows only generic uvicorn lines (`Started server process`, `Application startup complete`, `Uvicorn running on ...`) — no line confirming the monitoring background task itself started or completed a cycle.
- **Expected:** Some operator-visible confirmation the monitoring loop is alive, beyond "no error was logged."
- **Actual:** The only way to confirm the loop ran tonight was reading the `monitoring_baseline` table directly — not something an operator watching logs alone could do.
- **Evidence:** `OPERATIONAL_TEST.md` §2 row 5; full log review, both tracks.
- **Note:** this exact gap was already flagged as unresolved during DEP-003's fix ("The start/heartbeat line and status endpoint the issue suggested were not added" — Lane E's own report, `DEPLOYMENT_ISSUES.md`'s DEP-003 resolution note). Re-confirmed live here, not a new finding — recorded for completeness since this stage is specifically about operational observability.

### OP-005 — Real LLM testing (spec §3)

- **Severity:** N/A
- **Classification:** insufficient validation (configuration) at the time this stage ran; **since closed**
- **Detail:** At the time this stage ran, `.env` had `AI_PROVIDER=mock`, no API key set — per the user's explicit decision, no key was requested and no real LLM call was made. **Follow-up (2026-09-30, same night):** the user provided a real Groq API key and added `AI_PROVIDER=groq` support (new `ai/providers/groq_provider.py`, see its own commit). Live-verified: `GET /api/ai/config` → `configured: true, provider: "groq", model: "openai/gpt-oss-120b"`; a real `POST /api/ai/chat` call returned a genuine model-generated answer, correctly grounded in the deterministic context (`**FACT:** ... DEVELOPING (BUY) ...`), with the safety-filter framing intact and no actionable-directive or probability-claim language. The originally-suggested Groq model name (`llama-3.3-70b-versatile`) had been retired from Groq's catalog — found via `GET https://api.groq.com/openai/v1/models` with the real key, corrected to `openai/gpt-oss-120b`. This stage's own A+ explanation / alert explanation / trade review AI paths were still only exercised against mock during the stage itself — not retroactively re-run against the real provider, since they weren't part of this specific follow-up check.

### OP-006 — Digest period-boundary live check (spec §6)

- **Severity:** N/A
- **Classification:** configuration
- **Status: Live-tested (2026-09-30, follow-up).** `DIGEST_ENABLED` stays `false` in `.env` (the background scheduler was **not** silently enabled), but `POST /api/digest/preview` and `POST /api/digest/send` deliberately bypass that flag as an explicit manual action, so both were exercised directly against the real journal DB and real Telegram: `preview` returned `period_start: 2026-09-21, period_end: 2026-09-28` for a WEEKLY digest requested on 2026-09-30 (a Wednesday) — correctly the last *completed* Mon-Sun week, not the current in-progress one, matching Stage 20's fix. `send` returned `{"sent": true, "already_sent": false}` on the first call (a real message delivered to the configured Telegram chat) and `{"sent": false, "already_sent": true}` on an immediate resend for the same period — dedup confirmed live, not just in tests.
- **Detail:** `completed_period_bounds()`'s correctness already has dedicated regression tests (Stage 20) and was live-verified against the real wall clock at the time (per `project_xau_sentinel_status.md`'s Stage 20 notes) — this follow-up re-confirms it against tonight's real date and real (empty) journal data.

### OP-007 — MT5 disconnect/reconnect (spec §2)

- **Severity:** N/A
- **Classification:** insufficient validation
- **Detail:** Still not tested against the live running app, on a follow-up attempt: there is no HTTP-triggerable disconnect route in this app (checked — `grep -rn "disconnect" api/routes/*.py` returns nothing, by design for a read-only monitoring tool), and forcing it any other way would mean either closing the user's real, currently-open MT5 terminal, or adding new debug-only scaffolding outside this task's scope — neither was done. `connection.connect()` (the reconnect half) IS now exercised, correctly, by every monitoring cycle via the OP-001 fix; `connection.disconnect()`/the initial-failure path were exercised correctly in a disposable one-off script earlier tonight (during the VAL-016/017 live check). A genuine mid-session drop-then-recover against the live app process remains unverified.

### OP-008 — VAL-016 commission/swap/fee summing (spec §7)

- **Severity:** N/A
- **Classification:** insufficient validation
- **Detail:** Unchanged from tonight's earlier check — the connected account has no real BUY/SELL deal, only its initial deposit. Marked `UNVALIDATED`, not forced.
