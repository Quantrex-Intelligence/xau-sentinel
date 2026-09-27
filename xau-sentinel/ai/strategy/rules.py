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
from datetime import datetime, timedelta, timezone
from typing import List, Optional

import config
from analysis.liquidity import LiquidityEvent, SWEEPABLE_HIGH_LEVELS, SWEEPABLE_LOW_LEVELS
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


def is_opposing_mss_invalidated(direction: str, m5_state: str) -> bool:
    """Item 10: an opposing M5 structure break invalidates the candidate —
    identical condition to Stage 1's own INVALIDATED branch
    (analysis/setup.py), reapplied here since Stage 4 tracks its own rating
    independently of Stage 1's state string."""
    return (direction == "BUY" and m5_state == "BEARISH") or (direction == "SELL" and m5_state == "BULLISH")


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


def is_m5_mss_confirmed(direction: str, m5_last_mss: Optional[str]) -> bool:
    """Item 5: M5 only, an actual shift (not merely an established trend) —
    identical condition to Stage 1's hardened MSS check."""
    return (direction == "BUY" and m5_last_mss == "bullish") or (direction == "SELL" and m5_last_mss == "bearish")


def is_displacement_confirmed(direction: str, displacement: Optional[str]) -> bool:
    """Item 6: identical condition to Stage 1's displacement check."""
    return (direction == "BUY" and displacement == "bullish") or (direction == "SELL" and displacement == "bearish")


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


def compute_risk_reward(direction: str, entry: float, stop_loss: float, target: Optional[float]):
    """Item 9: actual R:R from entry->SL and entry->target — never a fixed
    3R target. Returns (rr, risk, reward); rr is None when it can't be
    computed (no target, or a degenerate/zero-risk stop)."""
    risk = abs(entry - stop_loss)
    if target is None or risk <= 0:
        return None, risk, None
    reward = abs(target - entry)
    return round(reward / risk, 2), risk, reward


def passes_min_rr(rr: Optional[float], min_rr: float = None) -> bool:
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
