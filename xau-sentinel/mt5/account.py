"""Read-only MT5 account info + closed-trade history for the FundedNext risk
monitor. A NEW file, not an edit to the frozen mt5/connection.py or
mt5/market_data.py — reuses their existing connection state (mt5.connection)
rather than duplicating it. Like market_data.py, degrades to clearly-labeled
mock data in MODE=mock and to an explicit "unavailable" state (never a
fabricated value) whenever MT5 isn't actually connected.

Only reads: account_info() and history_deals_get(). Never calls an
order-placing, closing, or modifying function.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo

import numpy as np

import config
from mt5 import connection
from risk.models import AccountSnapshot

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None


def server_timezone() -> ZoneInfo:
    return ZoneInfo(config.FUNDEDNEXT_SERVER_TIMEZONE)


def server_now() -> datetime:
    return datetime.now(server_timezone())


def get_account_snapshot() -> AccountSnapshot:
    """Current balance/equity — mock in MODE=mock, real account_info() in
    MODE=live, or an explicit unavailable state, never a fabricated value."""
    if config.IS_MOCK:
        return _mock_account_snapshot()

    if mt5 is None or not connection.is_connected():
        return AccountSnapshot(balance=0.0, equity=0.0, source="live", available=False,
                                error="MT5 not connected")
    try:
        info = mt5.account_info()
        if info is None:
            return AccountSnapshot(balance=0.0, equity=0.0, source="live", available=False,
                                    error="account_info() returned no data")
        return AccountSnapshot(balance=float(info.balance), equity=float(info.equity), source="live")
    except Exception as exc:  # noqa: BLE001 - any MT5 hiccup must degrade, never crash
        return AccountSnapshot(balance=0.0, equity=0.0, source="live", available=False, error=str(exc))


def get_daily_pnl_history(days: int = 10) -> Optional[List[tuple]]:
    """Returns [(server_local_date, realized_pnl), ...] for the last `days`
    calendar days (server time), oldest first — used for min-trading-days
    and the optional consistency-rule check. None when genuinely
    unavailable (never fabricated in live mode)."""
    if config.IS_MOCK:
        return _mock_daily_pnl_history(days)

    if mt5 is None or not connection.is_connected():
        return None
    try:
        to_dt = datetime.now(timezone.utc)
        from_dt = to_dt - timedelta(days=days)
        deals = mt5.history_deals_get(from_dt, to_dt)
        if deals is None:
            return []
        by_day: dict = {}
        tz = server_timezone()
        for d in deals:
            local_date = datetime.fromtimestamp(d.time, tz=timezone.utc).astimezone(tz).date()
            by_day[local_date] = by_day.get(local_date, 0.0) + float(d.profit)
        return sorted(by_day.items())
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------------------
# Mock data — deterministic, clearly labeled "mock", never presented as live.
# ---------------------------------------------------------------------------

def _mock_seed(salt: str) -> int:
    return abs(hash((salt, "xau-sentinel-fundednext-mock"))) % (2**32)


def _mock_account_snapshot() -> AccountSnapshot:
    today = server_now().date().isoformat()
    rng = np.random.default_rng(_mock_seed(f"balance-{today}"))
    initial = config.ACCOUNT_BALANCE
    realized_today = float(rng.normal(loc=initial * 0.002, scale=initial * 0.006))
    floating = float(rng.normal(loc=0, scale=initial * 0.003))
    balance = initial + realized_today
    equity = balance + floating
    return AccountSnapshot(balance=round(balance, 2), equity=round(equity, 2), source="mock")


def _mock_daily_pnl_history(days: int) -> List[tuple]:
    initial = config.ACCOUNT_BALANCE
    today = server_now().date()
    history = []
    for i in range(days, 0, -1):
        day = today - timedelta(days=i)
        rng = np.random.default_rng(_mock_seed(f"day-{day.isoformat()}"))
        # ~70% of days have a trade; deterministic per calendar day.
        if rng.random() < 0.7:
            pnl = float(rng.normal(loc=initial * 0.003, scale=initial * 0.01))
            history.append((day, round(pnl, 2)))
    return history
