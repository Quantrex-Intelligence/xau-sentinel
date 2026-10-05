"""Unified key-area engine (Analysis Engine V2, increment 2).

Collects objective price references from the existing analysis functions and
merges references that sit within an ATR-based tolerance into one key area.
Every area keeps its components and their provenance.

Inputs are CLOSED candles only. Current price is passed in explicitly.

Strength is evidence-based, never a score:
    HIGH      >= 3 distinct reference kinds across >= 2 timeframes
    MODERATE  >= 2 distinct reference kinds
    LOW       1 reference kind
Every area carries the reason it received its status.
"""
from dataclasses import replace
from datetime import datetime
from typing import Dict, List, Optional

import pandas as pd

from analysis.liquidity import detect_equal_levels
from analysis.structure import compute_atr, displacement_at, find_swing_points
from analysis.v2.models import Evidence, KeyArea, KeyComponent, Relationship
from analysis.v2.normalize import atr_normalized_distance
from analysis.zones import compute_zones

MERGE_TOL_ATR = 0.25  # references closer than this (in ATR) join the same area
NEAR_ATR = 1.0  # within this many ATR of an area edge price is "APPROACHING"
SWING_REFS_PER_SIDE = 2  # most recent confirmed swing highs and lows used per timeframe

# zone name -> (timeframe of the source bars, reference kind)
_ZONE_META = {
    "Previous Day High": ("D1", "PDH"),
    "Previous Day Low": ("D1", "PDL"),
    "Current Day High": ("M5", "CURRENT_DAY_HIGH"),
    "Current Day Low": ("M5", "CURRENT_DAY_LOW"),
    "Asian High": ("M5", "ASIAN_HIGH"),
    "Asian Low": ("M5", "ASIAN_LOW"),
    "London High": ("M5", "LONDON_HIGH"),
    "London Low": ("M5", "LONDON_LOW"),
    "H1 Swing High": ("H1", "H1_SWING_HIGH"),
    "H1 Swing Low": ("H1", "H1_SWING_LOW"),
    "H4 Swing High": ("H4", "H4_SWING_HIGH"),
    "H4 Swing Low": ("H4", "H4_SWING_LOW"),
    "VWAP": ("M5", "VWAP_UTC_DAY"),
}


def _components(m5: pd.DataFrame, h1: pd.DataFrame, h4: pd.DataFrame) -> List[KeyComponent]:
    zones = compute_zones(m5, h1, h4)
    now = pd.Timestamp(m5["time"].iloc[-1]).to_pydatetime()
    comps: List[KeyComponent] = []
    for name, price in zones.items():
        if name not in _ZONE_META:
            continue
        tf, kind = _ZONE_META[name]
        ev = Evidence(timeframe=tf, timestamp=now, kind=kind, value=float(price),
                      source="analysis.zones", note=name)
        comps.append(KeyComponent(label=name, price=float(price), evidence=ev))

    for tf_name, frame in (("H1", h1), ("H4", h4)):
        if frame is None or frame.empty:
            continue
        # Only the most recent swings per side: a reference from months back is
        # not part of the current market picture and would inflate strength.
        swings = find_swing_points(frame)
        recent = [p for p in swings if p.kind == "high"][-SWING_REFS_PER_SIDE:] + \
                 [p for p in swings if p.kind == "low"][-SWING_REFS_PER_SIDE:]
        for p in recent:
            ts = pd.Timestamp(p.time).to_pydatetime()
            kind = f"{tf_name}_SWING_{'HIGH' if p.kind == 'high' else 'LOW'}"
            ev = Evidence(timeframe=tf_name, timestamp=ts, kind=kind, value=p.price,
                          source="analysis.structure", note=f"confirmed {tf_name} swing {p.kind}")
            comps.append(KeyComponent(label=f"{tf_name} swing {p.kind}", price=p.price, evidence=ev))

    for e in detect_equal_levels(m5):
        ev = Evidence(timeframe="M5", timestamp=pd.Timestamp(e.time).to_pydatetime(),
                      kind=e.kind.upper(), value=e.level_price, source="analysis.liquidity",
                      note=e.label)
        comps.append(KeyComponent(label=e.label, price=e.level_price, evidence=ev))
    comps.extend(_extra_components(m5, h1, h4))
    return _consolidate(comps)


