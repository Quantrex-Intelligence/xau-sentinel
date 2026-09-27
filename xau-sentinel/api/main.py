"""FastAPI application factory — a thin presentation layer over the existing,
frozen Stage 1 engine. No trading logic lives here; see api/snapshot.py for
the one place multiple engine calls are assembled together."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from journal.database import init_db
from api.routes import alerts, journal, market, risk, settings, setup
from api import ws

DEFAULT_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    yield


def create_app() -> FastAPI:
    app = FastAPI(title="XAU Sentinel API", version="1.0.0", lifespan=_lifespan)

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
    app.include_router(ws.router)

    return app


app = create_app()
