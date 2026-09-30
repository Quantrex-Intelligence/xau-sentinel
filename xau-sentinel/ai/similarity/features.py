"""Deterministic feature extraction for historical setup similarity.

extract_features_from_trade() is the literal no-look-ahead boundary: it
reads ONLY columns journal_context/trades capture AT TRADE CREATION (see
api/routes/journal.py::create_trade) — direction, h4_bias/h1_bias/m15_bias/
m5_bias, regime, liquidity, mss, displacement, session, planned_rr, entry,
stop_loss, take_profit. It never reads result, pnl, r_multiple, exit_price,
exit_reason, mistake, duration_minutes, or status — those are OUTCOME
fields, attached separately and only after scoring (see
ai/similarity/engine.py). This function's output is provably independent of
them (see tests/test_similarity_features.py).

extract_features_from_live_setup() builds the same shape from the CURRENT
candidate setup — api.snapshot.build_snapshot() + analysis.setup.detect_setup()'s
already-computed result, never re-run here.
"""
import math
from typing import Any, Optional

import pandas as pd

from ai.similarity.models import SetupFeatures


# DEP-014: a row read through pd.read_sql_query can carry float NaN instead
# of None for a NULL column (always for float columns, and for string
# columns too under pandas 3's default string dtype). NaN is truthy, so a
# bare `if not value` guard lets it through. Every trade-row value is
# normalized through these helpers instead.
def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    # pd.isna covers float NaN, numpy NaN, pd.NA and NaT; guard with
    # is_scalar so a list/array value is never mistaken for "missing".
    return bool(pd.api.types.is_scalar(value) and pd.isna(value))


def _optional_float(value: Any) -> Optional[float]:
    if _is_missing(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


# Every sweepable level name in analysis/liquidity.py contains "High" or
# "Low" (see SWEEPABLE_HIGH_LEVELS/SWEEPABLE_LOW_LEVELS), and the stored
# label is always "{level_name} swept" — so the kind is losslessly
# re-derivable from the label alone, not new information.
def _infer_liquidity_kind(label: Optional[str]) -> Optional[str]:
    if not isinstance(label, str) or not label:  # None, NaN, pd.NA, ""
        return None
    lowered = label.lower()
    if "low" in lowered:
        return "sweep_low"
    if "high" in lowered:
        return "sweep_high"
    return None


def _norm(value: Optional[str]) -> Optional[str]:
    return value.strip() if isinstance(value, str) and value.strip() else None


def extract_features_from_trade(trade_row: dict) -> SetupFeatures:
    return SetupFeatures(
        direction=_norm(trade_row.get("direction")),
        h4_structure=_norm(trade_row.get("h4_bias")),
        h1_structure=_norm(trade_row.get("h1_bias")),
        m15_structure=_norm(trade_row.get("m15_bias")),
        m5_structure=_norm(trade_row.get("m5_bias")),
        regime=_norm(trade_row.get("regime")) or _norm(trade_row.get("market_regime")),
        liquidity_kind=_infer_liquidity_kind(trade_row.get("liquidity")),
        mss_direction=_norm(trade_row.get("mss")),
        displacement=_norm(trade_row.get("displacement")),
        session=_norm(trade_row.get("session")),
        planned_rr=_optional_float(trade_row.get("planned_rr")),
    )


def extract_features_from_live_setup(snapshot, setup_result) -> SetupFeatures:
    structure = snapshot.structure or {}

    def _state(tf: str) -> Optional[str]:
        s = structure.get(tf)
        return s.state if s is not None else None

    liquidity_kind = None
    if snapshot.liquidity and snapshot.liquidity.sweeps:
        liquidity_kind = snapshot.liquidity.sweeps[-1].kind

    m5 = structure.get("M5")

    return SetupFeatures(
        direction=_norm(setup_result.direction),
        h4_structure=_state("H4"),
        h1_structure=_state("H1"),
        m15_structure=_state("M15"),
        m5_structure=_state("M5"),
        regime=_norm(snapshot.regime.regime) if snapshot.regime else None,
        liquidity_kind=liquidity_kind,
        mss_direction=_norm(m5.last_mss) if m5 is not None else None,
        displacement=_norm(snapshot.displacement),
        session=_norm(snapshot.session),
        planned_rr=setup_result.rr,
    )