# Extra key-area sources (Analysis Engine V2, increment 4). Each one is a
# measurable structure in closed candles, never a free-standing guess.
CONSOLIDATION_BARS = 12  # H1 bars inspected for a consolidation
CONSOLIDATION_MAX_ATR = 2.0  # range over those bars, in H1 ATR, to count as consolidating
REJECTION_BARS = 60  # recent M5 bars scanned for rejection wicks
REJECTION_WICK_SHARE = 0.6  # wick must be at least this share of the bar's range
DISPLACEMENT_SCAN_BARS = 50  # recent H1 bars scanned for supply/demand origins
PSYCH_STEP = 10.0  # round-number grid; only used when justified by repeated touches
PSYCH_TOUCH_ATR = 0.25  # an H1 bar "touches" a round level within this many H1 ATR
PSYCH_MIN_TOUCHES = 2  # round level must be touched this often to be a reference
PSYCH_NEAR_ATR = 1.0  # and sit within this many M5 ATR of the current price


# Kinds that describe the SAME underlying swing. A structure swing, its zone
# twin, and the "broken" status of that swing are one level, not three references.
_LEVEL_FAMILY = {
    "H1_SWING_HIGH": "H1_SWING_HIGH", "H1_BROKEN_HIGH": "H1_SWING_HIGH",
    "H1_SWING_LOW": "H1_SWING_LOW", "H1_BROKEN_LOW": "H1_SWING_LOW",
    "H4_SWING_HIGH": "H4_SWING_HIGH", "H4_SWING_LOW": "H4_SWING_LOW",
}


def _consolidate(comps: List[KeyComponent]) -> List[KeyComponent]:
    """One logical component per (timeframe, level family, price). Only records of the
    same swing at the same price merge. Different prices, timeframes, or independent
    kinds (PDH, session extremes, VWAP, zones) are never merged. Every merged source
    is kept in `corroborations`, so provenance survives."""
    groups: Dict[tuple, List[KeyComponent]] = {}
    order: List[tuple] = []
    for idx, c in enumerate(comps):
        family = _LEVEL_FAMILY.get(c.evidence.kind)
        key = (c.evidence.timeframe, family, round(c.price, 2)) if family else ("single", idx)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(c)

    out: List[KeyComponent] = []
    for key in order:
        members = groups[key]
        # Prefer the plain reference over the "broken" status as the primary record.
        members = sorted(members, key=lambda m: ("BROKEN" in m.evidence.kind, ))
        primary = members[0]
        extra = tuple(m.evidence for m in members[1:]) + tuple(e for m in members for e in m.corroborations)
        out.append(replace(primary, corroborations=extra) if extra else primary)
    return out


