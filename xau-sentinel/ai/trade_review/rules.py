"""Deterministic trade-review classifiers (Stage 16) — pure functions over
a trade's own historical, stored fields (journal.trades.get_trade()'s
joined dict + risk.fundednext_journal.get_snapshot()'s immutable
snapshot). No DB/HTTP/LLM calls here; no lookahead — every check reads
only what was captured AT TRADE CREATION, never today's live market or
account state.

Consistency rules mirror analysis/setup.py::detect_setup()'s own exact
definition of "does this bias/sweep/MSS/displacement support this
direction" — applied to a trade's stored values instead of live candles.
Not a new, invented definition of "aligned" (see the Stage 16 plan).

Field casing note: h1_bias/h4_bias/etc. are stored UPPERCASE (direct from
analysis/structure.py); mss/displacement are stored Title Case (via
api/routes/journal.py::create_trade()'s `.title()` call). Every comparison
below normalizes with .lower() first to be robust to both.
"""
from typing import Any, Dict, List, Optional

import config
from ai.similarity.features import _infer_liquidity_kind
from ai.trade_review.models import Deviation, DeviationType, Outcome, StrategyAlignment
from risk.models import SafetyLevel

_BUY_H1_STATES = {"bullish", "pullback"}
_SELL_H1_STATES = {"bearish", "pullback"}


def _lower(value: Optional[str]) -> Optional[str]:
    return value.strip().lower() if isinstance(value, str) and value.strip() else None


# ---------------------------------------------------------------------------
# Per-dimension consistency — None (not populated) is UNKNOWN, never assumed.
# ---------------------------------------------------------------------------

def _h1_bias_consistency(direction: Optional[str], h1_bias: Optional[str]) -> Optional[bool]:
    h1 = _lower(h1_bias)
    if h1 is None or direction is None:
        return None
    if direction == "BUY":
        return h1 in _BUY_H1_STATES
    if direction == "SELL":
        return h1 in _SELL_H1_STATES
    return None


def _liquidity_consistency(direction: Optional[str], liquidity_label: Optional[str]) -> Optional[bool]:
    kind = _infer_liquidity_kind(liquidity_label)
    if kind is None or direction is None:
        return None
    if direction == "BUY":
        return kind == "sweep_low"
    if direction == "SELL":
        return kind == "sweep_high"
    return None


def _mss_consistency(direction: Optional[str], mss: Optional[str]) -> Optional[bool]:
    value = _lower(mss)
    if value is None or direction is None:
        return None
    if direction == "BUY":
        return value == "bullish"
    if direction == "SELL":
        return value == "bearish"
    return None


def _displacement_consistency(direction: Optional[str], displacement: Optional[str]) -> Optional[bool]:
    value = _lower(displacement)
    if value is None or direction is None:
        return None
    if direction == "BUY":
        return value == "bullish"
    if direction == "SELL":
        return value == "bearish"
    return None


def dimension_consistencies(trade: Dict[str, Any]) -> Dict[str, Optional[bool]]:
    """Public — also used directly by ai/trade_review/engine.py to build
    rule_observations without recomputing the same checks twice."""
    direction = trade.get("direction")
    return {
        "h1_bias": _h1_bias_consistency(direction, trade.get("h1_bias")),
        "liquidity": _liquidity_consistency(direction, trade.get("liquidity")),
        "mss": _mss_consistency(direction, trade.get("mss")),
        "displacement": _displacement_consistency(direction, trade.get("displacement")),
    }


def _rollup(consistencies: Dict[str, Optional[bool]]) -> StrategyAlignment:
    values = list(consistencies.values())
    if any(v is False for v in values):
        return StrategyAlignment.NOT_ALIGNED
    populated = [v for v in values if v is not None]
    if not populated:
        return StrategyAlignment.UNKNOWN
    if len(populated) == len(values):
        return StrategyAlignment.ALIGNED
    return StrategyAlignment.PARTIALLY_ALIGNED


def classify_setup_alignment(trade: Dict[str, Any]) -> StrategyAlignment:
    return _rollup(dimension_consistencies(trade))


def classify_execution_alignment(trade: Dict[str, Any]) -> StrategyAlignment:
    planned_rr = trade.get("planned_rr")
    if planned_rr is None:
        return StrategyAlignment.UNKNOWN
    return StrategyAlignment.ALIGNED if planned_rr >= config.AI_STRATEGY_MIN_RR else StrategyAlignment.NOT_ALIGNED


_ALIGNMENT_SEVERITY = {
    StrategyAlignment.NOT_ALIGNED: 3, StrategyAlignment.PARTIALLY_ALIGNED: 2,
    StrategyAlignment.UNKNOWN: 1, StrategyAlignment.ALIGNED: 0,
}


