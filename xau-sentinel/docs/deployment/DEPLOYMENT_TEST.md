# Stage 23 — Local Production Deployment Test

**Date:** 2026-09-29/30 (UTC+7 local). **Code under test:** `a7e5956` (Stage 22 HEAD). The images were built from
that commit; line-ending-normalized file hashes inside the container match HEAD.
**Host:** Windows 11, Docker Desktop 29.7.2, Compose v5.5.1.
**Scope:** deployment and runtime behavior only. No application code was changed in this stage. Failures are
recorded in [DEPLOYMENT_ISSUES.md](DEPLOYMENT_ISSUES.md).

## 1. Deployment architecture

```text
Browser ──► web  (Next.js 16 production build, `next start`)   127.0.0.1:3000
   │
   └──────► api  (FastAPI + uvicorn, 1 worker, no --reload)       127.0.0.1:8000
              │   in-process background tasks: monitoring (20 s), Telegram delivery (5 s), digest (off)
              └── volume xau-data → /app/data   SQLite xau_sentinel.db + FundedNext JSON state

MT5 terminal (Windows host only) ◄── not reachable from containers; the api container runs MODE=mock
```

- **No PostgreSQL service.** The application's persistence layer is raw `sqlite3` with SQLite-only SQL across
  about 10 modules, and has no ORM or Alembic. The Stage 23 brief assumed PostgreSQL and Alembic; the user chose
  to test SQLite on a Docker volume and record the gap (DEP-002) rather than port it in a test stage.
- **The browser calls the API directly, cross-origin.** There is no reverse proxy, and the API URL is baked into
  the frontend bundle at build time (`NEXT_PUBLIC_*`).
- **Secrets** are loaded only via `env_file: .env` (gitignored) and never written into the compose file or the
  images.

| File | Purpose |
|---|---|
| `docker-compose.yml` | Two services, the named volume, and localhost-only ports; `restart: unless-stopped`; api healthcheck gates web startup |
| `Dockerfile.api` | `python:3.12-slim`; installs `requirements.txt` + `api/requirements.txt` (MetaTrader5 is skipped by its Windows marker); non-root uid 10001; `/api/health` healthcheck |
| `frontend/Dockerfile` | Three stages (deps → `next build` → `next start`) on `node:22-slim`; runs as the `node` user |
| `.dockerignore`, `frontend/.dockerignore` | Keep `.env*`, `data/`, `.venv`, `node_modules`, `.next`, tests and docs out of the build context |

Commands:

```bash
cd xau-sentinel
docker compose build
docker compose up -d --wait        # api must be healthy before web starts
docker compose down                # keeps the data volume
docker compose down -v             # also deletes the data volume (clean start)
```