def _extra_components(m5: pd.DataFrame, h1: pd.DataFrame, h4: pd.DataFrame) -> list:
    comps: list = []
    if m5 is None or m5.empty:
        return comps
    atr_m5 = compute_atr(m5)
    atr_m5_now = float(atr_m5.iloc[-1]) if len(atr_m5) else float("nan")
    atr_h1 = compute_atr(h1) if h1 is not None and len(h1) else None
    atr_h1_now = float(atr_h1.iloc[-1]) if atr_h1 is not None and len(atr_h1) else float("nan")
    price = float(m5["close"].iloc[-1])

    bar_time = pd.Timestamp(m5["time"].iloc[-1]).to_pydatetime()

    def add(label, value, tf, kind, note):
        ev = Evidence(timeframe=tf, timestamp=bar_time, kind=kind, value=float(value),
                      source="analysis.v2.key_areas", note=note)
        comps.append(KeyComponent(label=label, price=float(value), evidence=ev))

    # CONSOLIDATION: a tight H1 range, its edges become references.
    if h1 is not None and len(h1) > CONSOLIDATION_BARS + 14:
        # Baseline is the H1 ATR from BEFORE the window, so the window cannot
        # inflate its own yardstick and look tight.
        atr_before = float(compute_atr(h1).iloc[len(h1) - CONSOLIDATION_BARS - 1])
        block = h1.tail(CONSOLIDATION_BARS)
        hi, lo = float(block["high"].max()), float(block["low"].min())
        if atr_before > 0 and hi - lo <= CONSOLIDATION_MAX_ATR * atr_before:
            add("Consolidation high", hi, "H1", "CONSOLIDATION_HIGH", ("H1 range of the last 12 bars is tight"))
            add("Consolidation low", lo, "H1", "CONSOLIDATION_LOW", ("H1 range of the last 12 bars is tight"))

    # REJECTION areas: a long wick that closed back away marks where price was refused.
    if atr_m5_now > 0 and len(m5) > 2:
        block = m5.tail(REJECTION_BARS)
        upper, lower = [], []
        for _, bar in block.iterrows():
            rng = float(bar["high"] - bar["low"])
            if rng < 0.5 * atr_m5_now:
                continue
            body_top, body_bot = max(bar["open"], bar["close"]), min(bar["open"], bar["close"])
            if (bar["high"] - body_top) >= REJECTION_WICK_SHARE * rng:
                upper.append(float(bar["high"]))
            if (body_bot - bar["low"]) >= REJECTION_WICK_SHARE * rng:
                lower.append(float(bar["low"]))
        for v in upper[-2:]:
            add("Rejection high", v, "M5", "REJECTION_HIGH", ("long upper wick"))
        for v in lower[-2:]:
            add("Rejection low", v, "M5", "REJECTION_LOW", ("long lower wick"))

    # SUPPLY / DEMAND: the last opposite bar before an H1 displacement, edges as references.
    if h1 is not None and len(h1) > DISPLACEMENT_SCAN_BARS and atr_h1 is not None:
        start = len(h1) - DISPLACEMENT_SCAN_BARS
        demand, supply = None, None
        for i in range(start, len(h1)):
            side = displacement_at(h1, i, atr=atr_h1)
            if side is None:
                continue
            for j in range(i - 1, max(-1, i - 6), -1):
                opposite = (h1["close"].iloc[j] < h1["open"].iloc[j]) if side == "bullish" \
                    else (h1["close"].iloc[j] > h1["open"].iloc[j])
                if opposite:
                    zone = (float(h1["low"].iloc[j]), float(h1["high"].iloc[j]))
                    if side == "bullish":
                        demand = zone
                    else:
                        supply = zone
                    break
        if demand:
            add("Demand zone low", demand[0], "H1", "DEMAND_ZONE", ("H1 origin of an up-displacement"))
            add("Demand zone high", demand[1], "H1", "DEMAND_ZONE", ("H1 origin of an up-displacement"))
        if supply:
            add("Supply zone low", supply[0], "H1", "SUPPLY_ZONE", ("H1 origin of a down-displacement"))
            add("Supply zone high", supply[1], "H1", "SUPPLY_ZONE", ("H1 origin of a down-displacement"))

    # BREAK-AND-RETEST: an H1 swing that a later closed H1 bar has traded through
    # keeps a reference, and it now acts from the other side.
    if h1 is not None and len(h1) > 10:
        swings = find_swing_points(h1)
        highs = [p for p in swings if p.kind == "high"]
        lows = [p for p in swings if p.kind == "low"]
        if highs:
            h = highs[-1]
            if (h1["close"].iloc[h.index + 1:] > h.price).any():
                add("Broken H1 swing high", h.price, "H1", "H1_BROKEN_HIGH", ("H1 swing high closed through; now a possible support"))
        if lows:
            lo_p = lows[-1]
            if (h1["close"].iloc[lo_p.index + 1:] < lo_p.price).any():
                add("Broken H1 swing low", lo_p.price, "H1", "H1_BROKEN_LOW", ("H1 swing low closed through; now a possible resistance"))

    # WEEK-TO-DATE high and low, only when the H1 history starts at or before this
    # week's Monday 00:00 UTC. Otherwise the week is incomplete and is skipped.
    if h1 is not None and len(h1) and atr_h1_now > 0:
        now = pd.Timestamp(m5["time"].iloc[-1])
        monday = (now - pd.Timedelta(days=now.weekday())).normalize()
        # On Monday the week-to-date range IS today's range, so it adds no independent evidence.
        if now.weekday() != 0 and pd.Timestamp(h1["time"].iloc[0]) <= monday:
            week = h1[h1["time"] >= monday]
            if len(week):
                add("Week high", float(week["high"].max()), "H1", "WEEK_HIGH", ("week-to-date"))
                add("Week low", float(week["low"].min()), "H1", "WEEK_LOW", ("week-to-date"))

    # PSYCHOLOGICAL levels: included only with repeated H1 touches, and only near price.
    if atr_m5_now > 0 and atr_h1_now > 0 and h1 is not None and len(h1) >= 50:
        recent = h1.tail(50)
        base = round(price / PSYCH_STEP) * PSYCH_STEP
        for level in (base - PSYCH_STEP, base, base + PSYCH_STEP):
            if abs(level - price) > PSYCH_NEAR_ATR * atr_m5_now:
                continue
            tol = PSYCH_TOUCH_ATR * atr_h1_now
            near_level = ((recent["high"] - level).abs() <= tol) | ((recent["low"] - level).abs() <= tol)
            touches = int(near_level.sum())
            if touches >= PSYCH_MIN_TOUCHES:
                add(f"Round level {level:.0f}", level, "H1", "PSYCH_LEVEL", f"{touches} H1 touches in 50 bars")

    return comps


