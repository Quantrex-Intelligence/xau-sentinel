"""Deterministic setup state machine.

NO SETUP -> DEVELOPING -> VALID -> INVALIDATED

Combines H1 direction, M15 direction, key-zone proximity, a liquidity sweep,
an M5 MSS, displacement, and a retracement into a checklist. This flags when
a configurable set of price-action conditions has lined up — it does not
predict outcomes and does not guarantee a profitable trade. All final
trading decisions and execution are manual.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

import config
from analysis.structure import analyze_structure, closed_only, detect_displacement, is_feed_stale
from analysis.liquidity import detect_sweeps, detect_equal_levels
from analysis.sequence import evaluate_sequence
from analysis.zones import compute_zones

CHECKLIST_STEPS = ["Liquidity Sweep", "MSS", "Displacement", "Retracement"]


@dataclass
class SetupResult:
    state: str
    direction: Optional[str] = None  # "BUY" or "SELL"
    checklist: dict = field(default_factory=dict)
    entry_zone: Optional[tuple] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    rr: Optional[float] = None
    reason: str = ""
    context: dict = field(default_factory=dict)


def _nearest_zone_distance(price: float, zones: dict) -> float:
    relevant = {k: v for k, v in zones.items() if k != "VWAP"}
    if not relevant:
        return float("inf")
    return min(abs(price - v) for v in relevant.values())


def detect_setup(candles: dict, zone_proximity: float = None, now: Optional[datetime] = None) -> SetupResult:
    """`candles` is a dict of timeframe -> DataFrame for M5, M15, H1, H4.

    Structural confirmation (structure, zones, sweeps, equal levels, and the
    sweep -> MSS -> displacement -> retracement sequence) is computed only
    from CLOSED candles (Stage 21, VAL-006). `current_price` is the one
    deliberate exception: current-price context (zone proximity, entry
    planning) legitimately reads the unfiltered set's last close, which may
    still be forming.

    The M5 checklist steps come from analysis/sequence.py, each located on
    its own bar in order from the sweep (Stage 23A, VAL-008/009/018). A
    stale feed (`now` vs the newest M5 candle) can never be VALID
    (Stage 23A, VAL-011)."""
    zone_proximity = zone_proximity if zone_proximity is not None else config.LIQUIDITY_SWEEP_BUFFER_PIPS * 6
    now = now or datetime.now(timezone.utc)

    closed = closed_only(candles)
    h4_struct = analyze_structure(closed["H4"])
    h1 = analyze_structure(closed["H1"])
    m15 = analyze_structure(closed["M15"])
    m5 = analyze_structure(closed["M5"])
    zones = compute_zones(closed["M5"], closed["H1"], closed["H4"])

    current_price = float(candles["M5"]["close"].iloc[-1])
    sweeps = detect_sweeps(closed["M5"], zones)
    equal_levels = detect_equal_levels(closed["M5"])
    displacement = detect_displacement(closed["M5"])
    data_stale = is_feed_stale(candles["M5"], now)

    context = {
        "h4_bias": h4_struct.state,
        "h1_bias": h1.state,
        "m15_bias": m15.state,
        "m5_bias": m5.state,
        "zones": zones,
        "sweeps": [s.label for s in sweeps[-3:]],
        # Equal highs/lows are exposed as deterministic liquidity information
        # (per the liquidity module's own scope) but are NOT wired into the
        # checklist below — the setup strategy is unchanged by this.
        "equal_levels": [e.label for e in equal_levels[-3:]],
        # Latest-candle displacement, for display only — the checklist's own
        # Displacement step is the sequence's displacement bar below.
        "displacement": displacement,
        "data_stale": data_stale,
    }

    direction = None
    if h1.state in ("BULLISH", "PULLBACK") and h1.last_mss != "bearish":
        direction = "BUY"
    elif h1.state in ("BEARISH", "PULLBACK") and h1.last_mss != "bullish":
        direction = "SELL"

    if direction is None:
        return SetupResult(state="NO SETUP", checklist={s: "WAITING" for s in CHECKLIST_STEPS},
                            reason="No clear H1 directional bias yet.", context=context)

    near_zone = _nearest_zone_distance(current_price, zones) <= zone_proximity

    relevant_sweep = next(
        (s for s in reversed(sweeps)
         if (direction == "BUY" and s.kind == "sweep_low") or (direction == "SELL" and s.kind == "sweep_high")),
        None,
    )

    # The M5 steps only exist relative to a sweep: the sequence starts at the
    # sweep bar, so an MSS or displacement with no qualifying sweep behind it
    # is not part of this setup.
    seq = evaluate_sequence(closed["M5"], relevant_sweep, direction)

    checklist = {
        "Liquidity Sweep": bool(relevant_sweep) and near_zone,
        "MSS": seq.mss_ok,
        "Displacement": seq.displacement_ok,
        "Retracement": seq.retracement_ok,
    }

    # Invalidation: the sweep fired, an MSS followed, and price has since
    # closed back beyond the swept extreme. The opposing M5 structure that
    # precedes the MSS is the setup's normal precursor and never invalidates
    # it (Stage 23A, VAL-008).
    if checklist["Liquidity Sweep"] and seq.invalidated:
        return SetupResult(state="INVALIDATED", direction=direction, checklist=checklist,
                            reason=f"{direction} setup invalidated: {seq.invalidation_reason}",
                            context=context)

    completed = sum(1 for v in checklist.values() if v)
    if completed == 0:
        return SetupResult(state="NO SETUP", direction=direction, checklist=checklist,
                            reason=f"H1 {direction.lower()} bias present, but no sweep, MSS, or displacement yet.",
                            context=context)

    if checklist["Liquidity Sweep"] and checklist["MSS"] and checklist["Displacement"]:
        if checklist["Retracement"]:
            if data_stale:
                return SetupResult(state="DEVELOPING", direction=direction, checklist=checklist,
                                    reason="All steps confirmed, but market data is stale — no new M5 candle "
                                           "has arrived recently, so this cannot be treated as a live setup.",
                                    context=context)
            entry_zone, sl, tp, rr = _plan_trade(closed["M5"], current_price, direction)
            if rr is not None:
                return SetupResult(state="VALID", direction=direction, checklist=checklist,
                                    entry_zone=entry_zone, stop_loss=sl, take_profit=tp, rr=rr,
                                    reason=f"{direction} setup fully confirmed: sweep + MSS + displacement + retracement.",
                                    context=context)
            # Degenerate stop distance (current close sits exactly on the planning
            # window's extreme) — nothing tradeable yet, keep waiting rather than
            # surface a VALID setup with a zero-risk stop loss.
        return SetupResult(state="DEVELOPING", direction=direction, checklist=checklist,
                            reason="Sweep, MSS and displacement confirmed. Waiting for retracement.",
                            context=context)

    done_steps = ", ".join(k for k, v in checklist.items() if v) or "none yet"
    return SetupResult(state="DEVELOPING", direction=direction, checklist=checklist,
                        reason=f"{direction} bias building — confirmed: {done_steps}.", context=context)


def _plan_trade(closed_df: pd.DataFrame, current_price: float, direction: str, lookback: int = 10):
    """`closed_df` (CLOSED candles only) supplies the SL/TP range;
    `current_price` (the live/forming-inclusive close, explicitly passed
    in by the caller — Stage 21, VAL-006) is the entry reference."""
    recent = closed_df.tail(lookback)

    if direction == "BUY":
        sl = float(recent["low"].min())
        risk = current_price - sl
        entry_zone = (round(current_price - risk * 0.15, 2), round(current_price + risk * 0.05, 2))
        tp = round(current_price + risk * 2.4, 2)
    else:
        sl = float(recent["high"].max())
        risk = sl - current_price
        entry_zone = (round(current_price - risk * 0.05, 2), round(current_price + risk * 0.15, 2))
        tp = round(current_price - risk * 2.4, 2)

    rr = round(abs(tp - current_price) / risk, 2) if risk > 0 else None
    return entry_zone, round(sl, 2), tp, rr
