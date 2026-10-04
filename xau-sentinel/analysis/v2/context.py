"""Layer 4 of Analysis Engine V2: market context as independent dimensions.

Each dimension answers one question and reports its own state. They are kept
separate on purpose, and nothing here is combined into a score, a grade or a
confidence percentage. The regime comes from the existing classify_regime();
the other dimensions are derived from the same closed-candle observations.
"""
from dataclasses import dataclass
from typing import Dict, Optional

import config
from analysis.regime import classify_regime
from analysis.v2.events import Event
from analysis.v2.observations import Observations

def _ordinal(n: float) -> str:
    n = int(round(n))
    suffix = 'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f'{n}{suffix}'


VOLATILITY_HIGH_PCT = 70.0
VOLATILITY_LOW_PCT = 30.0


@dataclass(frozen=True)
class Dimension:
    state: str
    detail: str


@dataclass(frozen=True)
class MarketContext:
    direction: Dimension  # trend: UP | DOWN | NONE; phase: TRENDING | PULLBACK | RANGING
    structure: Dict[str, Dimension]  # per timeframe state
    regime: Dimension
    volatility: Dimension
    volume: Dimension
    liquidity: Dimension
    momentum: Dimension
    session: Dimension
    price_location: Dimension


def _trend_from_state(state: str, last_mss: Optional[str]) -> tuple:
    if state == "BULLISH":
        return "UP", "TRENDING"
    if state == "BEARISH":
        return "DOWN", "TRENDING"
    if state == "PULLBACK":
        # A pullback is a move against the trend. A bearish MSS inside an up
        # structure means the trend is still UP and price is pulling back.
        if last_mss == "bearish":
            return "UP", "PULLBACK"
        if last_mss == "bullish":
            return "DOWN", "PULLBACK"
        return "NONE", "PULLBACK"
    if state == "INSUFFICIENT":
        return "NONE", "UNKNOWN"
    return "NONE", "RANGING"


def _volatility(obs: Observations) -> Dimension:
    pct, change = obs.atr_percentile_m5, obs.atr_change_m5
    if pct is None:
        return Dimension("UNKNOWN", "Not enough ATR history for a percentile.")
    level = "HIGH" if pct >= VOLATILITY_HIGH_PCT else "LOW" if pct <= VOLATILITY_LOW_PCT else "NORMAL"
    if change is None:
        trend = "STABLE"
    elif change >= config.HIGH_VOL_ATR_MULT:
        trend = "EXPANDING"
    elif change <= config.LOW_VOL_ATR_MULT:
        trend = "CONTRACTING"
    else:
        trend = "STABLE"
    return Dimension(f"{level}_{trend}" if trend != "STABLE" else level,
                     f"M5 ATR is at the {_ordinal(pct)} percentile of its last 100 bars; ratio to 10 bars ago "
                     f"{change:.2f}." if change is not None else f"M5 ATR is at the {_ordinal(pct)} percentile.")


def _volume(obs: Observations) -> Dimension:
    vol = obs.volume_m5 or {}
    state = vol.get("state", "UNKNOWN")
    rel = vol.get("relative_volume")
    if state == "UNKNOWN" or rel is None or rel != rel:
        return Dimension("UNKNOWN", "Not enough tick-volume history for a relative volume.")
    return Dimension(state, f"Last closed M5 tick volume is {rel:.2f}x the prior 20-bar mean "
                            f"(tick volume is an activity proxy, not traded volume).")


def _liquidity(obs: Observations) -> Dimension:
    sweeps = list(obs.sweeps)
    lows = [s for s in sweeps if s.kind == "sweep_low"]
    highs = [s for s in sweeps if s.kind == "sweep_high"]
    if lows and highs:
        state = "SWEPT_BOTH_SIDES"
    elif lows:
        state = "SWEPT_LOW"
    elif highs:
        state = "SWEPT_HIGH"
    else:
        state = "NO_RECENT_SWEEP"
    equal = []
    if any(e.kind == "equal_high" for e in obs.equal_levels):
        equal.append("equal highs")
    if any(e.kind == "equal_low" for e in obs.equal_levels):
        equal.append("equal lows")
    detail = "No qualifying liquidity sweep among recent M5 bars."
    if sweeps:
        detail = "Recent sweeps: " + "; ".join(sorted(s.label for s in sweeps)) + "."
    if equal:
        detail += " Resting liquidity: " + " and ".join(equal) + "."
    return Dimension(state, detail)


