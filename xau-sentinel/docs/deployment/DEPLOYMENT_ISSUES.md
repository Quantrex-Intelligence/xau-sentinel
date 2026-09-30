# Stage 23 — Deployment Issues

Issues found while testing XAU Sentinel as a local production-like stack (see
[DEPLOYMENT_TEST.md](DEPLOYMENT_TEST.md)). **None were fixed in this stage**, and no application code was
changed. Severity reflects the risk of taking the app **online**; locally, every service is bound to
127.0.0.1.

| ID | Severity | Summary |
|---|---|---|
| DEP-014 | **HIGH** | Unpinned dependencies: the Docker image resolves pandas 3, which makes `/api/similarity/current` return 500 |
| DEP-001 | **HIGH** (blocks online) | No authentication or authorization on any API route, the WebSocket, or the UI |
| DEP-015 | MEDIUM | 500 responses carry no CORS headers, so the browser reports every server error as a CORS failure |
| DEP-016 | LOW | One backend test reads the developer's real DB, so it fails on a clean checkout |
| DEP-002 | MEDIUM | No PostgreSQL, ORM or migration framework; schema changes never reach an existing DB |
| DEP-003 | MEDIUM | Background tasks are silent: no logs, and every exception is swallowed |
| DEP-004 | MEDIUM | Monitoring state lives only in memory; a restart drops any transition across the downtime |
| DEP-005 | LOW | Synchronous monitoring cycles run on the async event loop |
| DEP-006 | LOW | `/docs`, `/redoc`, `/openapi.json` are publicly served |
| DEP-007 | LOW | Frontend API URL is fixed at build time; the browser talks to the API cross-origin |
| DEP-008 | LOW | `localhost` → IPv6 `::1` first; ports published on IPv4 only |
| DEP-009 | LOW | Healthcheck start period is too short on a cold Docker Desktop boot |
| DEP-010 | LOW | Secrets are readable via `docker inspect` (env_file injection) |
| DEP-011 | LOW | Telegram status can't confirm a working channel until a real alert is delivered |
| DEP-012 | INFO | MT5 cannot run in the Linux containers; the containerized stack is mock-only |
| DEP-013 | LOW | Container logs are unbounded and dominated by healthcheck access lines |

---

### DEP-014 — Unpinned dependencies; the image gets pandas 3 and the similarity endpoint 500s (HIGH)
- **Reproduction:** `docker compose build && docker compose up -d --wait`, create any journal trade with no liquidity sweep (so `journal_context.liquidity` is NULL), then `curl http://127.0.0.1:8000/api/similarity/current` returns `500 Internal Server Error`. The same request against the host `.venv` returns 200.
- **Evidence:** the container has Python 3.12.14 with **pandas 3.0.6** / numpy 2.5.3; the host `.venv` has Python 3.10.10 with **pandas 2.3.3** / numpy 2.2.6. `requirements.txt` and `api/requirements.txt` use only `>=` bounds, and there is no lock file. Traceback: `ai/similarity/features.py:28 _infer_liquidity_kind → label.lower()` raises `AttributeError: 'float' object has no attribute 'lower'`. Under pandas 3 the NULL `liquidity` read by `pd.read_sql_query` arrives as float `NaN`, not `None`, so the `if not label` guard (NaN is truthy) doesn't catch it. This is the same NaN-vs-None family as VAL-005.
- **Impact:** the "Historical similarity" panel fails on the production image. Five E2E checklists fail their console/network checks (contextual analysis, market intelligence, migration, monitoring, strategy A+), and the historical-similarity checklist crashes. The same 14 checklists pass 14/14 (217 checks) against host dev servers.
- **Likely root cause:** unpinned dependencies, so every fresh build can pick up a new major version; plus a NaN-unsafe `None` check in `ai/similarity/features.py`. Pin exact versions (a lock file or `pip freeze` constraints matching the tested `.venv`) and make `_infer_liquidity_kind` NaN-safe (`pd.isna`).

### DEP-015 — 500 responses carry no CORS headers (MEDIUM)
- **Reproduction:** with DEP-014 present, open any dashboard page in the production stack. The browser console shows `Access to fetch at 'http://localhost:8000/api/similarity/current' … blocked by CORS policy`, and the request fails with `net::ERR_FAILED`.
- **Evidence:** the API log shows `GET /api/similarity/current … 500` with a traceback. Unhandled exceptions are answered by Starlette's outermost `ServerErrorMiddleware`, outside `CORSMiddleware`, so the 500 has no `Access-Control-Allow-Origin` header. The frontend therefore cannot read the status and sees a CORS error instead of "server error".
- **Likely root cause:** Starlette's middleware ordering, with no app-level exception handler. Any future server error will look like a CORS misconfiguration in the browser and be misdiagnosed. Add a catch-all exception handler that returns a JSON 500 inside the CORS layer, and log it (see DEP-003).

