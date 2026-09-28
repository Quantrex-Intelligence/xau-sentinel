"""Read-only tool wrappers over risk.fundednext.compute_status() (Stage 2)
and mt5.account.get_open_positions() (new in Stage 6) — the same settings
resolution api/routes/fundednext.py already uses (risk.settings_store)."""
from datetime import datetime, timezone

from mt5 import account as mt5_account
from risk import settings_store
from risk.fundednext import compute_status
from risk.models import AccountType, Phase
from ai.tools.registry import ToolSpec, register
from ai.tools.schemas import ToolResult

_EMPTY_SCHEMA = {"type": "object", "properties": {}}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_risk_status(_args: dict) -> ToolResult:
    settings = settings_store.get_settings()
    status = compute_status(
        AccountType(settings["account_type"]), Phase(settings["phase"]),
        consistency_enabled=settings["consistency_enabled"],
    )
    if not status.data_available:
        return ToolResult(data_available=False, reason=status.reason, source="risk.fundednext")
    return ToolResult(
        data_available=True, timestamp=_now(), source="risk.fundednext",
        data={
            "account_type": status.account_type.value, "phase": status.phase.value, "mode": status.mode,
            "balance": status.balance, "equity": status.equity, "today_pnl": status.today_pnl,
            "daily_loss_remaining": status.daily_loss_remaining,
            "daily_loss_used_pct": status.daily_loss_used_pct,
            "max_drawdown_remaining": status.max_drawdown_remaining,
            "max_drawdown_used_pct": status.max_drawdown_used_pct,
            "safety_level": status.safety_level.value, "reason": status.reason,
            "violations": [{"rule": v.rule, "level": v.level.value, "message": v.message}
                            for v in status.violations],
        },
    )


def get_open_positions(_args: dict) -> ToolResult:
    positions = mt5_account.get_open_positions()
    if positions is None:
        return ToolResult(data_available=False, reason="Open position data unavailable (MT5 not connected).",
                           source="mt5.account")
    return ToolResult(data_available=True, timestamp=_now(), source="mt5.account", data={"positions": positions})


register(ToolSpec("get_risk_status", "FundedNext Risk Status",
                   "Current FundedNext account risk status and any active violations.",
                   _EMPTY_SCHEMA, get_risk_status))
register(ToolSpec("get_open_positions", "Open Positions",
                   "Currently open MT5 positions (read-only).", _EMPTY_SCHEMA, get_open_positions))
