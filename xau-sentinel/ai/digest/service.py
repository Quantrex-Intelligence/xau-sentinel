"""Digest builder and scheduler (Stage 18). build_digest() is pure Python —
no DB writes, no HTTP, no LLM call; every number comes from
ai.strategy_analytics.metrics.compute_overview() and
ai.trade_review.patterns.aggregate_patterns(), called on a period-filtered
trade list. This module does not reimplement win-rate/R/alignment math —
see tests/test_digest_service.py's structural test.

run_digest_cycle()/run_forever() mirror ai/monitoring/engine.py's and
ai/notifications/delivery.py's own "synchronous testable core + thin async
wrapper" shape exactly.
"""
import asyncio
import calendar
from datetime import date, datetime, time, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import config
from ai.digest import store
from ai.digest.formatter import format_digest_telegram
from ai.digest.models import DigestSummary, DigestType, PeriodComparison
from ai.notifications.providers import get_notification_provider
from ai.notifications.providers.telegram import NotificationConfigError
from ai.strategy_analytics import metrics as strategy_metrics
from ai.trade_review import patterns

CHANNEL = "telegram"


def _now() -> datetime:
    return datetime.now(ZoneInfo(config.SESSION_TIMEZONE))


def _parse_time(value: str) -> time:
    return datetime.strptime(value.strip(), "%H:%M").time()


# ---------------------------------------------------------------------------
# Period boundaries
# ---------------------------------------------------------------------------

def compute_period_bounds(digest_type: DigestType, reference: date) -> Tuple[date, date]:
    """The period CONTAINING reference, as a half-open [start, end) interval
    -- end is the first day of the NEXT period (exclusive), not the last
    day of this one. Callers that want the last real day of the period
    should use `end - timedelta(days=1)` (see
    ai/digest/formatter.py::_format_period_range())."""
    if digest_type == DigestType.WEEKLY:
        start = reference - timedelta(days=reference.weekday())  # Monday
        end = start + timedelta(days=7)  # next Monday
    else:
        start = reference.replace(day=1)
        days_in_month = calendar.monthrange(start.year, start.month)[1]
        end = start + timedelta(days=days_in_month)  # 1st of next month
    return start, end


def _step_back_one_period(digest_type: DigestType, period_start: date) -> Tuple[date, date]:
    """The period immediately before the one starting at period_start."""
    day_before = period_start - timedelta(days=1)
    return compute_period_bounds(digest_type, day_before)


def completed_period_bounds(digest_type: DigestType, reference: date) -> Tuple[date, date]:
    """The most recently COMPLETED period as of `reference` (Stage 20 fix
    for VAL-004: the period CONTAINING reference -- e.g. "today" when the
    scheduler fires -- is still in progress and must never be reported as
    if it were done; this steps back to the one immediately before it).
    This is what build_digest() actually reports on."""
    current_start, _ = compute_period_bounds(digest_type, reference)
    return _step_back_one_period(digest_type, current_start)


def previous_period_bounds(digest_type: DigestType, period_start: date) -> Tuple[date, date]:
    """Given a reported period's own start, the period immediately before
    it -- used only for the "previous period" comparison section (one
    more step back from whatever period is being reported)."""
    return _step_back_one_period(digest_type, period_start)


def trades_in_period(trades: List[Dict[str, Any]], start: date, end: date) -> List[Dict[str, Any]]:
    """start/end are half-open: [start, end) -- end (the first day of the
    NEXT period) is excluded."""
    result = []
    for trade in trades:
        raw = trade.get("trade_date")
        try:
            trade_date = datetime.strptime(raw, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            continue  # missing/malformed trade_date -> excluded, never guessed into a period
        if start <= trade_date < end:
            result.append(trade)
    return result


# ---------------------------------------------------------------------------
# Deterministic digest
# ---------------------------------------------------------------------------

def build_digest(digest_type: DigestType, reference: Optional[date] = None) -> DigestSummary:
    reference = reference or _now().date()
    start, end = completed_period_bounds(digest_type, reference)

    all_closed = patterns.closed_trades()
    period_trades = trades_in_period(all_closed, start, end)

    overview = strategy_metrics.compute_overview(period_trades)
    behavioral_patterns = patterns.aggregate_patterns(period_trades)

    prev_start, prev_end = previous_period_bounds(digest_type, start)
    prev_trades = trades_in_period(all_closed, prev_start, prev_end)

    comparison = None
    if prev_trades:  # "where enough data exists" -- at least one closed trade last period
        prev_overview = strategy_metrics.compute_overview(prev_trades)
        comparison = PeriodComparison(
            current_trade_count=overview.total_trades, current_total_r=overview.total_r,
            current_avg_r=overview.avg_r, current_win_rate=overview.win_rate,
            current_strategy_alignment_counts=overview.strategy_alignment_counts,
            previous_trade_count=prev_overview.total_trades, previous_total_r=prev_overview.total_r,
            previous_avg_r=prev_overview.avg_r, previous_win_rate=prev_overview.win_rate,
            previous_strategy_alignment_counts=prev_overview.strategy_alignment_counts,
        )

    return DigestSummary(
        digest_type=digest_type, period_start=start, period_end=end,
        generated_at=datetime.now(timezone.utc).isoformat(),
        overview=overview, behavioral_patterns=behavioral_patterns, previous_period=comparison,
    )


# ---------------------------------------------------------------------------
# Sending (used by both the scheduler below and api/routes/digest.py)
# ---------------------------------------------------------------------------

def attempt_send(
    digest_type: DigestType, reference: Optional[date] = None,
) -> Tuple[DigestSummary, bool, bool, Optional[str]]:
    """Returns (summary, sent, already_sent, error). Never sends twice for
    the same (digest_type, period_start, period_end, channel) identity --
    store.was_sent() is checked before ever calling the provider."""
    summary = build_digest(digest_type, reference)

    if store.was_sent(digest_type.value, summary.period_start, summary.period_end, CHANNEL):
        return summary, False, True, None

    try:
        provider = get_notification_provider()
    except NotificationConfigError as exc:
        return summary, False, False, str(exc)

    result = provider.send(format_digest_telegram(summary))
    if result.success:
        store.record_sent(digest_type.value, summary.period_start, summary.period_end, CHANNEL)
        return summary, True, False, None
    return summary, False, False, result.error


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------

def should_send_now(digest_type: DigestType, now: datetime) -> bool:
    if not config.DIGEST_ENABLED:
        return False

    if digest_type == DigestType.WEEKLY:
        if not config.DIGEST_WEEKLY_ENABLED:
            return False
        if now.strftime("%A").upper() != config.DIGEST_WEEKLY_DAY:
            return False
        return now.time() >= _parse_time(config.DIGEST_WEEKLY_TIME)

    if not config.DIGEST_MONTHLY_ENABLED:
        return False
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    target_day = min(config.DIGEST_MONTHLY_DAY, days_in_month)  # clamp e.g. day=31 into a 30-day month
    if now.day != target_day:
        return False
    return now.time() >= _parse_time(config.DIGEST_MONTHLY_TIME)


def run_digest_cycle() -> None:
    now = _now()
    for digest_type in (DigestType.WEEKLY, DigestType.MONTHLY):
        if not should_send_now(digest_type, now):
            continue
        try:
            attempt_send(digest_type, reference=now.date())
        except Exception:  # noqa: BLE001 - one type's failure must never block the other
            pass


async def run_forever() -> None:
    while True:
        try:
            run_digest_cycle()
        except Exception:  # noqa: BLE001 - one bad cycle must never kill the loop
            pass
        await asyncio.sleep(config.DIGEST_POLL_INTERVAL_SECONDS)
