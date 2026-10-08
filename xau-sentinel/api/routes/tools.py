"""Read-only chart overlay for the offline LuxAlgo ICT reference (tools/luxalgo_audit).

Closed candles only: the forming bar is dropped before the reference runs. This route changes no
analysis, A+ rule or alert. It exists so the chart can show the ICT overlays when the toggle is on.
"""
from fastapi import APIRouter, HTTPException, Query

from mt5 import market_data
from tools.luxalgo_audit.overlay import build_overlay

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("/luxalgo-ict")
def get_luxalgo_ict(timeframe: str = Query("M5"), count: int = Query(300, ge=60, le=1000)):
    try:
        df = market_data.get_candles(timeframe, count)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except market_data.MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    closed = df[df["is_closed"].astype(bool)].reset_index(drop=True)
    return {"timeframe": timeframe, "bars": int(len(closed)), "note": "Reference reimplementation, not validated.",
            **build_overlay(closed)}
