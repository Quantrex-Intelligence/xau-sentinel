"""The locked A+ strategy specification, encoded as explicit, configurable,
pure functions — nothing here is inferred or invented; every function maps
to one numbered item in the user-provided specification (noted in each
docstring). Thresholds come from config.py (env-overridable), never
hardcoded inline.

These are Rules, not Evidence and not a Rating: every function here answers
one yes/no/can't-tell question about facts the deterministic engines
already produced (analysis/structure.py, analysis/liquidity.py,
analysis/zones.py, risk/fundednext.py). ai/strategy/evaluator.py is the only
caller, and it — not the LLM — decides the final rating from these answers.
"""
import math
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import config
from analysis.liquidity import LiquidityEvent, SWEEPABLE_HIGH_LEVELS, SWEEPABLE_LOW_LEVELS
from analysis.sequence import SequenceResult
from risk.models import FundedNextStatus, SafetyLevel

# direction -> the liquidity kind that anchors a candidate in that direction,
# and the zone-name list that qualifies as "meaningful opposing liquidity"
# for that direction's target (item 9) — both drawn directly from Stage 1's
# own qualifying-level lists (item 3's "existing Stage 1 qualifying liquidity
# types"), never a new list.
_SWEEP_KIND_FOR_DIRECTION = {"BUY": "sweep_low", "SELL": "sweep_high"}
_TARGET_ZONE_NAMES_FOR_DIRECTION = {"BUY": SWEEPABLE_HIGH_LEVELS, "SELL": SWEEPABLE_LOW_LEVELS}


def select_candidate(sweeps: List[LiquidityEvent]) -> Optional[LiquidityEvent]:
    """Item 3 + item 7 (sequence starts at the liquidity sweep): the most
    recent qualifying-type sweep, of either kind, anchors the candidate and
    its direction — a sweep_low anchors a BUY candidate, a sweep_high a
    SELL candidate. `sweeps` must already be Stage 1's detect_sweeps()
    output (PDH/PDL/session/H1/H4-swing only) — equal highs/lows are never
    passed in here (item 3's second decision: supporting evidence only)."""
    if not sweeps:
        return None
    return max(sweeps, key=lambda s: s.time)


def candidate_direction(sweep: LiquidityEvent) -> str:
    return "BUY" if sweep.kind == "sweep_low" else "SELL"


def is_within_sweep_window(sweep_time, now: datetime, window_minutes: int = None) -> bool:
    """Item 10 (expiry) + item 7 (sequence recency): the qualifying sweep
    must be within `window_minutes` of the current M5 snapshot."""
    window_minutes = window_minutes if window_minutes is not None else config.AI_STRATEGY_SWEEP_WINDOW_MINUTES
    sweep_time = _as_utc(sweep_time)
    now = _as_utc(now)
    return (now - sweep_time) <= timedelta(minutes=window_minutes)


def _as_utc(ts) -> datetime:
    if hasattr(ts, "to_pydatetime"):
        ts = ts.to_pydatetime()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts


def is_opposing_mss_invalidated(seq: SequenceResult) -> bool:
    """Item 10: an opposing M5 structure break invalidates the candidate.
    Only a break that happens AFTER the candidate's own MSS counts — price
    closing back beyond the swept extreme (analysis/sequence.py). The
    opposing M5 structure before the MSS is the setup's normal precursor,
    not an invalidation (Stage 23A, VAL-008). Same condition Stage 1's
    INVALIDATED branch (analysis/setup.py) uses."""
    return seq.invalidated


def is_h1_flip_invalidated(direction: str, h1_state: str) -> bool:
    """Item 10 (locked interpretation): H1 bias flipping to the hard
    opposite state invalidates the candidate before entry. Only the
    opposite hard state counts as a "flip" — H1 merely being RANGING (not
    yet confirming) is not a flip, it's just not-yet-supported, which the
    sweep-recency window already handles via expiry."""
    return (direction == "BUY" and h1_state == "BEARISH") or (direction == "SELL" and h1_state == "BULLISH")


def h1_supports_direction(direction: str, h1_state: str, h1_last_mss: Optional[str]) -> bool:
    """Item 1 + item 2: H1 is required and must support the candidate
    direction — the exact gate analysis/setup.py::detect_setup already uses
    for its own `direction` field, reapplied here against the CURRENT H1
    read (which may differ from Stage 1's gate if H1 has since flipped)."""
    if direction == "BUY":
        return h1_state in ("BULLISH", "PULLBACK") and h1_last_mss != "bearish"
    return h1_state in ("BEARISH", "PULLBACK") and h1_last_mss != "bullish"


