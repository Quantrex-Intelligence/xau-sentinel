"""FastAPI application factory — a thin presentation layer over the existing,
frozen Stage 1 engine. No trading logic lives here; see api/snapshot.py for
the one place multiple engine calls are assembled together."""
import asyncio
import hmac
import logging
import os
import sys
from contextlib import asynccontextmanager
from urllib.parse import parse_qs

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

import config
import log_safety
from ai.digest import service as digest_service
from ai.knowledge.seed_documents import seed_if_empty as seed_knowledge_if_empty
from ai.monitoring import engine as monitoring_engine
from ai.notifications import delivery as notification_delivery
from api.routes import (
    ai, alerts, analysis_v2, digest, explanations, fundednext, fundednext_mcp, journal, knowledge, market, market_intelligence,
    memory, monitoring, notifications, risk, settings, setup, similarity, strategy, strategy_analytics,
    trade_review,
)
from api import ws

# OP-004 (docs/validation/OPERATIONAL_ISSUES.md): nothing in this app's real
# startup path ever configured Python logging -- ai.monitoring.engine's own
# "Monitoring loop started"/heartbeat lines (and every other logger.info()
# call in the codebase) were silently swallowed in real usage, since a
# logger with no configured handler only surfaces WARNING and above via
# logging's last-resort handler. Only ERROR/EXCEPTION calls were ever
# actually visible, which is why that gap wasn't caught earlier -- OP-004's
# own unit test passed regardless, because pytest's caplog attaches its own
# handler directly and bypasses this entirely.
#
# A plain StreamHandler to stdout, not a file handler: this only ever runs
# inside a container, where the logging driver (docker-compose.yml's
# json-file, max-size/max-file capped per DEP-013) already owns stdout/
# stderr capture and rotation -- writing to a file here would duplicate
# that, not add anything.
#
# Must run BEFORE log_safety.install(): raising the root level to INFO here
# is exactly the scenario log_safety.py's own docstring warns about ("one
# logging.basicConfig(level=logging.INFO) added later would silently start
# writing the token to every log") -- install() runs right after and
# re-pins httpx/httpcore to WARNING regardless of this root-level change,
# closing that gap on the same line that opens it.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)
log_safety.install()  # VAL-036: keep the Telegram bot token out of httpx's request logs

logger = logging.getLogger(__name__)

DEFAULT_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]


