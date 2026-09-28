"""FastAPI application factory — a thin presentation layer over the existing,
frozen Stage 1 engine. No trading logic lives here; see api/snapshot.py for
the one place multiple engine calls are assembled together."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from ai.assistant import init_table as init_ai_messages_table
from ai.knowledge.seed_documents import seed_if_empty as seed_knowledge_if_empty
from ai.knowledge.store import init_table as init_knowledge_tables
from ai.memory.store import init_table as init_memory_table
from journal.database import init_db
from risk.fundednext_journal import init_table as init_fundednext_context_table
from api.routes import ai, alerts, fundednext, journal, knowledge, market, memory, risk, settings, setup, strategy
from api import ws

DEFAULT_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]


@asynccontextmanager
async def _lifespan(app: FastAPI):
    init_db()
    init_fundednext_context_table()
    init_ai_messages_table()
    init_knowledge_tables()
    seed_knowledge_if_empty()
    init_memory_table()
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
    app.include_router(fundednext.router)
    app.include_router(ai.router)
    app.include_router(strategy.router)
    app.include_router(knowledge.router)
    app.include_router(memory.router)
    app.include_router(ws.router)

    return app


app = create_app()