def is_m5_mss_confirmed(seq: SequenceResult) -> bool:
    """Item 5: M5 only, an actual shift tied to a concrete bar at/after the
    sweep (analysis/sequence.py) — not merely "the latest close is beyond a
    swing" (Stage 23A, VAL-018)."""
    return seq.mss_ok


def is_displacement_confirmed(seq: SequenceResult) -> bool:
    """Item 6: an outsized, ATR-relative candle in the candidate's direction
    on some bar at/after the sweep — not only on the latest bar (Stage 23A,
    VAL-009)."""
    return seq.displacement_ok


def compute_stop_loss(direction: str, swept_level_price: float, buffer: float = None) -> float:
    """Item 8: beyond the swept liquidity level with a buffer (default
    $0.30). BUY swept a low -> SL below it; SELL swept a high -> SL above it."""
    buffer = buffer if buffer is not None else config.AI_STRATEGY_SL_BUFFER
    return round(swept_level_price - buffer, 2) if direction == "BUY" else round(swept_level_price + buffer, 2)


def select_target(direction: str, zones: dict, entry: float) -> Optional[float]:
    """Item 9: the nearest meaningful OPPOSING liquidity level beyond entry
    — restricted to Stage 1's own qualifying liquidity zone names (the same
    list item 3 restricts sweeps to), per the locked spec's "meaningful"
    reading. Returns None if no qualifying zone exists on the target side —
    never a fabricated or fixed-multiple target."""
    candidates = [
        price for name, price in zones.items()
        if name in _TARGET_ZONE_NAMES_FOR_DIRECTION[direction]
        and (price > entry if direction == "BUY" else price < entry)
    ]
    if not candidates:
        return None
    return min(candidates) if direction == "BUY" else max(candidates)


def signed_risk(direction: str, entry: float, stop_loss: float) -> float:
    """Distance from entry to stop on the side the stop must be on: BUY
    stops sit below entry, SELL stops above. Zero or negative means price
    has already traded through the stop level (Stage 23A, VAL-010)."""
    return entry - stop_loss if direction == "BUY" else stop_loss - entry


def compute_risk_reward(direction: str, entry: float, stop_loss: float, target: Optional[float]):
    """Item 9: actual R:R from entry->SL and entry->target — never a fixed
    3R target. Returns (rr, risk, reward) with rr UNROUNDED — compare it
    with passes_min_rr() and round only for display (display_rr()). rr is
    None when it can't be computed: no target, or a stop that is not on
    the correct side of entry (risk <= 0)."""
    risk = signed_risk(direction, entry, stop_loss)
    if target is None or risk <= 0:
        return None, risk, None
    reward = abs(target - entry)
    return reward / risk, risk, reward


def display_rr(rr: Optional[float]) -> Optional[float]:
    """Floors to 2 dp, so a displayed ratio can never overstate the true one
    (a real 2.996 shows as 2.99, never 3.0)."""
    return None if rr is None else math.floor(rr * 100 + 1e-9) / 100


def passes_min_rr(rr: Optional[float], min_rr: float = None) -> bool:
    """Compares the UNROUNDED ratio (Stage 23A, VAL-010)."""
    min_rr = min_rr if min_rr is not None else config.AI_STRATEGY_MIN_RR
    return rr is not None and rr >= min_rr


def check_fundednext_gate(status: FundedNextStatus, max_daily_loss_used_pct: float = None):
    """Item 11: A+ is prohibited unless risk status is SAFE and daily loss
    used is below the configured percentage of the permitted daily-loss
    limit. Returns (passed: bool, reason: str)."""
    max_daily_loss_used_pct = (
        max_daily_loss_used_pct if max_daily_loss_used_pct is not None
        else config.AI_STRATEGY_FUNDEDNEXT_MAX_DAILY_LOSS_USED_PCT
    )
    if not status.data_available:
        return False, f"FundedNext data unavailable — {status.reason}"
    if status.safety_level != SafetyLevel.SAFE:
        return False, f"FundedNext safety level is {status.safety_level.value}, not SAFE."
    if status.daily_loss_used_pct is None or status.daily_loss_used_pct >= max_daily_loss_used_pct:
        used = status.daily_loss_used_pct
        return False, f"Daily loss used ({used}%) is at or above the {max_daily_loss_used_pct}% A+ limit."
    return True, "SAFE and daily loss used is below the A+ limit."
