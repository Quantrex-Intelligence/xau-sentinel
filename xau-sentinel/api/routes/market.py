"""Market data / analysis routes — every handler is a direct call into the
existing engine (mt5/, analysis/); see api/snapshot.py for the shared
aggregate used by /analysis and the WS stream."""
from fastapi import APIRouter, HTTPException, Query

from mt5 import market_data
from analysis.structure import analyze_structure
from analysis.zones import compute_zones
from analysis.liquidity import detect_sweeps, detect_equal_levels
from analysis.regime import classify_regime

from api.schemas import (
    CandleOut, LiquidityEventOut, LiquidityOut, MarketSnapshotOut, PriceInfoOut,
    RegimeOut, StructureOut,
)
from api.snapshot import build_snapshot, candles_to_out, _epoch, _liquidity_event_out, _structure_out

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/ticker", response_model=PriceInfoOut)
def get_ticker():
    try:
        price_info = market_data.get_price_info()
    except market_data.MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return PriceInfoOut(
        price=price_info["price"], bid=price_info["bid"], ask=price_info["ask"],
        spread=price_info["spread"], time=_epoch(price_info["time"]),
        source=price_info["source"], stale=market_data.is_stale(price_info),
    )


@router.get("/candles", response_model=list[CandleOut])
def get_candles(timeframe: str = Query("M5"), count: int = Query(300, ge=1, le=1000)):
    try:
        df = market_data.get_candles(timeframe, count)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except market_data.MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return candles_to_out(df)


@router.get("/structure", response_model=dict[str, StructureOut])
def get_structure():
    try:
        candles = market_data.get_all_candles(300)
    except market_data.MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {tf: _structure_out(analyze_structure(candles[tf])) for tf in market_data.TIMEFRAMES}


@router.get("/zones", response_model=dict[str, float])
def get_zones():
    try:
        candles = market_data.get_all_candles(300)
    except market_data.MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return compute_zones(candles["M5"], candles["H1"], candles["H4"])


@router.get("/liquidity", response_model=LiquidityOut)
def get_liquidity():
    try:
        candles = market_data.get_all_candles(300)
    except market_data.MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    zones = compute_zones(candles["M5"], candles["H1"], candles["H4"])
    return LiquidityOut(
        sweeps=[_liquidity_event_out(s) for s in detect_sweeps(candles["M5"], zones)],
        equal_levels=[_liquidity_event_out(e) for e in detect_equal_levels(candles["M5"])],
    )


@router.get("/regime", response_model=RegimeOut)
def get_regime():
    try:
        candles = market_data.get_all_candles(300)
    except market_data.MarketDataError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    result = classify_regime(candles["H1"], candles["M15"])
    return RegimeOut(regime=result.regime, reason=result.reason)


@router.get("/analysis", response_model=MarketSnapshotOut)
def get_analysis():
    return build_snapshot()
