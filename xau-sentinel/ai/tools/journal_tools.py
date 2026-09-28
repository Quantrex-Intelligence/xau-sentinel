"""Read-only tool wrappers over journal.trades. search_journal is a NEW
capability, but the filtering happens here in the tool layer, over data
journal.trades.list_trades() already returns — journal/trades.py itself is
not touched, no new query capability is added to it."""
from datetime import datetime, timezone

import pandas as pd

from journal import trades as trades_repo
from ai.tools.registry import ToolSpec, register
from ai.tools.schemas import ToolResult

_EMPTY_SCHEMA = {"type": "object", "properties": {}}
_SEARCH_FIELDS = ("notes", "setup", "mistake", "exit_notes")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_records(df: pd.DataFrame) -> list:
    """Pandas leaves NaN in place of a missing numeric/text value —
    replaced with None so the result is ordinary, JSON-safe data."""
    return df.where(pd.notnull(df), None).to_dict(orient="records")


def get_trade(args: dict) -> ToolResult:
    trade_id = args.get("trade_id")
    if trade_id is None:
        return ToolResult(data_available=False, reason="trade_id is required.", source="journal.trades")
    trade = trades_repo.get_trade(int(trade_id))
    if trade is None:
        return ToolResult(data_available=False, reason=f"No trade with id {trade_id}.", source="journal.trades")
    return ToolResult(data_available=True, timestamp=_now(), source="journal.trades", data={"trade": trade})


def get_trade_history(args: dict) -> ToolResult:
    limit = int(args.get("limit") or 10)
    df = trades_repo.list_trades()
    if df.empty:
        return ToolResult(data_available=False, reason="No trades have been journaled yet.", source="journal.trades")
    return ToolResult(data_available=True, timestamp=_now(), source="journal.trades",
                       data={"trades": _clean_records(df.head(limit))})


def get_performance(_args: dict) -> ToolResult:
    df = trades_repo.list_trades()
    if df.empty:
        return ToolResult(data_available=False, reason="No trades have been journaled yet.", source="journal.trades")
    return ToolResult(data_available=True, timestamp=_now(), source="journal.trades",
                       data=trades_repo.compute_analytics(df))


def search_journal(args: dict) -> ToolResult:
    query = (args.get("query") or "").strip().lower()
    if not query:
        return ToolResult(data_available=False, reason="query is required.", source="journal.trades")
    df = trades_repo.list_trades()
    if df.empty:
        return ToolResult(data_available=False, reason="No trades have been journaled yet.", source="journal.trades")

    def _matches(row) -> bool:
        haystack = " ".join(str(row.get(f) or "") for f in _SEARCH_FIELDS).lower()
        return query in haystack

    matched = df[df.apply(_matches, axis=1)]
    return ToolResult(
        data_available=True, timestamp=_now(), source="journal.trades",
        data={"trades": _clean_records(matched.head(20)), "matched": len(matched)},
    )


register(ToolSpec("get_trade", "Trade Detail", "A specific journaled trade by id.",
                   {"type": "object", "properties": {"trade_id": {"type": "integer"}}, "required": ["trade_id"]},
                   get_trade))
register(ToolSpec("get_trade_history", "Trade History", "Recent journaled trades, newest first.",
                   {"type": "object", "properties": {"limit": {"type": "integer"}}}, get_trade_history))
register(ToolSpec("get_performance", "Performance Analytics",
                   "Win rate, total R, average R, and profit factor across closed trades.",
                   _EMPTY_SCHEMA, get_performance))
register(ToolSpec("search_journal", "Search Journal",
                   "Free-text search over trade notes, setup labels, and recorded mistakes.",
                   {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                   search_journal))
