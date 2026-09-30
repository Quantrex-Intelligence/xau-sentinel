"""Persists a FundedNext account/risk SNAPSHOT alongside each journal trade,
captured once at trade-creation time — never updated afterward, so a
historical trade's stored context can never drift as the live account
changes later.

Lives in its own table (fundednext_context), defined in journal/schema.py
alongside every other table (DEP-002) -- schema changes now go through an
Alembic migration, not an inline dedup script (see git history before
DEP-002 for the sqlite3-era CREATE TABLE IF NOT EXISTS + DELETE-dedup
version of this module: the dedup was only ever needed because that
pattern couldn't alter a live table, which Alembic doesn't have a problem
with, so it's gone).

One row per trade is structurally enforced (Stage 23D, VAL-030) by the
idx_fundednext_context_trade_id UNIQUE constraint on trade_id.
"""
import logging
from typing import Optional

from sqlalchemy import select, insert
from sqlalchemy.engine import Connection

from journal.database import get_connection
from journal.schema import fundednext_context
from risk.models import FundedNextStatus

logger = logging.getLogger(__name__)


def save_snapshot(trade_id: int, status: FundedNextStatus, rules_daily_loss_pct: Optional[float],
                   rules_max_loss_pct: Optional[float],
                   conn: Optional[Connection] = None) -> None:
    """Writes exactly one row per trade — an INSERT, never an UPDATE. There
    is deliberately no function anywhere in this module that mutates an
    existing row, so a trade's captured context cannot be overwritten by a
    later call, however the live account changes afterward. A second call
    for the same trade raises an IntegrityError via the UNIQUE constraint
    (Stage 23D, VAL-030).

    With no `conn`, opens its own connection and commits. With a caller's
    `conn` it writes into that open transaction and does NOT commit (Stage
    23D, VAL-029), so api/routes/journal.py can commit the trade and its
    snapshot atomically."""
    row = {
        "trade_id": trade_id,
        "data_available": status.data_available,
        "account_type": status.account_type.value,
        "phase": status.phase.value,
        "mode": status.mode,
        "balance": status.balance,
        "equity": status.equity,
        "today_pnl": status.today_pnl,
        "daily_loss_remaining": status.daily_loss_remaining,
        "daily_loss_used_pct": status.daily_loss_used_pct,
        "max_drawdown_remaining": status.max_drawdown_remaining,
        "max_drawdown_used_pct": status.max_drawdown_used_pct,
        "daily_loss_pct_rule": rules_daily_loss_pct,
        "max_loss_pct_rule": rules_max_loss_pct,
        "safety_level": status.safety_level.value,
        "reason": status.reason,
    }
    stmt = insert(fundednext_context).values(**row)
    if conn is not None:
        conn.execute(stmt)
        return
    with get_connection() as own_conn:
        own_conn.execute(stmt)
        own_conn.commit()


def get_snapshot(trade_id: int) -> Optional[dict]:
    """Returns captured_at as an ISO 8601 string -- the pre-DEP-002 shape
    callers (e.g. api/schemas.py's FundedNextContextOut.captured_at: str)
    already expect, even though the column is now a real TIMESTAMPTZ."""
    with get_connection() as conn:
        row = conn.execute(
            select(fundednext_context)
            .where(fundednext_context.c.trade_id == trade_id)
            .order_by(fundednext_context.c.id.desc())
            .limit(1)
        ).mappings().fetchone()
        if row is None:
            return None
        result = dict(row)
        result["captured_at"] = result["captured_at"].isoformat()
        return result
