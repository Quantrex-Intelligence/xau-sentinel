"""Trade CRUD, automatic market-context capture, event/alert logging, and journal analytics."""
import json
import sqlite3
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import pandas as pd

import config
from journal.database import get_connection


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


def create_trade(data: dict, context: dict, conn: Optional[sqlite3.Connection] = None) -> int:
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
    context_row = {field: context.get(field) for field in CONTEXT_FIELDS}

    cur = conn.execute(
        f"""INSERT INTO trades ({', '.join(TRADE_FIELDS)}, status)
            VALUES ({', '.join(':' + f for f in TRADE_FIELDS)}, 'OPEN')""",
        trade_row,
    )
    trade_id = cur.lastrowid

    context_row["trade_id"] = trade_id
    conn.execute(
        f"""INSERT INTO journal_context (trade_id, {', '.join(CONTEXT_FIELDS)})
            VALUES (:trade_id, {', '.join(':' + f for f in CONTEXT_FIELDS)})""",
        context_row,
    )
    return trade_id


def close_trade(trade_id: int, exit_data: dict) -> bool:
    """Closes an OPEN trade. Returns False (writing nothing) when no OPEN
    trade with this id exists -- the `status = 'OPEN'` guard (Stage 23D,
    VAL-024) means a re-submitted close can never overwrite an already-
    closed trade's result/pnl/r_multiple, including a race where two closes
    pass the route's pre-check at the same time."""
    row = {field: exit_data.get(field) for field in EXIT_FIELDS}
    row["trade_id"] = trade_id
    with get_connection() as conn:
        cur = conn.execute(
            f"""UPDATE trades SET {', '.join(f'{f} = :{f}' for f in EXIT_FIELDS)}, status = 'CLOSED'
                WHERE id = :trade_id AND status = 'OPEN'""",
            row,
        )
        conn.commit()
        return cur.rowcount == 1


def list_trades(filters: Optional[dict] = None) -> pd.DataFrame:
    query = """SELECT t.*, jc.h4_bias, jc.h1_bias, jc.m15_bias, jc.m5_bias, jc.regime,
                      jc.liquidity, jc.mss, jc.displacement
               FROM trades t LEFT JOIN journal_context jc ON jc.trade_id = t.id
               WHERE 1=1"""
    params = {}
    filters = filters or {}
    for column in ("session", "setup", "direction"):
        if filters.get(column):
            query += f" AND t.{column} = :{column}"
            params[column] = filters[column]
    if filters.get("regime"):
        query += " AND t.market_regime = :regime"
        params["regime"] = filters["regime"]
    query += " ORDER BY t.trade_date DESC, t.trade_time DESC"

    with get_connection() as conn:
        return pd.read_sql_query(query, conn, params=params)


def get_trade(trade_id: int) -> Optional[dict]:
    with get_connection() as conn:
        row = conn.execute(
            """SELECT t.*, jc.h4_bias, jc.h1_bias, jc.m15_bias, jc.m5_bias, jc.regime,
                      jc.liquidity, jc.mss, jc.displacement
               FROM trades t LEFT JOIN journal_context jc ON jc.trade_id = t.id
               WHERE t.id = ?""",
            (trade_id,),
        ).fetchone()
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
            """SELECT 1 FROM market_events
               WHERE event_time = ? AND event_type = ? AND description = ? LIMIT 1""",
            (event_time.isoformat(), event_type, description),
        ).fetchone()
        if existing:
            return
        conn.execute(
            "INSERT INTO market_events (event_time, event_type, description, timeframe) VALUES (?, ?, ?, ?)",
            (event_time.isoformat(), event_type, description, timeframe),
        )
        conn.commit()


def log_alert(level: str, message: str, direction: str = "", details: Optional[dict] = None,
              alert_time: Optional[datetime] = None) -> None:
    alert_time = alert_time or datetime.now(timezone.utc)
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO alerts (alert_time, level, direction, message, details) VALUES (?, ?, ?, ?, ?)",
            (alert_time.isoformat(), level, direction, message, json.dumps(details or {})),
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
            "SELECT details FROM alerts WHERE level = ? AND direction = ? ORDER BY id DESC LIMIT ?",
            (level, direction, lookback),
        ).fetchall()
    for row in rows:
        try:
            details = json.loads(row["details"] or "{}")
        except (TypeError, ValueError):
            continue
        if details.get("dedup_key") == dedup_key:
            return True
    return False


def recent_events(limit: int = 10) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(
            "SELECT * FROM market_events ORDER BY event_time DESC LIMIT ?", conn, params=(limit,)
        )


def today_r_total(today: Optional[str] = None) -> float:
    """Sums r_multiple across closed trades for the given date (default:
    today, in config.SESSION_TIMEZONE — see session_now(), Stage 22/
    VAL-012) — powers the Risk panel's "Today P/L" figure."""
    day = today or session_now().date().isoformat()
    with get_connection() as conn:
        row = conn.execute(
            """SELECT COALESCE(SUM(r_multiple), 0) AS total FROM trades
               WHERE status = 'CLOSED' AND trade_date = ?""",
            (day,),
        ).fetchone()
        return round(float(row["total"]), 2)


def recent_alerts(limit: int = 10) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(
            "SELECT * FROM alerts ORDER BY alert_time DESC LIMIT ?", conn, params=(limit,)
        )
