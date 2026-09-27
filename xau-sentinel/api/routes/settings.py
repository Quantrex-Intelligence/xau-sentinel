"""Read-only view of the effective config.py values. Deliberately excludes
MT5_LOGIN/MT5_PASSWORD/MT5_SERVER and DB_PATH — this is a display surface,
never a place to edit or expose secrets."""
from fastapi import APIRouter

import config

from api.schemas import SettingsOut

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings", response_model=SettingsOut)
def get_settings():
    return SettingsOut(
        mode="mock" if config.IS_MOCK else "live",
        trading_symbol=config.TRADING_SYMBOL,
        session_timezone=config.SESSION_TIMEZONE,
        account_balance=config.ACCOUNT_BALANCE,
        risk_per_trade_pct=config.RISK_PER_TRADE_PCT,
        data_stale_seconds=config.DATA_STALE_SECONDS,
        swing_lookback=config.SWING_LOOKBACK,
        displacement_atr_mult=config.DISPLACEMENT_ATR_MULT,
        liquidity_sweep_buffer_pips=config.LIQUIDITY_SWEEP_BUFFER_PIPS,
        equal_level_tolerance=config.EQUAL_LEVEL_TOLERANCE,
        atr_period=config.ATR_PERIOD,
        retracement_min_pct=config.RETRACEMENT_MIN_PCT,
        retracement_max_pct=config.RETRACEMENT_MAX_PCT,
    )