def _strength(components) -> tuple:
    kinds = {c.evidence.kind for c in components}
    timeframes = {c.evidence.timeframe for c in components}
    if len(kinds) >= 3 and len(timeframes) >= 2:
        status = "HIGH"
    elif len(kinds) >= 2:
        status = "MODERATE"
    else:
        status = "LOW"
    reason = (f"{len(kinds)} distinct reference kind(s) across {len(timeframes)} timeframe(s): "
              + ", ".join(sorted(kinds)))
    return status, reason


def build_key_areas(m5: pd.DataFrame, h1: pd.DataFrame, h4: pd.DataFrame,
                    current_price: float) -> List[KeyArea]:
    """Return merged key areas sorted by price. Empty when there is not enough data."""
    if m5 is None or m5.empty:
        return []
    atr_series = compute_atr(m5)
    atr = float(atr_series.iloc[-1]) if len(atr_series) else float("nan")
    if not atr > 0:
        return []

    comps = sorted(_components(m5, h1, h4), key=lambda c: c.price)
    if not comps:
        return []

    groups: List[List[KeyComponent]] = [[comps[0]]]
    for c in comps[1:]:
        if c.price - groups[-1][-1].price <= MERGE_TOL_ATR * atr:
            groups[-1].append(c)
        else:
            groups.append([c])

    areas: List[KeyArea] = []
    for g in groups:
        low = min(c.price for c in g)
        high = max(c.price for c in g)
        mid = (low + high) / 2
        side = "RESISTANCE" if mid > current_price else "SUPPORT" if mid < current_price else "MIXED"
        status, reason = _strength(g)
        areas.append(KeyArea(low=round(low, 2), high=round(high, 2), components=tuple(g),
                             side=side, strength_status=status, strength_reason=reason))
    return areas


def relationship(area: KeyArea, current_price: float, atr: float) -> Relationship:
    """Where the current price sits relative to one area, in ATR units."""
    if area.low <= current_price <= area.high:
        return Relationship(area, 0.0, "INSIDE")
    edge = area.low if current_price < area.low else area.high
    distance = atr_normalized_distance(edge, current_price, atr)
    relation = "APPROACHING" if abs(distance) <= NEAR_ATR else "FAR"
    return Relationship(area, distance, relation)
