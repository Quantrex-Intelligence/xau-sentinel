"""Deterministic setup state machine.

NO SETUP -> DEVELOPING -> VALID -> INVALIDATED

Combines H1 direction, M15 direction, key-zone proximity, a liquidity sweep,
an M5 MSS, displacement, and a retracement into a checklist. This flags when
a configurable set of price-action conditions has lined up — it does not
predict outcomes and does not guarantee a profitable trade. All final
trading decisions and execution are manual.
"""
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

import config
from analysis.structure import analyze_structure, closed_only, detect_displacement
from analysis.liquidity import detect_sweeps, detect_equal_levels
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


def detect_setup(candles: dict, zone_proximity: float = None) -> SetupResult:
    """`candles` is a dict of timeframe -> DataFrame for M5, M15, H1, H4.

    Structural confirmation (structure, zones, sweeps, equal levels,
    displacement, and — below — retracement) is computed only from CLOSED
    candles (Stage 21, VAL-006). `current_price` is the one deliberate
    exception: current-price context (zone proximity, entry planning)
    legitimately reads the unfiltered set's last close, which may still be
    forming."""
    zone_proximity = zone_proximity if zone_proximity is not None else config.LIQUIDITY_SWEEP_BUFFER_PIPS * 6

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
        "displacement": displacement,
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

    # An actual detected structure shift, not merely an established trend:
    # analyze_structure only ever sets last_mss alongside state == "PULLBACK",
    # so checking last_mss directly is the precise "did a shift just happen"
    # signal — checking m5.state == "BULLISH"/"BEARISH" here would just mean
    # "M5 already agrees with the trend," which is a different, weaker claim.
    m5_mss_ok = (direction == "BUY" and m5.last_mss == "bullish") or \
                (direction == "SELL" and m5.last_mss == "bearish")

    displacement_ok = (direction == "BUY" and displacement == "bullish") or \
                       (direction == "SELL" and displacement == "bearish")

    checklist = {
        "Liquidity Sweep": bool(relevant_sweep) and near_zone,
        "MSS": m5_mss_ok,
        "Displacement": displacement_ok,
        "Retracement": False,
    }

    # Invalidation: the liquidity sweep already fired (something to invalidate), but
    # M5 has since broken firmly the other way. Gated on the sweep rather than
    # checklist["MSS"]: analyze_structure only ever pairs last_mss with state ==
    # "PULLBACK", never with the opposite hard state, so an MSS-gated check here
    # could never fire — m5.state can't simultaneously be BULLISH/BEARISH-opposite
    # and satisfy m5_mss_ok in the same direction. See tests/test_setup.py.
    if checklist["Liquidity Sweep"] and (
        (direction == "BUY" and m5.state == "BEARISH") or (direction == "SELL" and m5.state == "BULLISH")
    ):
        return SetupResult(state="INVALIDATED", direction=direction, checklist=checklist,
                            reason=f"M5 {m5.state.lower()} structure break invalidated the {direction} setup.",
                            context=context)

    completed = sum(1 for v in checklist.values() if v)
    if completed == 0:
        return SetupResult(state="NO SETUP", direction=direction, checklist=checklist,
                            reason=f"H1 {direction.lower()} bias present, but no sweep, MSS, or displacement yet.",
                            context=context)

    if checklist["Liquidity Sweep"] and checklist["MSS"] and checklist["Displacement"]:
        retracement_ok = _check_retracement(closed["M5"], direction)
        checklist["Retracement"] = retracement_ok
        if retracement_ok:
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


def _check_retracement(df: pd.DataFrame, direction: str, lookback: int = 10) -> bool:
    recent = df.tail(lookback)
    impulse_high = float(recent["high"].max())
    impulse_low = float(recent["low"].min())
    if impulse_high <= impulse_low:
        return False

    last_close = float(recent["close"].iloc[-1])
    if direction == "BUY":
        retrace_pct = (impulse_high - last_close) / (impulse_high - impulse_low)
    else:
        retrace_pct = (last_close - impulse_low) / (impulse_high - impulse_low)

    return config.RETRACEMENT_MIN_PCT <= retrace_pct <= config.RETRACEMENT_MAX_PCT


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
