"""Key level detection: previous/current day highs & lows, session highs & lows,
higher-timeframe swing points, and session VWAP."""
from typing import Optional

import numpy as np
import pandas as pd

import config
from analysis.structure import find_swing_points


def _session_mask(times: pd.Series, start_hour: int, end_hour: int) -> pd.Series:
    hours = times.dt.hour
    if start_hour <= end_hour:
        return (hours >= start_hour) & (hours < end_hour)
    return (hours >= start_hour) | (hours < end_hour)  # session wraps past midnight UTC


def compute_zones(m5: pd.DataFrame, h1: pd.DataFrame, h4: pd.DataFrame) -> dict:
    """Returns {zone_name: price}. Day/session levels come from M5 candles;
    higher-timeframe swing levels come from H1/H4 candles."""
    zones: dict = {}
    if m5 is None or m5.empty:
        return zones

    times = m5["time"]
    today = times.iloc[-1].date()
    is_today = times.dt.date == today
    is_yesterday = times.dt.date == (pd.Timestamp(today) - pd.Timedelta(days=1)).date()

    if is_yesterday.any():
        zones["Previous Day High"] = float(m5.loc[is_yesterday, "high"].max())
        zones["Previous Day Low"] = float(m5.loc[is_yesterday, "low"].min())

    if is_today.any():
        zones["Current Day High"] = float(m5.loc[is_today, "high"].max())
        zones["Current Day Low"] = float(m5.loc[is_today, "low"].min())

    asian_today = is_today & _session_mask(times, config.ASIAN_SESSION_START_UTC, config.ASIAN_SESSION_END_UTC)
    if asian_today.any():
        zones["Asian High"] = float(m5.loc[asian_today, "high"].max())
        zones["Asian Low"] = float(m5.loc[asian_today, "low"].min())

    london_today = is_today & _session_mask(times, config.LONDON_SESSION_START_UTC, config.LONDON_SESSION_END_UTC)
    if london_today.any():
        zones["London High"] = float(m5.loc[london_today, "high"].max())
        zones["London Low"] = float(m5.loc[london_today, "low"].min())

    if h1 is not None and not h1.empty:
        h1_highs = [p for p in find_swing_points(h1) if p.kind == "high"]
        h1_lows = [p for p in find_swing_points(h1) if p.kind == "low"]
        if h1_highs:
            zones["H1 Swing High"] = h1_highs[-1].price
        if h1_lows:
            zones["H1 Swing Low"] = h1_lows[-1].price

    if h4 is not None and not h4.empty:
        h4_highs = [p for p in find_swing_points(h4) if p.kind == "high"]
        h4_lows = [p for p in find_swing_points(h4) if p.kind == "low"]
        if h4_highs:
            zones["H4 Swing High"] = h4_highs[-1].price
        if h4_lows:
            zones["H4 Swing Low"] = h4_lows[-1].price

    vwap = compute_session_vwap(m5.loc[is_today])
    if vwap is not None:
        zones["VWAP"] = vwap

    return {k: round(v, 2) for k, v in zones.items() if v is not None and not np.isnan(v)}


def current_session(dt) -> str:
    """Labels which trading session a UTC datetime falls in, using the same
    configurable windows as the zone detection above."""
    hour = dt.hour
    if config.ASIAN_SESSION_START_UTC <= hour < config.ASIAN_SESSION_END_UTC:
        return "Asian"
    if config.LONDON_SESSION_START_UTC <= hour < config.LONDON_SESSION_END_UTC:
        return "London"
    if config.NY_SESSION_START_UTC <= hour < config.NY_SESSION_END_UTC:
        return "New York"
    return "Off-session"


def compute_session_vwap(df: pd.DataFrame) -> Optional[float]:
    if df is None or df.empty:
        return None
    typical = (df["high"] + df["low"] + df["close"]) / 3
    volume = df["volume"].replace(0, 1)
    total_volume = volume.sum()
    if total_volume == 0:
        return None
    return float((typical * volume).sum() / total_volume)
