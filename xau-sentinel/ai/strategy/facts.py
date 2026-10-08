"""The facts A+ decides from, as one value object.

A+ never reads candles directly in its decision step. It reads these facts,
which come from one of two sources:

- legacy: collect_legacy_facts() in ai/strategy/evaluator.py, computed from
  raw candles exactly as the A+ evaluator always has.
- v2: ai/v2_strategy/bridge.py, which maps Analysis Engine V2's structured
  output onto the same fields.

The A+ rules (ai/strategy/rules.py) and the decision step are identical for
both sources. Only where the facts come from differs.
"""
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from analysis.liquidity import LiquidityEvent
from analysis.sequence import SequenceResult
from analysis.structure import StructureResult


@dataclass(frozen=True)
class StrategyFacts:
    h4: StructureResult
    h1: StructureResult
    m15: StructureResult
    m5: StructureResult
    zones: dict
    sweeps: List[LiquidityEvent]
    equal_levels: List[LiquidityEvent]
    m5_closed: pd.DataFrame  # closed M5 bars; the sequence and the labels read these
    current_price: float  # entry-price context (see closed_only's documented exception)
    data_stale: bool
    # The M5 sequence for the current candidate, when the source already computed it (V2).
    # None means the decision computes it from m5_closed exactly as the legacy path always has.
    sequence: Optional[SequenceResult] = None
    # False when V2 found the sequence's steps out of order (displacement before the structure
    # shift). The decision then treats the MSS and displacement as NOT confirmed, so an
    # out-of-order sequence is never accepted as valid evidence. True for every other source.
    sequence_chronology_ok: bool = True
    # The actual order of the structure shift and the displacement: MSS_FIRST | DISPLACEMENT_FIRST |
    # SIMULTANEOUS, or None when they are not both present. A+ must not assume MSS comes first; the
    # decision reads each step on its own bar, and this field records which order occurred.
    sequence_ordering: Optional[str] = None
