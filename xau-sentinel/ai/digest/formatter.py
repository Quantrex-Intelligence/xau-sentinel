"""Deterministic Telegram digest formatting (Stage 18) — never calls an
LLM, never computes anything; every value read here was already finalized
by ai/digest/service.py::build_digest(). Mirrors
ai/notifications/formatter.py's plain f-string-join style (its own local
helpers, not imported -- sibling AI packages in this project mirror this
shape rather than cross-importing private helpers).

Zero-count alignment/risk categories are omitted (keeps the message
concise for Telegram, matching the spec's own example, which likewise
only lists the non-zero categories). Never "better"/"worse"/"improving"/
"deteriorating" anywhere -- the previous-period line is plain counts.
"""
from datetime import date, timedelta

from ai.digest.models import DigestSummary, DigestType
from ai.trade_review.models import StrategyAlignment

_NO_PATTERNS_MESSAGE = "No recurring behavioral patterns detected."

_ALIGNMENT_LABELS = [
    (StrategyAlignment.ALIGNED, "Aligned"),
    (StrategyAlignment.PARTIALLY_ALIGNED, "Partial"),
    (StrategyAlignment.NOT_ALIGNED, "Not aligned"),
    (StrategyAlignment.UNKNOWN, "Unknown"),
]

_DEVIATION_LABELS = {
    "DIRECTION_DEVIATION": "Direction Deviation",
    "MISSED_CONFIRMATION": "Missed Confirmation",
    "MISSING_CONTEXT": "Missing Context",
    "OUTSIDE_STRATEGY": "Outside Strategy",
    "INSUFFICIENT_RR": "Insufficient R:R",
    "RISK_LIMIT_DEVIATION": "Risk Limit Deviation",
    "EARLY_ENTRY": "Early Entry",
    "LATE_ENTRY": "Late Entry",
    "SL_DEVIATION": "SL Deviation",
    "TP_DEVIATION": "TP Deviation",
    "INVALIDATED_SETUP_TRADED": "Invalidated Setup Traded",
}


def _signed(value: float) -> str:
    return f"{'+' if value >= 0 else ''}{value:.2f}"


def _format_period_range(digest_type: DigestType, start: date, end: date) -> str:
    """start/end are the half-open [start, end) bounds build_digest() uses
    internally -- end is the first day of the NEXT period, exclusive.
    display_end converts that back to the last real day of THIS period for
    a human-readable range."""
    display_end = end - timedelta(days=1)
    if digest_type == DigestType.MONTHLY:
        return f"{start:%B %Y}"
    if start.month == display_end.month:
        return f"{start:%b %d}–{display_end.day}"
    return f"{start:%b %d}–{display_end:%b %d}"


def _alignment_lines(counts) -> list:
    lines = []
    for alignment, label in _ALIGNMENT_LABELS:
        count = counts.get(alignment, 0)
        if count > 0:
            lines.append(f"{label}: {count}")
    return lines


def format_digest_telegram(summary: DigestSummary) -> str:
    overview = summary.overview
    kind = "Weekly" if summary.digest_type == DigestType.WEEKLY else "Monthly"

    lines = [
        f"\U0001F4CA XAU Sentinel — {kind} Digest", "",
        "Period",
        _format_period_range(summary.digest_type, summary.period_start, summary.period_end), "",
        "TRADING",
        f"{overview.total_trades} trades",
        f"{overview.wins}W · {overview.losses}L · {overview.breakeven}BE",
        f"{_signed(overview.total_r)}R",
        f"Avg R: {_signed(overview.avg_r)}",
        f"Win rate: {overview.win_rate}%", "",
        "STRATEGY",
    ]
    lines += _alignment_lines(overview.strategy_alignment_counts) or ["No closed trades this period."]
    lines += ["", "RISK"]
    lines += _alignment_lines(overview.risk_alignment_counts) or ["No closed trades this period."]
    lines += ["", "BEHAVIOR"]
    if summary.behavioral_patterns:
        for pattern in summary.behavioral_patterns:
            label = _DEVIATION_LABELS.get(pattern.deviation_type.value, pattern.deviation_type.value.replace("_", " ").title())
            lines.append(f"• {label} — {pattern.sample_count} occurrences")
    else:
        lines.append(_NO_PATTERNS_MESSAGE)

    if summary.previous_period is not None:
        prev = summary.previous_period
        lines += ["", "PREVIOUS PERIOD", f"{prev.previous_trade_count} trades · {_signed(prev.previous_total_r)}R"]

    return "\n".join(lines)
