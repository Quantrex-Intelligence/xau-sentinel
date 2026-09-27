from fastapi import APIRouter, HTTPException

from mt5 import market_data
from analysis.setup import detect_setup

from api.schemas import SetupOut
from api.snapshot import _setup_out

router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("/current", response_model=SetupOut)
def get_current_setup():
    try:
        candles = market_data.get_all_candles(300)
    except market_data.MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return _setup_out(detect_setup(candles))
