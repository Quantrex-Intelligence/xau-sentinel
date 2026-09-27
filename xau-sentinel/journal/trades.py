"""Trade CRUD, automatic market-context capture, event/alert logging, and journal analytics."""
import json
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from journal.database import get_connection

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


def create_trade(data: dict, context: dict) -> int:
    """Inserts a trade plus the market context captured automatically at the
    same moment, so nothing the system already knows has to be typed twice."""
    trade_row = {field: data.get(field) for field in TRADE_FIELDS}
    context_row = {field: context.get(field) for field in CONTEXT_FIELDS}

    with get_connection() as conn:
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
        conn.commit()
        return trade_id


def close_trade(trade_id: int, exit_data: dict) -> None:
    row = {field: exit_data.get(field) for field in EXIT_FIELDS}
    row["trade_id"] = trade_id
    with get_connection() as conn:
        conn.execute(
            f"""UPDATE trades SET {', '.join(f'{f} = :{f}' for f in EXIT_FIELDS)}, status = 'CLOSED'
                WHERE id = :trade_id""",
            row,
        )
        conn.commit()


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

    wins = int((closed["result"] == "WIN").sum())
    losses = int((closed["result"] == "LOSS").sum())
    breakeven = int((closed["result"] == "BE").sum())

    r_values = closed["r_multiple"].dropna()
    total_r = float(r_values.sum())
    avg_r = float(r_values.mean()) if len(r_values) else 0.0

    gross_win = float(closed.loc[closed["result"] == "WIN", "r_multiple"].sum())
    gross_loss = float(-closed.loc[closed["result"] == "LOSS", "r_multiple"].sum())
    profit_factor = round(gross_win / gross_loss, 2) if gross_loss > 0 else None

    win_rate = round(wins / total * 100, 1)

    return {
        "total_trades": total, "wins": wins, "losses": losses, "breakeven": breakeven,
        "win_rate": win_rate, "total_r": round(total_r, 2), "avg_r": round(avg_r, 2),
        "profit_factor": profit_factor,
    }


def log_event(event_type: str, description: str, timeframe: str = "",
              event_time: Optional[datetime] = None) -> None:
    event_time = event_time or datetime.now(timezone.utc)
    with get_connection() as conn:
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


def recent_events(limit: int = 10) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(
            "SELECT * FROM market_events ORDER BY event_time DESC LIMIT ?", conn, params=(limit,)
        )


def recent_alerts(limit: int = 10) -> pd.DataFrame:
    with get_connection() as conn:
        return pd.read_sql_query(
            "SELECT * FROM alerts ORDER BY alert_time DESC LIMIT ?", conn, params=(limit,)
        )