### DEP-016 — `test_build_digest_dates_are_the_expected_completed_period` depends on the developer DB (LOW)
- **Reproduction:** run `pytest` from a clean `git archive HEAD` export that has no `data/xau_sentinel.db`. Result: **1118 passed, 1 failed** with `sqlite3.OperationalError: no such table: trades`. In the main checkout, where the developer DB exists, all 1119 pass.
- **Evidence:** `tests/test_digest_service.py:196` calls `service.build_digest()` without the `temp_db` fixture, so it reads (and could be affected by) the real `data/xau_sentinel.db`.
- **Likely root cause:** a missing fixture (introduced in Stage 20). A CI run or fresh clone would fail, and in the main checkout the test's outcome depends on whatever is in the developer's DB. Add `temp_db`.

### DEP-001 — No authentication or authorization anywhere (HIGH, blocks online)
- **Reproduction:** `curl -X PUT http://127.0.0.1:8000/api/fundednext/settings -H 'Content-Type: application/json' -d '{"account_type":"stellar_lite"}'` succeeds with no credentials. The same holds for `POST /api/journal/trades`, `POST /api/ai/memory`, `POST /api/notifications/telegram/test`, `POST /api/ai/chat` (which spends AI credits when a real provider is set), and `ws://…/ws/market`.
- **Evidence:** `api/main.py::create_app()` registers 20 routers with no dependency, middleware or API key check; the frontend has no login. All test writes in DEPLOYMENT_TEST.md row 15 succeeded unauthenticated.
- **Likely root cause:** the app was designed as a single-user local tool. Binding to 127.0.0.1 is the only protection, and it disappears once the stack is reachable from a network.
- **Before going online:** put the whole stack behind authentication (at minimum a reverse proxy with auth, or an app-level token), and keep the API off the public internet if possible.