def _momentum(m5_closed, events) -> Dimension:
    if m5_closed is None or len(m5_closed) < 8:
        return Dimension("UNKNOWN", "Not enough closed M5 bars for a momentum read.")
    body = (m5_closed["close"] - m5_closed["open"]).astype(float)
    recent = body.iloc[-3:]
    earlier = body.iloc[-6:-3]
    earlier_mean = earlier.abs().mean()
    recent_mean = recent.abs().mean()
    if earlier_mean <= 0:
        return Dimension("UNKNOWN", "Earlier bodies are flat, so momentum is not measurable.")
    direction = "up" if recent.sum() > 0 else "down" if recent.sum() < 0 else "flat"
    if any(e.kind == "MOMENTUM_LOSS" for e in events):
        state = "FADING"
    elif recent_mean >= 1.5 * earlier_mean:
        state = "ACCELERATING"
    else:
        state = "STEADY"
    return Dimension(state, f"Last 3 M5 bodies average {recent_mean / earlier_mean:.0%} of the prior 3; "
                            f"recent net direction {direction}.")


def _price_location(obs: Observations) -> Dimension:
    p = obs.current_price
    z = obs.zones or {}
    pdh, pdl = z.get("Previous Day High"), z.get("Previous Day Low")
    dh, dl = z.get("Current Day High"), z.get("Current Day Low")
    if p is None:
        return Dimension("UNKNOWN", "No current price.")
    if pdh is not None and p > pdh:
        return Dimension("ABOVE_PREVIOUS_DAY_HIGH", f"Price {p:.2f} is above the previous day high {pdh:.2f}.")
    if pdl is not None and p < pdl:
        return Dimension("BELOW_PREVIOUS_DAY_LOW", f"Price {p:.2f} is below the previous day low {pdl:.2f}.")
    if dh is None or dl is None or dh <= dl:
        return Dimension("UNKNOWN", "No current-day range yet.")
    share = (p - dl) / (dh - dl)
    third = "UPPER_THIRD" if share >= 2 / 3 else "LOWER_THIRD" if share <= 1 / 3 else "MIDDLE_THIRD"
    return Dimension(third, f"Price sits at {share:.0%} of the current day range {dl:.2f}-{dh:.2f}.")


def build_context(obs: Observations, closed: dict, events) -> MarketContext:
    """Independent dimensions from observations, closed bars and events. Each
    dimension is reported on its own; none is combined with another."""
    h1_struct, h4_struct = obs.structure["H1"], obs.structure["H4"]
    trend, phase = _trend_from_state(h1_struct.state, h1_struct.last_mss)
    if trend == "NONE":
        h4_trend, h4_phase = _trend_from_state(h4_struct.state, h4_struct.last_mss)
        if h4_trend != "NONE":
            trend, phase = h4_trend, h4_phase
            detail = f"H1 has no clear trend; H4 is {h4_trend.lower()}."
        else:
            detail = f"H1 is {h1_struct.state.lower()} and H4 is {h4_struct.state.lower()}: no clear trend."
    else:
        detail = f"H1 structure {h1_struct.state.lower()}."
    if trend != "NONE":
        detail += f" Phase: {phase.lower()}."

    regime_state, regime_detail = "UNKNOWN", "Regime needs closed H1 and M15 history."
    h1_closed, m15_closed = closed.get("H1"), closed.get("M15")
    if h1_closed is not None and m15_closed is not None:
        r = classify_regime(h1_closed, m15_closed)
        regime_state, regime_detail = r.regime, r.reason

    return MarketContext(
        direction=Dimension(trend, detail),
        structure={tf: Dimension(obs.structure[tf].state, obs.structure[tf].reason) for tf in obs.structure},
        regime=Dimension(regime_state, regime_detail),
        volatility=_volatility(obs),
        volume=_volume(obs),
        liquidity=_liquidity(obs),
        momentum=_momentum(closed.get("M5"), events),
        session=Dimension(obs.session or "UNKNOWN", "Session from the configured UTC windows."),
        price_location=_price_location(obs),
    )
