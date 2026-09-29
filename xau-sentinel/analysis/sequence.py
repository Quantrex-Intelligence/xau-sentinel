"""M5 entry-sequence tracking: sweep -> MSS -> displacement -> retracement.

Each step is located on its own CLOSED bar, in order, starting from the
liquidity-sweep bar — rather than requiring every condition to hold on the
literal latest bar at once (Stage 23A, VAL-008/009/018 — see
docs/validation/ISSUE_LOG.md). Pure and deterministic: the same closed
candles and sweep always produce the same result, and because closed bars
never change, an invalidated sweep stays invalidated for as long as it is
the candidate — no persisted state needed.

Like the rest of analysis/, this only labels price action that has already
happened. It does not predict outcomes.
"""
from dataclasses import dataclass
from typing import Optional

import pandas as pd

import config
from analysis.liquidity import LiquidityEvent
from analysis.structure import compute_atr, displacement_at, find_swing_points


@dataclass
class SequenceResult:
    sweep_index: Optional[int] = None
    mss_index: Optional[int] = None
    mss_level: Optional[float] = None
    displacement_index: Optional[int] = None
    retracement_ok: bool = False
    retrace_pct: Optional[float] = None
    invalidated: bool = False
    invalidation_reason: str = ""

    @property
    def mss_ok(self) -> bool:
        return self.mss_index is not None and not self.invalidated

    @property
    def displacement_ok(self) -> bool:
        return self.displacement_index is not None and not self.invalidated


def _bar_index(df: pd.DataFrame, ts) -> Optional[int]:
    if ts is None:
        return None
    matches = df.index[df["time"] == ts]
    return int(matches[0]) if len(matches) else None


def evaluate_sequence(m5: pd.DataFrame, sweep: Optional[LiquidityEvent], direction: str) -> SequenceResult:
    """`m5` must be CLOSED candles only (analysis.structure.closed_only),
    indexed 0..n-1. `direction` is "BUY" (anchored by a sweep_low) or "SELL"
    (anchored by a sweep_high).

    1. MSS: the first bar at/after the sweep that CLOSES beyond the most
       recent opposing swing confirmed before the sweep (for BUY: the last
       swing high) — a shift tied to a concrete bar, not a current state.
    2. Displacement: the first bar at/after the sweep with an outsized,
       ATR-relative body in `direction`.
    3. Retracement: only on the latest bar, and only if that bar is strictly
       after both the MSS bar and the displacement bar — measured against the
       impulse from the sweep bar's extreme to the best price since.
    4. Invalidation: only after an MSS — any later bar closing back beyond
       the sweep bar's extreme. The opposing structure BEFORE the MSS is the
       setup's normal precursor, not an invalidation.
    """
    result = SequenceResult()
    if m5 is None or m5.empty or sweep is None:
        return result

    df = m5.reset_index(drop=True)
    sweep_idx = _bar_index(df, sweep.time)
    if sweep_idx is None:
        return result
    result.sweep_index = sweep_idx
    n = len(df)
    buy = direction == "BUY"

    swings = [p for p in find_swing_points(df)
              if p.kind == ("high" if buy else "low") and p.index < sweep_idx]
    closes = df["close"].values
    if swings:
        level = swings[-1].price
        result.mss_level = level
        for i in range(sweep_idx, n):
            if (closes[i] > level) if buy else (closes[i] < level):
                result.mss_index = i
                break

    atr = compute_atr(df)
    wanted = "bullish" if buy else "bearish"
    for i in range(sweep_idx, n):
        if displacement_at(df, i, atr=atr) == wanted:
            result.displacement_index = i
            break

    sweep_extreme = float(df["low"].iloc[sweep_idx]) if buy else float(df["high"].iloc[sweep_idx])
    if result.mss_index is not None:
        after = closes[result.mss_index + 1:]
        broke = (after < sweep_extreme).any() if buy else (after > sweep_extreme).any()
        if broke:
            result.invalidated = True
            side = "below the swept low" if buy else "above the swept high"
            result.invalidation_reason = (
                f"M5 closed back {side} ({sweep_extreme:.2f}) after the market structure shift."
            )
            return result

    if result.mss_index is None or result.displacement_index is None:
        return result
    last = n - 1
    if last <= max(result.mss_index, result.displacement_index):
        return result

    since = df.iloc[sweep_idx:]
    if buy:
        impulse_low, impulse_high = sweep_extreme, float(since["high"].max())
    else:
        impulse_low, impulse_high = float(since["low"].min()), sweep_extreme
    if impulse_high <= impulse_low:
        return result
    last_close = float(closes[last])
    pct = ((impulse_high - last_close) if buy else (last_close - impulse_low)) / (impulse_high - impulse_low)
    result.retrace_pct = round(pct, 4)
    result.retracement_ok = config.RETRACEMENT_MIN_PCT <= pct <= config.RETRACEMENT_MAX_PCT
    return result
