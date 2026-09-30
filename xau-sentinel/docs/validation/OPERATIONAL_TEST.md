# Stage 24 — Real-World Operational Validation

**Date:** 2026-09-30
**Code under test / commit:** `e025d95` (branch `claude/magical-carson-b1gzd5`, pushed to origin), plus documentation-only commits made during this stage — no application code changed.
**Host:** Windows 11, this machine's own Docker Desktop and a real MT5 terminal (`MetaTrader5` package 5.0.6180, terminal build 6231) already running and connected.
**Scope:** observe the real system operating — Docker Compose lifecycle, a real MT5 connection, real Telegram delivery, and a short live-monitoring window — and write down what actually happens. No features added, no refactors, no auto-fixes (per the stage's own instructions). Real LLM testing (spec section 3) was not run: `.env` has `AI_PROVIDER=mock` with no API key configured, so there is no real LLM to test — marked `UNVALIDATED`, not attempted, per the user's explicit decision.

## 1. Two-track architecture

MT5 only works from this Windows host (the `MetaTrader5` package is Windows-only, and the Linux Docker image can't reach it — DEP-012). Docker Compose lifecycle testing only makes sense containerized. So this split into two tracks:

- **Track A — Docker Compose lifecycle**: the containerized stack, `MODE=mock` (a platform boundary, not a choice), real Telegram via the Docker-secrets wiring (DEP-010).
- **Track B — Host real-data session**: `uvicorn`/`npm run dev` directly on the host, `MODE=live` (real MT5), `AI_PROVIDER=mock` (unchanged), `NOTIFICATION_PROVIDER=telegram` (real, same `.env`).

```bash
# Track A
cd xau-sentinel
export TELEGRAM_BOT_TOKEN=$(grep '^TELEGRAM_BOT_TOKEN=' .env | cut -d= -f2-)
export TELEGRAM_CHAT_ID=$(grep '^TELEGRAM_CHAT_ID=' .env | cut -d= -f2-)
docker compose up -d --wait

# Track B (after Track A's `docker compose down`, to free ports 8000/3000)
MODE=live .venv/Scripts/python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000 --timeout-keep-alive 75
# separately: cd frontend && npm run dev
```

Compose secrets are type `environment` (`docker-compose.yml:60-64`) — they read from the **host shell environment** at `up` time, not from `.env` inside the container, hence the `export` lines.

## 2. Track A results — Docker Compose lifecycle

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Clean startup | PASS | `docker compose up -d --wait` at 08:07:07 UTC → both containers `Healthy` by 08:07:19 (~12s). |
| 2 | Database / schema init | PASS | `/api/health` → `{"status":"ok"}` immediately after startup; `monitoring_baseline` table auto-created by the first monitoring cycle (see #3), confirming `CREATE TABLE IF NOT EXISTS` ran cleanly on the fresh named volume. |
| 3 | Frontend → backend | PASS | `web` container `Healthy`; `curl http://127.0.0.1:3000` → 200. |
| 4 | Ports published both IPv4 and IPv6 | PASS | `docker compose ps`: `127.0.0.1:8000->8000/tcp, [::1]:8000->8000/tcp` (and `:3000`) — re-confirms DEP-008. |
| 5 | Monitoring startup | PASS, with a finding — see OP-001 | First cycle completed and persisted a baseline at 08:07:52, ~45s after container start (confirmed via direct DB read: `monitoring_baseline` row with a real snapshot, including the `aplus_candidate_key` field from Stage 23B). **No explicit "monitoring started" log line exists** — `docker compose logs api` shows only generic uvicorn startup lines; the loop's operation is only inferable from the database, not from logs alone. |
| 6 | Backend-only restart → monitoring recovery | PASS | Restarted `api` at 08:08:19 (27s after the baseline was saved, well inside the 10-minute `BASELINE_MAX_AGE` window — `ai/monitoring/engine.py:54`). API healthy again 9s later. First post-restart cycle reused the persisted baseline (`saved_at` moved to 08:09:06) and produced **zero** alerts — no false "state changed" alert fired purely from the restart. |
| 7 | Duplicate-alert prevention | PASS (indirect) | Across the initial cycle and all three restarts below, `/api/monitoring/alerts` stayed at 0 new alerts throughout Track A — no duplicate-creation was observed. A genuine transition-then-restart race (VAL-019's specific scenario) wasn't organically reproduced in this short window; that exact scenario already has its own regression coverage from Stage 23B, not re-derived here. |
| 8 | Full Compose restart | PASS | `docker compose restart` at 08:09:20 → both services `Up` and healthy again within seconds; `/api/health` and `http://127.0.0.1:3000` both 200 immediately after. |
| 9 | Full teardown/up cycle | PASS | `docker compose down` (removes containers + network, **not** the named volume) then `docker compose up -d --wait` → clean recreation, healthy in the same ~12s as the first startup. |
| 10 | Data persistence across teardown/up | PASS | `monitoring_baseline` row count still 1 after the full down/up cycle — the `xau-data` named volume (`docker-compose.yml:39,67`) correctly survives a teardown that doesn't pass `-v`. |
| 11 | Real Telegram delivery via Docker | PASS | `POST /api/notifications/telegram/test` → `{"success":true,"error":null}`; `last_test_success_at` moved from an earlier (07:12, from Lane G's own verification) to 08:08:01 — a genuine new message was sent and landed. |
| 12 | Secrets not exposed via `docker inspect` | PASS | `docker inspect xau-sentinel-api-1` shows `TELEGRAM_BOT_TOKEN=` and `TELEGRAM_CHAT_ID=` as **blank** in the environment block — re-confirms DEP-010 under a live check, not just Stage 23's one-off test. |
| 13 | No errors across the full Track A session | PASS | `docker compose logs` (both services, full session) contains zero `error`/`exception`/`traceback` lines. |

## 3. Track B results — host real-data session

| # | Check | Result | Evidence |
|---|---|---|---|
| 14 | MT5 connection | PASS | `mt5/connection.py::connect()` succeeded once triggered (see OP-001); `terminal_info()`/`account_info()` returned a genuine session: login `112774667`, server `MetaQuotes-Demo`, balance/equity `$100,000`, `trade_allowed: True`. |
| 15 | Symbol readiness | PASS | XAUUSD resolved (`symbol_ready: True`, `last_error(): None`). |
| 16 | Tick/candle data | PASS | `GET /api/market/analysis` → real price `4194.35`, bid `4194.35`/ask `4194.68`/spread `0.33`, `source: "live"`, real M5 candle (`4195.75/4195.86/4193.58/4194.35`, volume `1442.0`). |
| 17 | Timestamps / timezone | PASS | `server_timezone()` → `Europe/Nicosia`; session correctly reported as `London` at the time of the check (matches real UTC hour). Re-confirms VAL-003/VAL-017's earlier live checks tonight, now through the running app rather than a one-off script. |
| 18 | Closed-candle handling | PASS | `analysis.structure.closed_only()` on real `get_all_candles(5)` output: exactly 1 forming candle excluded per timeframe across all of M5/M15/H1/H4 (5 unfiltered → 4 closed, each). Confirms VAL-006 holds on genuine live data, not just mock. |
| 19 | Data freshness | PASS | `price.stale: false`; A+ evaluator ran without a stale-data flag under normal live conditions (Stage 23A's "Data Freshness" criterion wasn't exercised as *failing*, since the feed never actually went stale during this session — not a gap, just nothing to observe). |
| 20 | Disconnect / reconnect | **Not tested live** — see limitations | The connected terminal is the user's real, currently-open MT5 session. Deliberately not force-disconnected to avoid disrupting anything the user may have running in it. `connection.disconnect()`/reconnect logic was exercised earlier tonight in a disposable script (VAL-016/017 check) and confirmed correct there; not re-tested against the live app process in this stage. |
| 21 | A+ evaluator on real data | PASS | `GET /api/strategy/aplus`: real INVALID rating with a genuine, coherent invalidation reason ("H1 bias flipped to BULLISH, invalidating the SELL candidate before entry."), real context evidence strings, `llm_explanation` correctly labeled `[MOCK PROVIDER — offline, deterministic, no API key used]`. |
| 22 | FundedNext daily-loss / P&L on real data | PASS, with a finding — see OP-002 | `safety_level: SAFE`, `daily_loss_used_pct: 0.0`, `today_pnl: 0.0` (deposit correctly excluded, consistent with VAL-016). `progress_to_target_pct: 1250.0` — mathematically correct given its inputs, but the inputs are mismatched (see OP-002). |
| 23 | Journal date/time boundaries | Not independently re-derived | VAL-012's `session_now()` fix already has 18 regression tests (Stage 22) exercising the real code path against a `temp_db`. A live test trade was deliberately **not** created to avoid writing throwaway data into the persistent dev DB (this project's own past lesson on E2E test-data hygiene). Verified by code inspection only: `journal/trades.py`'s capture logic is unchanged since Stage 22. |
| 24 | Digest period boundaries | **Config gap, not tested** | `DIGEST_ENABLED=false` in `.env`. Per the plan, this was not silently flipped on for this stage — logged as a real configuration gap rather than forced. |
| 25 | Monitoring baseline persistence (real data) | PASS | Same `monitoring_baseline` mechanism as Track A, now confirmed against genuine live account/market data (see OP-001's recovery timeline). |
| 26 | ~10-minute monitoring smoke window | PASS | Armed 08:16:20–08:26:20 UTC. One event: a benign Windows `asyncio` Proactor teardown warning (`Exception in callback _ProactorBasePipeTransport._call_connection_lost`) — a well-known Windows-`asyncio` artifact from a connection being closed, unrelated to the monitoring loop itself (no `Monitoring cycle failed` lines followed it). No new monitoring-loop errors, no crash, no organic setup/risk/MI-quality transition observed in the window (expected for a 10-minute smoke check on real market data, not a failure — see limitations). |
| 27 | Alert persistence | PASS, surfaced a pre-existing finding — see OP-003 | `GET /api/monitoring/alerts` returned one alert dated `2026-09-29T05:46:45` (`RISK_STATUS_CHANGED`, `acknowledged: true`) — correctly persisted across many hours and multiple restarts since. Its **content** is internally inconsistent; see OP-003. Not something this stage's testing generated. |
| 28 | Real Telegram delivery of that historical alert | PASS (historical) | `last_success_at: 2026-09-29T05:57:13` matches the alert above — a genuine real-alert delivery happened at the time, distinct from tonight's repeated `last_test_success_at` test-sends. |
| 29 | Same-origin frontend → backend proxy (host) | PASS | `curl http://localhost:3000/api/health` → 200 via the Next.js rewrite (DEP-007), matching the Docker verification. |

## 4. VAL-016 — commission/swap/fee summing

**Status: `UNVALIDATED`** (unchanged from tonight's earlier check). The connected account (`MetaQuotes-Demo`, login `112774667`) still has exactly one real deal — its initial `$100,000` `DEAL_TYPE_BALANCE` deposit, correctly excluded from realized P/L (`get_daily_pnl_history(30) == []`). No real BUY/SELL deal exists to test `_realized_pnl`'s commission+swap+fee summing against. Per the spec: marked `UNVALIDATED`, not forced by placing a trade (this app never trades on the user's behalf).

## 5. Final regression (no push)

| Suite | Result |
|---|---|
| Backend (`pytest`) | **1249 passed**, 0 failed — matches baseline exactly. |
| Frontend tests (`npm run test`) | **133 passed**. |
| `tsc --noEmit` | Clean. |
| `npm run lint` | Clean. |
| `npm run build` | Succeeds, all 9 static routes. |
| E2E checklists (Track B, `MODE=live`, host servers) | 11 of 14 fully green; 3 have exactly one or two checklist assertions that hard-code a "mock mode" expectation, which correctly does not hold under a deliberate real-mode test session — see §6. No checklist failure was caused by an actual defect. |

## 6. E2E deviations under `MODE=live` (not regressions)

| Checklist | Result | Explanation |
|---|---|---|
| `test_fundednext_checklist.py` | 12/14 | Both failures assert mock-mode UI/API labeling (`"/status returns mock mode data"`, `"mock mode clearly labeled"`) — correctly false when actually running live. |
| `test_market_intelligence_checklist.py` | 11/13 | Both failures assert a fully-populated structure with a source on every section. Real inspection of `GET /api/market-intelligence` shows the correct, documented degradation: `macro` is honestly `data_available: false` with `reason: "MARKET_INTEL_FRED_API_KEY is not set — see .env.example."`; `cross_asset`/`gold_fundamentals` are genuinely populated from real Yahoo Finance data (DXY 101.194, VIX 16.03, equity index 7670.84, silver 61.26, all `freshness: LIVE`). This is Stage 12's intended per-field degradation working correctly, not a defect — the checklist simply has no "partial real config" variant. |
| `test_migration_checklist.py` | 20/21 (after one flaky full-page timeout on the very first cold run, unrelated — see §7) | The one consistent failure is the same "Mock mode indicator visible" pattern as `fundednext`. |

None of these represent an app defect. They reflect the checklists' built-in assumption of `MODE=mock`, which Track B deliberately didn't use.

## 7. Test-process notes

- `frontend/node_modules` was found empty (0 entries, directory present) at the start of Track B, for reasons unrelated to this stage's own actions — confirmed Docker doesn't bind-mount the host `frontend/` directory (`docker-compose.yml`'s `web` service has no `volumes:` entry), so this wasn't caused by the Docker testing in §2. Resolved with a plain `npm install --legacy-peer-deps` (687 packages, 2 minutes); not a product issue.
- The migration checklist's first run (against a cold Next.js dev server that had just started) hit a `Page.goto` `networkidle` timeout at 30s. The immediate rerun completed normally (20/21, the one remaining failure being the expected mock-mode assertion above) — the same benign cold-compile pattern already noted earlier tonight during the fresh-clone push verification, not new to this stage.
- Track A and Track B were run sequentially, never concurrently, to avoid a port clash on 8000/3000 (per this project's own "parallel sessions share Docker/ports" lesson) — `docker compose down` was run before starting the host servers.
- No other Claude session was active on this machine during this stage (`ListAgents` confirmed empty at the start).