## 2. Results

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Images build | PASS | `xau-sentinel-api` 962 MB and `xau-sentinel-web` 1.31 GB; rebuild fully cached |
| 2 | Clean DB initialization (fresh volume) | PASS | `down -v` then `up -d --wait`: both containers healthy after 43 s. Created 14 tables: ai_messages, alert_deliveries, alerts, digest_deliveries, explanations, fundednext_context, journal_context, knowledge_chunks, knowledge_documents, market_events, memory_records, monitoring_alerts, trade_reviews, trades. Knowledge base seeded (4 documents, 17 chunks); every other table empty |
| 3 | "Migrations from scratch" | PASS, with a caveat | There is no migration framework. Schema comes from `CREATE TABLE IF NOT EXISTS` at startup. It is idempotent on an existing volume (3 restarts plus a one-off container against the same DB), but it can never alter an existing table (DEP-002) |
| 4 | Backend startup | PASS | uvicorn runs as uid 10001, with no `--reload`; FastAPI debug is off. Serving about 15–18 s after process start |
| 5 | Frontend production build/start | PASS | `next start`, "Ready in 553ms"; no dev/HMR markers |
| 6 | API health/status | PASS | 200 from `/api/health`, `/api/settings`, `/api/ai/config`, `/api/fundednext/status`, `/api/market/ticker`, `/analysis`, `/setup/current`, `/strategy/aplus`, `/risk`, journal trades+analytics, `/strategy-analytics`, `/trade-review/summary`, `/market-intelligence`, monitoring alerts, knowledge documents, memory, similarity, events, alerts |
| 7 | All dashboard pages | PASS | `/`, `/market`, `/setups`, `/journal`, `/analytics`, `/assistant`, `/fundednext`, `/settings` all return 200 over HTTP and in real Chromium; screenshots of `/` and `/journal` show fully rendered data |
| 8 | Frontend → API communication | PASS | Chromium pass: 29 API calls, all 200; 0 console errors, 0 page errors, 0 failed requests; WebSocket `ws://localhost:8000/ws/market` connected and received 14 frames |
| 9 | CORS | PASS | Preflight from `http://localhost:3000` returns 200 with `access-control-allow-origin: http://localhost:3000`; preflight from `http://evil.example` returns 400 with no allow-origin header |
| 10 | Environment variables | PASS | Container has MODE=mock (forced by compose), AI_PROVIDER=mock, TELEGRAM_ENABLED=true, SESSION_TIMEZONE=UTC, CORS origins set; MONITORING_ENABLED/DIGEST_ENABLED fall back to config defaults (true/false) |
| 11 | AI provider configuration | PASS | Mock provider: chat returns 200 with a tool call (`get_market_structure`) and knowledge retrieval. One-off container with `AI_PROVIDER=anthropic` and no key: `/api/ai/config` reports `configured:false` with an actionable reason, and chat returns a clean 503. A real Anthropic call was not tested (no key in `.env`) |
| 12 | Monitoring background task | PASS, with findings | The loop logs nothing (DEP-003), so liveness was shown by sampling uvicorn PID 1 CPU time: bursts of 0.5–1.0 s at t≈7, 28 and 48 s, a 20 s period matching `MONITORING_INTERVAL_SECONDS`. A manual cycle inside the container takes 0.15–0.44 s. No alert fired during the test window: the mock state had no transition (FundedNext stayed SAFE across settings changes), and every restart re-baselines (DEP-004) |
| 13 | Telegram test delivery | PASS | `POST /api/notifications/telegram/test` from inside the container returned `{"success":true}`, so a real message reached the configured chat. The token appears in no response, log, image layer, or git history. `last_success_at` stays null because it tracks alert deliveries only (DEP-011). Alert → Telegram delivery was not exercised because no alert fired |
| 14 | PostgreSQL persistence | N/A | No PostgreSQL in the application (DEP-002). SQLite persistence was tested instead (row 15) |
| 15 | Persistence: create → restart → verify | PASS | Created via the API: an open SELL trade (with auto-captured market and FundedNext context), a closed WIN trade (+3R), a TRADE_LESSON memory, and changed FundedNext settings. All of it re-verified field by field after each of the scenarios below |
| 15a | `docker compose restart api` | PASS | API back at t+18 s, healthy at t+26 s; data identical |
| 15b | `docker compose down` + `up -d --wait` (volume kept) | PASS | Data identical |
| 15c | API process exit (SIGINT to PID 1) | PASS | `restart: unless-stopped` recovered it: restart count 0 → 1, healthy again in about 9 s, data identical |
| 15d | Web keeps working after api restarts | PASS | `/journal` 200; browser pass after restarts shows the persisted trades |
| 15e | Docker engine shutdown + restart | PASS | Docker Desktop was shut down mid-test by something outside this session. After relaunch and `up -d --wait`, the volume still held all 8 trades, 4 memories and the last-written FundedNext settings. The earlier snapshot comparison differs only in data this test changed on purpose later (settings switch, E2E trades) |
| 24 | Similarity endpoint on the production image | **FAIL** | `GET /api/similarity/current` returns 500 in the container (pandas 3 NaN), and the browser shows it as a CORS error. See DEP-014 / DEP-015 |
| 16 | Error handling | PASS | Unknown trade 404 `{"detail":"Trade not found"}`; invalid payload 422 with field-level detail; bad timeframe 400; unknown route 404. No stack traces in responses. Container logs have no tracebacks apart from one expected healthcheck probe during a restart |
| 17 | Logs | PASS, with findings | Access logs only; no secrets. Background tasks log nothing (DEP-003); no log rotation (DEP-013) |
| 18 | Secrets not committed | PASS | `git ls-files`: only `.env.example` and `frontend/.env.local.example`. Every commit on every branch has 0 matches for Telegram-token-shaped, `sk-ant-`, or `KEY=/TOKEN=/PASSWORD=` values, and 0 matches for the real token value |
| 19 | Secrets not exposed in API responses/logs | PASS | The real token and chat id were checked against every probe response body, container logs, image history/metadata, and the frontend bundle, with 0 matches. The one bundle hit is help text naming `AI_API_KEY`. `docker inspect` of the running container does show env values (DEP-010) |
| 20 | Production debug settings | PASS, with finding | No `--reload`, no FastAPI `debug=True`, Next.js production mode. `/docs`, `/redoc` and `/openapi.json` are publicly served (DEP-006) |
| 21 | Exposed ports | PASS | Only `127.0.0.1:3000` and `127.0.0.1:8000`; nothing on 0.0.0.0. Side effect: DEP-008 |
| 22 | `.env` handling | PASS | `.env` is excluded from both build contexts (only `.env.example` is in the image), injected at runtime via `env_file`, and never baked into the frontend |
| 23 | MT5 read-only connectivity (host) | PASS | See section 3 |