### DEP-002 — No PostgreSQL, ORM or migrations (MEDIUM)
- **Reproduction:** `grep -ri "postgres\|sqlalchemy\|alembic" --include=*.py` returns nothing. `journal/database.py` uses `sqlite3.connect(config.DB_PATH)`.
- **Evidence:** raw SQLite SQL (`datetime('now')`, `AUTOINCREMENT`, `?` params) across about 10 modules: `journal/database.py`, `journal/trades.py`, `ai/{assistant,knowledge,memory,monitoring,notifications,explanations,trade_review,digest}/store.py`, `risk/fundednext_journal.py`. The schema comes from `CREATE TABLE IF NOT EXISTS` in `api/main.py::_lifespan`.
- **Likely root cause:** SQLite was a deliberate local-first choice from Stage 1. `CREATE TABLE IF NOT EXISTS` never alters an existing table, so any future column change silently fails to reach an existing database (already hit during development, per the project's schema-drift note). SQLite on a volume also limits the API to one replica with one writer.
- **Impact:** the Stage 23 brief's PostgreSQL and Alembic assumptions do not hold. Persistence was tested on SQLite instead (PASS). A PostgreSQL move means porting every store module and adding versioned migrations: its own stage.

### DEP-003 — Background tasks are silent: no logs, all exceptions swallowed (MEDIUM)
- **Reproduction:** start the stack and read `docker compose logs api`. It has no line for monitoring start, cycle completion, or failure. Force a failure (e.g. make `market_data.get_all_candles` raise) and the log stays the same.
- **Evidence:** `ai/monitoring/engine.py::run_forever()` wraps each cycle in `except Exception: pass`, and the module has no logger. The only way to prove the loop ran was sampling PID 1's CPU time (20 s bursts). The Telegram delivery and digest loops follow the same pattern.
- **Likely root cause:** the "one bad cycle must never kill the loop" rule was implemented without logging. A permanently broken monitoring engine, e.g. a live-mode MT5 disconnect raising every cycle, would look exactly like a quiet market.
- **Suggested direction:** `logger.exception(...)` in each loop's except clause, a start/heartbeat log line, and a small status endpoint (last cycle time, last error).

### DEP-004 — Monitoring baseline is in-memory; restarts drop transitions (MEDIUM)
- **Reproduction:** with state A, restart the api container while the market moves to state B. The first post-restart cycle baselines at B, so the A→B transition is never alerted.
- **Evidence:** `ai/monitoring/engine.py` keeps `_last_snapshot` in a module global (lines 15, 39, 111–122); the first cycle after startup always returns no alerts. The test performed four restarts, and monitoring alerts stayed at 0 throughout.
- **Likely root cause:** by design for a local process. It matters once restarts are routine (deploys, `restart: unless-stopped` recovery, host reboots).
- **Suggested direction:** persist the last snapshot (one row) and compare against it on startup.

### DEP-005 — Synchronous monitoring cycle on the event loop (LOW)
- **Evidence:** `run_forever()` is `async`, but it calls the synchronous `run_monitoring_cycle()` directly. That runs `detect_setup`, the A+ evaluator, FundedNext status and market intelligence over 4×300 candles, measured at 0.15–0.44 s in-container. HTTP and WebSocket handling pauses for that time every 20 s. Health-latency sampling (953 calls) showed spikes up to 1.4 s, but the host was heavily loaded by other sessions, so attribution is not conclusive.
- **Likely root cause:** CPU-bound work is not offloaded (`asyncio.to_thread` or a separate worker). With real (network) market-intelligence providers, a slow HTTP call would block the whole API.

### DEP-006 — API docs publicly served (LOW)
- **Reproduction:** `GET /docs`, `/redoc` and `/openapi.json` all return 200.
- **Likely root cause:** FastAPI defaults. This publishes the full endpoint map, including write routes. Disable them (`docs_url=None`, etc.) or put them behind auth before going online.

### DEP-007 — Frontend API URL is build-time only; the browser calls the API cross-origin (LOW)
- **Evidence:** `frontend/lib/api.ts` and `lib/websocket.ts` read `NEXT_PUBLIC_API_BASE_URL` / `NEXT_PUBLIC_WS_URL`, which Next.js inlines at `next build`. The web image is hard-wired to `http://localhost:8000`.
- **Impact:** every hostname or environment needs its own image build. Online, the API must be publicly reachable at that URL, CORS must list the real origin, and the setup needs TLS (`https`/`wss`). A same-origin reverse proxy (`/api` → api service) would avoid all three.

### DEP-008 — `localhost` resolves to IPv6 first; ports are IPv4-only (LOW)
- **Reproduction:** from the Windows host, `httpx.get("http://localhost:8000/api/health")` fails with `ConnectError [WinError 10061]`, while `http://127.0.0.1:8000` works.
- **Evidence:** compose publishes `127.0.0.1:8000` / `127.0.0.1:3000` only, and this host resolves `localhost` to `::1` first. Browsers fall back to IPv4 (the Chromium pass succeeded); simple clients and scripts do not.
- **Likely root cause:** the localhost-only IPv4 binding (a security choice) combined with the `localhost` URLs in the frontend/E2E config. Use `127.0.0.1` in client URLs, or also publish on `[::1]`.

### DEP-009 — Healthcheck start period is too short on a cold Docker Desktop boot (LOW)
- **Evidence:** reported by session `propfirm-dashboard-50`. On the first `up` right after Docker Desktop launched, api-1 failed three healthchecks and web never started ("dependency api failed to start"). Warm restarts serve in about 15–18 s and turn healthy at 26 s, uncomfortably close to `start-period=20s`.
- **Likely root cause:** a slow cold import of pandas and friends plus lifespan table init and knowledge seeding, measured against a 20 s start period. Raise it to about 60 s.

### DEP-010 — Secrets readable via `docker inspect` (LOW)
- **Evidence:** `docker inspect xau-sentinel-api-1` includes `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` values (1 match for the real token). They are absent from image layers, logs and git.
- **Likely root cause:** inherent to `env_file` injection; anyone with Docker access on the host can read them. For online hosting, use Docker/Compose secrets (file-mounted) or the platform's secret store.

### DEP-011 — Telegram status can't confirm a working channel (LOW)
- **Evidence:** after a successful `POST /api/notifications/telegram/test` (`success:true`), `/telegram/status` still reports `last_success_at: null`. `ai/notifications/store.py::last_success_at()` only reads `alert_deliveries`, and the test route records nothing.
- **Impact:** the UI cannot show that Telegram works until a real monitoring alert is delivered. The alert → Telegram delivery path was not exercised end-to-end in this test, because no monitoring transition occurred (see DEP-004 for why restarts make this rarer).

### DEP-012 — MT5 cannot run inside the containers (INFO)
- **Evidence:** `MetaTrader5` is Windows-only (skipped by its `sys_platform == "win32"` marker), and compose forces `MODE=mock`. Read-only MT5 works from the Windows host (DEPLOYMENT_TEST.md section 3).
- **Impact:** a live deployment needs the API process on a Windows host next to the terminal, or a separate bridge; the Linux stack stays mock-only. Also: the verified terminal session was **MetaQuotes-Demo**, not a FundedNext server. The `Europe/Nicosia` conversion was correct there (UTC+3), but it should be re-verified against the real FundedNext server before going live.

### DEP-013 — Container logs are unbounded (LOW)
- **Evidence:** the daemon's logging driver is `json-file` with an empty `Config` (no `max-size` / `max-file`). After about 20 minutes the api log held 1,592 `/api/health` access lines (the 15 s healthcheck plus probes).
- **Likely root cause:** no `logging:` options in compose and no access-log filtering. A long-running host eventually fills its disk. Add `logging: {driver: json-file, options: {max-size: "10m", max-file: "3"}}` and consider filtering health access logs.
