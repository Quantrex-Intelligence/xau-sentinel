"""Read-only route for the Entry Model (manual decision support). No order, no action.

`evaluate()` resolves to the active Top-Down Multi-Timeframe Entry Model (analysis/entry_model/
hierarchy.py); this route is generic over its output shape and needed no change for the redesign."""
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException

from analysis.entry_model import evaluate
from mt5 import market_data

router = APIRouter(prefix="/api", tags=["entry-model"])

COUNTS = {"M1": 300, "M5": 300, "M15": 300, "H1": 300, "H4": 300, "D1": 60}


@router.get("/entry-model")
def get_entry_model():
    frames = {}
    try:
        for tf, count in COUNTS.items():
            frames[tf] = market_data.get_candles(tf, count)
    except market_data.MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    now = datetime.now(timezone.utc)
    return {"symbol": "XAUUSD", **evaluate(frames, now)}