def classify_strategy_alignment(setup: StrategyAlignment, execution: StrategyAlignment) -> StrategyAlignment:
    """The worse of the two — the full locked technical+R:R spec
    together. Risk is deliberately excluded (evaluated separately, see
    classify_risk_alignment()), matching how the A+ evaluator already
    treats the FundedNext gate as a distinct criterion from the technical
    checklist."""
    return max((setup, execution), key=lambda a: _ALIGNMENT_SEVERITY[a])


def classify_risk_alignment(fundednext_snapshot: Optional[Dict[str, Any]]) -> StrategyAlignment:
    if not fundednext_snapshot or not fundednext_snapshot.get("data_available"):
        return StrategyAlignment.UNKNOWN
    safety_level = fundednext_snapshot.get("safety_level")
    if safety_level == SafetyLevel.SAFE.value:
        return StrategyAlignment.ALIGNED
    if safety_level == SafetyLevel.WARNING.value:
        return StrategyAlignment.PARTIALLY_ALIGNED
    if safety_level in (SafetyLevel.CRITICAL.value, SafetyLevel.BREACHED.value):
        return StrategyAlignment.NOT_ALIGNED
    return StrategyAlignment.UNKNOWN


def classify_outcome(trade: Dict[str, Any]) -> Outcome:
    if trade.get("status") != "CLOSED":
        return Outcome.OPEN
    result = trade.get("result")
    if result == "WIN":
        return Outcome.WIN
    if result == "LOSS":
        return Outcome.LOSS
    if result == "BE":
        return Outcome.BREAKEVEN
    return Outcome.UNKNOWN


# ---------------------------------------------------------------------------
# Deviations — only emitted with real evidence; UNKNOWN never becomes a
# fabricated violation.
# ---------------------------------------------------------------------------

def detect_deviations(trade: Dict[str, Any], fundednext_snapshot: Optional[Dict[str, Any]]) -> List[Deviation]:
    deviations: List[Deviation] = []
    consistencies = dimension_consistencies(trade)
    has_context = trade.get("h1_bias") is not None or any(
        trade.get(f) is not None for f in ("liquidity", "mss", "displacement")
    )

    if not has_context:
        deviations.append(Deviation(
            DeviationType.MISSING_CONTEXT,
            "No market-context fields (H1 bias, liquidity, MSS, displacement) were captured for this trade.",
        ))
        # Nothing further can be evaluated without any context.
    else:
        if consistencies["h1_bias"] is False:
            deviations.append(Deviation(
                DeviationType.DIRECTION_DEVIATION,
                f"Recorded H1 bias ({trade.get('h1_bias')}) does not support the trade's "
                f"{trade.get('direction')} direction.",
            ))

        mss = trade.get("mss")
        liquidity = trade.get("liquidity")
        if mss is None and liquidity is not None:
            deviations.append(Deviation(
                DeviationType.MISSED_CONFIRMATION,
                "A liquidity sweep was recorded but no M5 MSS confirmation was captured.",
            ))
        elif consistencies["mss"] is False:
            deviations.append(Deviation(
                DeviationType.MISSED_CONFIRMATION,
                f"Recorded MSS ({mss}) does not support the trade's {trade.get('direction')} direction.",
            ))

        inconsistent_count = sum(1 for v in consistencies.values() if v is False)
        if inconsistent_count >= 2:
            deviations.append(Deviation(
                DeviationType.OUTSIDE_STRATEGY,
                f"{inconsistent_count} of 4 recorded technical conditions contradict the trade's "
                f"{trade.get('direction')} direction.",
            ))

    planned_rr = trade.get("planned_rr")
    if planned_rr is not None and planned_rr < config.AI_STRATEGY_MIN_RR:
        deviations.append(Deviation(
            DeviationType.INSUFFICIENT_RR,
            f"Planned R:R {planned_rr} is below the strategy's minimum {config.AI_STRATEGY_MIN_RR}.",
        ))

    if fundednext_snapshot and fundednext_snapshot.get("data_available"):
        safety_level = fundednext_snapshot.get("safety_level")
        if safety_level in (SafetyLevel.WARNING.value, SafetyLevel.CRITICAL.value, SafetyLevel.BREACHED.value):
            deviations.append(Deviation(
                DeviationType.RISK_LIMIT_DEVIATION,
                f"FundedNext safety level at entry was {safety_level}, not SAFE.",
            ))

    return deviations


def build_rule_observations(trade: Dict[str, Any], consistencies: Dict[str, Any]) -> List[str]:
    """Plain, factual statements of what was checked — distinct from
    `deviations` (which are only the violations); this lists every
    dimension's outcome, including the aligned/unknown ones."""
    labels = {"h1_bias": "H1 bias", "liquidity": "Liquidity sweep", "mss": "MSS", "displacement": "Displacement"}
    lines = []
    for key, label in labels.items():
        result = consistencies.get(key)
        if result is True:
            lines.append(f"{label}: consistent with {trade.get('direction')} direction.")
        elif result is False:
            lines.append(f"{label}: inconsistent with {trade.get('direction')} direction.")
        else:
            lines.append(f"{label}: not captured (unknown).")
    return lines