class CatchAllErrorMiddleware:
    """DEP-015: turns any unhandled exception into a logged JSON 500.

    An `app.exception_handler(Exception)` would NOT fix this: Starlette wires
    Exception/500 handlers into ServerErrorMiddleware, the outermost layer,
    i.e. outside CORSMiddleware, so the 500 still left without
    Access-Control-Allow-Origin and the browser reported a CORS failure.
    This middleware is registered BEFORE CORSMiddleware (add_middleware
    prepends, so it ends up inside the CORS layer) and the CORS headers are
    added to its response. HTTPException never reaches it: FastAPI's
    ExceptionMiddleware, further inside, already answers those."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_wrapper(message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            logger.exception("Unhandled error on %s %s", scope.get("method"), scope.get("path"))
            if response_started:
                raise  # too late to send a clean 500; let the server close the connection
            response = JSONResponse({"detail": "Internal server error"}, status_code=500)
            await response(scope, receive, send)


class AuthMiddleware:
    """DEP-001: a single shared-secret token, checked on every HTTP request
    and the WebSocket when config.API_AUTH_TOKEN is set — a complete no-op
    when it's blank (the default: local dev, every existing test, and all
    14 E2E checklists keep working with zero header changes, the same
    graceful-degradation shape as AI_API_KEY/MARKET_INTEL_FRED_API_KEY).

    Exempt: GET /api/health and the docs routes already gated by
    API_DOCS_ENABLED, matching common REST convention — Docker's own
    healthcheck doesn't even use HTTP any more (DEP-009's TCP probe), so
    this is for operator convenience, not a hard requirement.

    A browser can't set a custom header on `new WebSocket(url)`, so the
    WebSocket takes the token as `?token=` instead of `Authorization`
    (frontend/lib/websocket.ts) — an accepted trade-off at this "local,
    single shared secret" scope, not full production hardening (see
    DEPLOYMENT_ISSUES.md's DEP-001 "before going online" note).

    Added between CatchAllErrorMiddleware and CORSMiddleware (DEP-015's
    same ordering reasoning): inside CORS, so a 401 still carries
    Access-Control-Allow-Origin instead of looking like a CORS failure to
    the browser.

    Token comparison uses hmac.compare_digest, not ==, so a wrong guess
    can't be distinguished by response timing (a plain string compare
    returns as soon as the first differing byte is found)."""

    _EXEMPT_PATHS = {"/api/health", "/docs", "/redoc", "/openapi.json"}

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            not config.API_AUTH_TOKEN
            or scope["type"] not in ("http", "websocket")
            or scope["path"] in self._EXEMPT_PATHS
        ):
            await self.app(scope, receive, send)
            return

        if scope["type"] == "http":
            headers = dict(scope.get("headers") or [])
            auth = headers.get(b"authorization", b"").decode("latin-1")
            token = auth[len("Bearer "):] if auth.startswith("Bearer ") else ""
            if hmac.compare_digest(token, config.API_AUTH_TOKEN):
                await self.app(scope, receive, send)
                return
            response = JSONResponse({"detail": "Unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return

        # WebSocket: reject before accept() so an unauthorized client never
        # reaches api/ws.py's connection loop at all.
        query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
        token = (query.get("token") or [""])[0]
        if hmac.compare_digest(token, config.API_AUTH_TOKEN):
            await self.app(scope, receive, send)
            return
        await receive()  # consume the "websocket.connect" handshake event
        await send({"type": "websocket.close", "code": 4401})


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # DEP-002: schema is created/altered exclusively via `alembic upgrade
    # head`, run before this process starts (see Dockerfile.api's CMD) --
    # every table this app touches is guaranteed to already exist by the
    # time _lifespan runs, so there is nothing left to init here.
    seed_knowledge_if_empty()

    task = None
    if config.MONITORING_ENABLED:
        task = asyncio.create_task(monitoring_engine.run_forever())
    delivery_task = None
    if config.TELEGRAM_ENABLED:
        delivery_task = asyncio.create_task(notification_delivery.run_forever())
    digest_task = None
    if config.DIGEST_ENABLED:
        digest_task = asyncio.create_task(digest_service.run_forever())
    yield
    if task is not None:
        task.cancel()
    if delivery_task is not None:
        delivery_task.cancel()
    if digest_task is not None:
        digest_task.cancel()


def create_app() -> FastAPI:
    docs_kwargs = {} if config.API_DOCS_ENABLED else {"docs_url": None, "redoc_url": None, "openapi_url": None}
    app = FastAPI(title="XAU Sentinel API", version="1.0.0", lifespan=_lifespan, **docs_kwargs)

    # Must be added before CORSMiddleware so it sits INSIDE it (DEP-015).
    app.add_middleware(CatchAllErrorMiddleware)
    # DEP-001: also added before CORSMiddleware, same reasoning — a 401
    # needs CORS headers too. No-op when API_AUTH_TOKEN is blank.
    app.add_middleware(AuthMiddleware)

    origins = os.getenv("XAU_API_CORS_ORIGINS")
    allow_origins = origins.split(",") if origins else DEFAULT_ORIGINS
    app.add_middleware(
        CORSMiddleware, allow_origins=allow_origins, allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    app.include_router(market.router)
    app.include_router(setup.router)
    app.include_router(risk.router)
    app.include_router(alerts.router)
    app.include_router(journal.router)
    app.include_router(settings.router)
    app.include_router(fundednext.router)
    app.include_router(fundednext_mcp.router)
    app.include_router(ai.router)
    app.include_router(strategy.router)
    app.include_router(knowledge.router)
    app.include_router(memory.router)
    app.include_router(similarity.router)
    app.include_router(market_intelligence.router)
    app.include_router(monitoring.router)
    app.include_router(notifications.router)
    app.include_router(explanations.router)
    app.include_router(trade_review.router)
    app.include_router(analysis_v2.router)
    app.include_router(strategy_analytics.router)
    app.include_router(digest.router)
    app.include_router(ws.router)

    return app


app = create_app()
