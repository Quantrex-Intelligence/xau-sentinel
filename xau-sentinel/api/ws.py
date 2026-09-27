"""WS /ws/market — per-connection loop that reuses api.snapshot.build_snapshot(),
the exact same aggregate the REST /api/market/analysis route returns.

MT5 (and the mock generator standing in for it) is pull-only in this
codebase — there's no push-based tick event to subscribe to — so a
server-side polling loop pushed over WebSocket is the honest translation of
"real-time" here, not a shortcut around a "real" push architecture that
doesn't exist.
"""
import asyncio
import os

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.snapshot import build_snapshot

router = APIRouter()

WS_INTERVAL_SECONDS = float(os.getenv("XAU_API_WS_INTERVAL_SECONDS", "2.0"))


@router.websocket("/ws/market")
async def market_stream(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            snapshot = build_snapshot()
            await websocket.send_text(snapshot.model_dump_json())
            await asyncio.sleep(WS_INTERVAL_SECONDS)
    except WebSocketDisconnect:
        return