## 3. MT5 (read-only, on the Windows host, outside Docker)

This was a one-off script that went through the application's own `mt5.connection`, `mt5.market_data`,
`mt5.account` and `mt5.timeutil` with `MODE=live`. It called no order or trade function. The terminal was
already logged in; `.env` has no MT5 credentials, so `connect()` attached to the terminal's current session.

| Check | Result |
|---|---|
| Package / terminal | `MetaTrader5` 5.0.6180; terminal build 6198, `connected=True`, `trade_allowed=False` |
| Connection | `connect()` returned True, `is_connected()` True, `last_error` None |
| Account data | login `***667`, server **MetaQuotes-Demo** (a demo account, not FundedNext), currency USD; `get_account_snapshot()` OK |
| XAUUSD symbol | `symbol_ready()` True; `symbol_info`: visible, 2 digits |
| Candles | M5 and H1, 50 rows each; exactly the last row is `is_closed=False` (forming), 49 closed (Stage 21 behavior confirmed on live data) |
| Ticks | `get_price_info()`: bid 4147.16, ask 4147.44, spread 0.28, source `live`, `stale=False` |
| Timezone conversion | Raw tick epoch read naively as UTC = 20:23:52Z (−10 798 s in the future). Through `timeutil.to_utc()` = 17:23:52Z, 1.7 s old. The Stage 19 server-time → UTC conversion is correct for this server (UTC+3, matching the `Europe/Nicosia` default) |

The MT5 integration cannot run inside the Linux containers (DEP-012).

## 4. Test-process notes

- **Parallel sessions.** During the first attempt another Claude session ran `docker compose down -v` on the
  same compose project and recreated the stack. It was coordinated to stand down, and every result above comes
  from a second, uncontended run on a fresh volume. Session `propfirm-dashboard-50` contributed the cold-boot
  healthcheck (DEP-009) and `docker inspect` (DEP-010) findings.
- **Shared working tree.** Other sessions edit files in this checkout concurrently. The images were confirmed to
  contain HEAD content. The final regression suite (section 5) ran from a clean `git archive HEAD` export so it
  measures committed code only.
- The probe scripts were one-off scratch files and are not committed.

## 5. Final regression (clean `git archive HEAD` export plus this stage's files)

All of these were run from a clean `git archive a7e5956` export, so they measure only committed code, not other
sessions' in-progress edits in the shared checkout.

| Suite | Result |
|---|---|
| Backend pytest (host `.venv`, pandas 2.3.3) | 1118 passed, 1 failed. The failure is DEP-016: the test needs the developer DB, which a clean export doesn't have. In the main checkout the baseline is 1119/1119 |
| Frontend vitest | 133 / 133 |
| Frontend lint | clean |
| Frontend typecheck (`tsc --noEmit`) | clean (after a normal `npm ci`; `next build` generates route types first) |
| Frontend production build | OK (host and inside the web image) |
| E2E, 14 checklists vs **host dev servers** | **14 / 14** (217 checks, 0 failures) |
| E2E, 14 checklists vs **production Docker stack** | 8 / 14 fully pass (196 checks). 5 checklists fail only their console/network checks, and the historical-similarity checklist crashes, all from DEP-014 (+ DEP-015) |
