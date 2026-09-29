"""Cross-trade behavioral pattern aggregation (Stage 16) — deterministic,
no LLM. Runs ai.trade_review.rules over every CLOSED trade and reports
sample_count/total_relevant_trades/occurrence_rate per deviation type,
gated by config.TRADE_REVIEW_MIN_PATTERN_SAMPLE so a pattern is never
reported from a handful of trades. trades_with_loss is exposed as a
separately-labeled OBSERVED ASSOCIATION, never phrased as causation —
see _ASSOCIATION_NOTE below, reused verbatim on every pattern (the same
"reuse a fixed, reviewed safety string" convention
ai/strategy/evidence.py's _HISTORICAL_DESCRIPTIVE_NOTE already
established).
"""
from typing import Any, Dict, List

import config
from journal import trades as trades_repo
from risk.fundednext_journal import get_snapshot as get_fundednext_snapshot
from ai.trade_review import rules
from ai.trade_review.models import BehavioralPattern, DeviationType, Outcome, StrategyAlignment, TradeReviewSummary

_ASSOCIATION_NOTE = "Observed historical association, not evidence of causation."
_INSUFFICIENT_SAMPLE_NOTE = "Insufficient historical sample for a meaningful recurring-pattern conclusion."


def closed_trades() -> List[Dict[str, Any]]:
    """Public — also used directly by api/routes/trade_review.py's
    /patterns endpoint.

    `.astype(object)` before `.where()` is required: on a float64 column,
    `df.where(df.notnull(), None)` is a documented pandas no-op — pandas
    re-coerces the replacement back to NaN, since a float64 array cannot
    hold a Python None. That silently defeated every downstream `is None`
    check on planned_rr/r_multiple/duration_minutes (see
    docs/validation/ISSUE_LOG.md VAL-005) — a trade with no recorded
    planned_rr fell through rules.py's `if planned_rr is None: return
    UNKNOWN` into `NaN >= min_rr` (always False), misclassifying it as
    NOT_ALIGNED instead of the honest UNKNOWN. Casting to object dtype
    first lets None actually stick."""
    df = trades_repo.list_trades()
    records = df.astype(object).where(df.notnull(), None).to_dict(orient="records")
    return [r for r in records if r.get("status") == "CLOSED"]


def aggregate_patterns(trades: List[Dict[str, Any]]) -> List[BehavioralPattern]:
    total = len(trades)
    if total == 0:
        return []

    counts: Dict[DeviationType, int] = {}
    losses: Dict[DeviationType, int] = {}

    for trade in trades:
        snapshot = get_fundednext_snapshot(trade["id"])
        deviations = rules.detect_deviations(trade, snapshot)
        outcome = rules.classify_outcome(trade)
        seen_types = {d.type for d in deviations}
        for dtype in seen_types:
            counts[dtype] = counts.get(dtype, 0) + 1
            if outcome == Outcome.LOSS:
                losses[dtype] = losses.get(dtype, 0) + 1

    patterns = []
    for dtype, count in counts.items():
        if count < config.TRADE_REVIEW_MIN_PATTERN_SAMPLE:
            continue
        patterns.append(BehavioralPattern(
            deviation_type=dtype, sample_count=count, total_relevant_trades=total,
            occurrence_rate=round(count / total, 4) if total else None,
            trades_with_loss=losses.get(dtype, 0), note=_ASSOCIATION_NOTE,
        ))
    return sorted(patterns, key=lambda p: p.sample_count, reverse=True)


def build_summary() -> TradeReviewSummary:
    trades = closed_trades()

    aligned = partially = not_aligned = unknown = 0
    for trade in trades:
        setup = rules.classify_setup_alignment(trade)
        execution = rules.classify_execution_alignment(trade)
        strategy = rules.classify_strategy_alignment(setup, execution)
        if strategy == StrategyAlignment.ALIGNED:
            aligned += 1
        elif strategy == StrategyAlignment.PARTIALLY_ALIGNED:
            partially += 1
        elif strategy == StrategyAlignment.NOT_ALIGNED:
            not_aligned += 1
        else:
            unknown += 1

    patterns = aggregate_patterns(trades)
    note = None if patterns or len(trades) >= config.TRADE_REVIEW_MIN_PATTERN_SAMPLE else _INSUFFICIENT_SAMPLE_NOTE

    return TradeReviewSummary(
        trades_reviewed=len(trades), strategy_aligned=aligned, partially_aligned=partially,
        not_aligned=not_aligned, unknown=unknown, patterns=patterns, insufficient_sample_note=note,
    )
