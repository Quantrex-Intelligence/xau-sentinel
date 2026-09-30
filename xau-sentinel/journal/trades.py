"""Trade CRUD, automatic market-context capture, event/alert logging, and journal analytics."""
import json
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd
from sqlalchemy import select, insert, update, func
from sqlalchemy.engine import Connection

import config
from journal.database import get_connection
from journal.schema import trades, journal_context, market_events, alerts


def session_now() -> datetime:
    """The ONE boundary for 'what date/time is it right now' from the
    journal's perspective (Stage 22, see docs/validation/ISSUE_LOG.md
    VAL-012) -- config.SESSION_TIMEZONE, the same convention
    ai/digest/service.py::_now() already uses for period-boundary math.
    Every trade_date/trade_time capture point and every "today" journal
    query must derive from this single function, never datetime.now()/
    datetime.now(timezone.utc)/a client clock directly, so writers and
    readers of trade_date/trade_time agree on the same calendar day."""
    return datetime.now(ZoneInfo(config.SESSION_TIMEZONE))

TRADE_FIELDS = [
    "trade_date", "trade_time", "symbol", "direction", "session", "entry", "stop_loss",
    "take_profit", "planned_rr", "setup", "market_regime", "notes", "screenshot_path",
]

CONTEXT_FIELDS = [
    "h4_bias", "h1_bias", "m15_bias", "m5_bias", "regime", "liquidity", "mss", "displacement", "session",
]

EXIT_FIELDS = [
    "exit_price", "result", "pnl", "r_multiple", "duration_minutes",
    "exit_reason", "rule_followed", "mistake", "exit_notes",
]


def create_trade(data: dict, context: dict, conn: Optional[Connection] = None) -> int:
    """Inserts a trade plus the market context captured automatically at the
    same moment, so nothing the system already knows has to be typed twice.

    With no `conn`, opens its own connection and commits. With a caller's
    `conn` it writes into that connection's open transaction and does NOT
    commit (Stage 23D, VAL-029) -- api/routes/journal.py::create_trade uses
    this to make the trade insert and its FundedNext snapshot insert one
    atomic unit: both commit together or neither is written."""
    if conn is None:
        with get_connection() as own_conn:
            trade_id = create_trade(data, context, conn=own_conn)
            own_conn.commit()
            return trade_id

    trade_row = {field: data.get(field) for field in TRADE_FIELDS}

    result = conn.execute(
        insert(trades).values(**trade_row, status="OPEN").returning(trades.c.id)
    )
    trade_id = result.scalar_one()

    context_row = {field: context.get(field) for field in CONTEXT_FIELDS}
    context_row["trade_id"] = trade_id
    conn.execute(insert(journal_context).values(**context_row))

    return trade_id


def close_trade(trade_id: int, exit_data: dict) -> bool:
    """Closes an OPEN trade. Returns False (writing nothing) when no OPEN
    trade with this id exists -- the `status = 'OPEN'` guard (Stage 23D,
    VAL-024) means a re-submitted close can never overwrite an already-
    closed trade's result/pnl/r_multiple, including a race where two closes
    pass the route's pre-check at the same time."""
    row = {field: exit_data.get(field) for field in EXIT_FIELDS}
    with get_connection() as conn:
        result = conn.execute(
            update(trades)
            .where(trades.c.id == trade_id, trades.c.status == "OPEN")
            .values(**row, status="CLOSED")
        )
        conn.commit()
        return result.rowcount == 1


def list_trades(filters: Optional[dict] = None) -> pd.DataFrame:
    query = (
        select(
            trades,
            journal_context.c.h4_bias, journal_context.c.h1_bias, journal_context.c.m15_bias,
            journal_context.c.m5_bias, journal_context.c.regime, journal_context.c.liquidity,
            journal_context.c.mss, journal_context.c.displacement,
        )
        .select_from(trades.outerjoin(journal_context, journal_context.c.trade_id == trades.c.id))
    )
    filters = filters or {}
    for column in ("session", "setup", "direction"):
        if filters.get(column):
            query = query.where(trades.c[column] == filters[column])
    if filters.get("regime"):
        query = query.where(trades.c.market_regime == filters["regime"])
    query = query.order_by(trades.c.trade_date.desc(), trades.c.trade_time.desc())

    with get_connection() as conn:
        return pd.read_sql_query(query, conn)


def get_trade(trade_id: int) -> Optional[dict]:
    query = (
        select(
            trades,
            journal_context.c.h4_bias, journal_context.c.h1_bias, journal_context.c.m15_bias,
            journal_context.c.m5_bias, journal_context.c.regime, journal_context.c.liquidity,
            journal_context.c.mss, journal_context.c.displacement,
        )
        .select_from(trades.outerjoin(journal_context, journal_context.c.trade_id == trades.c.id))
        .where(trades.c.id == trade_id)
    )
    with get_connection() as conn:
        row = conn.execute(query).mappings().fetchone()
        return dict(row) if row else None


