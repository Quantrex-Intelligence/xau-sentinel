"""Builds ONE aggregate snapshot from the existing engine — reused by every
REST route that needs more than a single call, and by the WS stream. This is
the only "assembly" logic in the API layer; every field is a direct,
traceable call into analysis/, journal/, or mt5/, never a re-derivation of
what they already compute.

Mirrors the wiring in app.py exactly (same functions, same order), just
returning data instead of rendering Streamlit widgets.
"""
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

import config
from mt5 import connection, market_data
from analysis.structure import analyze_structure, detect_displacement
from analysis.regime import classify_regime
from analysis.zones import compute_zones, current_session
from analysis.liquidity import detect_sweeps, detect_equal_levels
from analysis.setup import detect_setup
from journal import trades as trades_repo

from api.schemas import (
    CandleOut, ConnectionOut, LiquidityEventOut, LiquidityOut, MarketSnapshotOut,
    PriceInfoOut, RegimeOut, RiskOut, SetupOut, StructureOut, SwingPointOut,
)


def _epoch(ts) -> int:
    if isinstance(ts, pd.Timestamp):
        ts = ts.to_pydatetime()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return int(ts.timestamp())


def _candle_out(row) -> CandleOut:
    return CandleOut(
        time=_epoch(row["time"]), open=float(row["open"]), high=float(row["high"]),
        low=float(row["low"]), close=float(row["close"]), volume=float(row["volume"]),
    )


def candles_to_out(df: pd.DataFrame) -> list:
    return [_candle_out(row) for _, row in df.iterrows()]


def _structure_out(result) -> StructureOut:
    return StructureOut(
        state=result.state, last_bos=result.last_bos, last_mss=result.last_mss, reason=result.reason,
        swings=[SwingPointOut(time=_epoch(p.time), price=p.price, kind=p.kind, label=p.label)
                for p in result.swings if p.label is not None],
    )


def _liquidity_event_out(event) -> LiquidityEventOut:
    return LiquidityEventOut(
        time=_epoch(event.time) if event.time is not None else None,
        label=event.label, level_name=event.level_name,
        level_price=event.level_price, kind=event.kind,
    )


def _setup_out(result) -> SetupOut:
    return SetupOut(
        state=result.state, direction=result.direction, checklist=result.checklist,
        entry_zone=result.entry_zone, stop_loss=result.stop_loss,
        take_profit=result.take_profit, rr=result.rr, reason=result.reason,
    )


def build_snapshot() -> MarketSnapshotOut:
    if config.IS_LIVE and not connection.is_connected():
        connection.connect()
    conn_label, conn_ok = connection.status_label()
    connection_out = ConnectionOut(label=conn_label, connected=conn_ok,
                                    mode="mock" if config.IS_MOCK else "live")
    risk_out = RiskOut(balance=config.ACCOUNT_BALANCE, risk_per_trade_pct=config.RISK_PER_TRADE_PCT,
                        today_r=trades_repo.today_r_total())

    try:
        candles = market_data.get_all_candles(300)
        price_info = market_data.get_price_info()
    except market_data.MarketDataError as exc:
        return MarketSnapshotOut(
            connection=connection_out, price=None, structure={}, regime=None,
            zones={}, liquidity=LiquidityOut(sweeps=[], equal_levels=[]),
            setup=None, risk=risk_out, data_error=str(exc),
        )

    is_stale = market_data.is_stale(price_info)
    price_out = PriceInfoOut(
        price=price_info["price"], bid=price_info["bid"], ask=price_info["ask"],
        spread=price_info["spread"], time=_epoch(price_info["time"]),
        source=price_info["source"], stale=is_stale,
    )

    structures = {tf: analyze_structure(candles[tf]) for tf in market_data.TIMEFRAMES}
    regime = classify_regime(candles["H1"], candles["M15"])
    zones = compute_zones(candles["M5"], candles["H1"], candles["H4"])
    sweeps = detect_sweeps(candles["M5"], zones)
    equal_levels = detect_equal_levels(candles["M5"])
    displacement = detect_displacement(candles["M5"])
    setup_result = detect_setup(candles)

    now_utc = datetime.now(timezone.utc)
    latest_m5 = candles["M5"].iloc[-1] if not candles["M5"].empty else None

    return MarketSnapshotOut(
        connection=connection_out,
        price=price_out,
        structure={tf: _structure_out(structures[tf]) for tf in market_data.TIMEFRAMES},
        regime=RegimeOut(regime=regime.regime, reason=regime.reason),
        zones=zones,
        liquidity=LiquidityOut(
            sweeps=[_liquidity_event_out(s) for s in sweeps],
            equal_levels=[_liquidity_event_out(e) for e in equal_levels],
        ),
        displacement=displacement,
        setup=_setup_out(setup_result),
        risk=risk_out,
        session=current_session(now_utc),
        latest_m5_candle=_candle_out(latest_m5) if latest_m5 is not None else None,
    )