def compute_analytics(df: pd.DataFrame) -> dict:
    closed = df[df["status"] == "CLOSED"] if "status" in df.columns else df.iloc[0:0]
    total = len(closed)

    if total == 0:
        return {"total_trades": 0, "wins": 0, "losses": 0, "breakeven": 0,
                "win_rate": 0.0, "total_r": 0.0, "avg_r": 0.0, "profit_factor": None}

    # Stage 23D, VAL-032: the API now only accepts WIN/LOSS/BE, but a row
    # written before that (or via the Streamlit form) may hold "win" or
    # " Loss ". Normalize case/whitespace here too so such a trade still
    # counts toward wins/losses/breakeven instead of deflating the win rate.
    result = closed["result"].map(lambda v: v.strip().upper() if isinstance(v, str) else "")

    wins = int((result == "WIN").sum())
    losses = int((result == "LOSS").sum())
    breakeven = int((result == "BE").sum())

    r_values = closed["r_multiple"].dropna()
    total_r = float(r_values.sum())
    avg_r = float(r_values.mean()) if len(r_values) else 0.0

    gross_win = float(closed.loc[result == "WIN", "r_multiple"].sum())
    gross_loss = float(-closed.loc[result == "LOSS", "r_multiple"].sum())
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else None

    win_rate = round(wins / total * 100, 1)

    return {
        "total_trades": total, "wins": wins, "losses": losses, "breakeven": breakeven,
        "win_rate": win_rate, "total_r": round(total_r, 2), "avg_r": round(avg_r, 2),
        "profit_factor": profit_factor,
    }


def log_event(event_type: str, description: str, timeframe: str = "",
              event_time: Optional[datetime] = None) -> None:
    """Dedupes against the database (not just the caller's in-memory session
    state) so the same discrete event — e.g. a liquidity sweep on a specific
    candle — isn't re-logged every time a new browser session starts."""
    event_time = event_time or datetime.now(timezone.utc)
    with get_connection() as conn:
        existing = conn.execute(
            select(market_events.c.id).where(
                market_events.c.event_time == event_time,
                market_events.c.event_type == event_type,
                market_events.c.description == description,
            ).limit(1)
        ).fetchone()
        if existing:
            return
        conn.execute(
            insert(market_events).values(
                event_time=event_time, event_type=event_type, description=description, timeframe=timeframe,
            )
        )
        conn.commit()


def log_alert(level: str, message: str, direction: str = "", details: Optional[dict] = None,
              alert_time: Optional[datetime] = None) -> None:
    alert_time = alert_time or datetime.now(timezone.utc)
    with get_connection() as conn:
        conn.execute(
            insert(alerts).values(
                alert_time=alert_time, level=level, direction=direction,
                message=message, details=json.dumps(details or {}),
            )
        )
        conn.commit()


def has_recent_alert(level: str, direction: str, dedup_key: str, lookback: int = 50) -> bool:
    """Checks whether an alert carrying this exact dedup_key (in its JSON
    `details` blob) already exists for this level/direction, so a repeated
    evaluation of the SAME candidate (e.g. the A+ strategy evaluator polled
    again before the underlying liquidity sweep has changed) never produces
    a duplicate alert. Reuses the existing `alerts` table/schema as-is — no
    migration — the same way `log_event`'s own (event_time, event_type,
    description) dedup already works for market events."""
    with get_connection() as conn:
        rows = conn.execute(
            select(alerts.c.details)
            .where(alerts.c.level == level, alerts.c.direction == direction)
            .order_by(alerts.c.id.desc())
            .limit(lookback)
        ).fetchall()
    for row in rows:
        try:
            details = json.loads(row[0] or "{}")
        except (TypeError, ValueError):
            continue
        if details.get("dedup_key") == dedup_key:
            return True
    return False


def recent_events(limit: int = 10) -> pd.DataFrame:
    query = select(market_events).order_by(market_events.c.event_time.desc()).limit(limit)
    with get_connection() as conn:
        return pd.read_sql_query(query, conn)


def today_r_total(today: Optional[str] = None) -> float:
    """Sums r_multiple across closed trades for the given date (default:
    today, in config.SESSION_TIMEZONE — see session_now(), Stage 22/
    VAL-012) — powers the Risk panel's "Today P/L" figure."""
    day = today or session_now().date().isoformat()
    with get_connection() as conn:
        row = conn.execute(
            select(func.coalesce(func.sum(trades.c.r_multiple), 0)).where(
                trades.c.status == "CLOSED", trades.c.trade_date == day,
            )
        ).fetchone()
        return round(float(row[0]), 2)


def recent_alerts(limit: int = 10) -> pd.DataFrame:
    query = select(alerts).order_by(alerts.c.alert_time.desc()).limit(limit)
    with get_connection() as conn:
        return pd.read_sql_query(query, conn)
