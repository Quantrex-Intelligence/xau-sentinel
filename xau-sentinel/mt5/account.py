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

import numpy as np

import config
from mt5 import connection
from mt5.timeutil import server_now, server_timezone, to_utc
from risk.models import AccountSnapshot
from stable_seed import stable_seed

try:
    import MetaTrader5 as mt5
except ImportError:
    mt5 = None


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


def get_open_positions() -> Optional[List[dict]]:
    """Currently open positions — mock-labeled synthetic data in MODE=mock,
    real (strictly read-only — positions_get() only, never an
    order/close/modify call) in MODE=live. None when genuinely unavailable
    (MT5 not connected), never a fabricated value. New in Stage 6: this app
    has never read live positions before (Stage 2's risk monitor only reads
    balance/equity and closed-deal history)."""
    if config.IS_MOCK:
        return _mock_open_positions()

    if mt5 is None or not connection.is_connected():
        return None
    try:
        positions = mt5.positions_get(symbol=config.TRADING_SYMBOL)
        if positions is None:
            return []
        return [
            {
                "ticket": p.ticket, "symbol": p.symbol, "direction": "BUY" if p.type == 0 else "SELL",
                "volume": p.volume, "price_open": p.price_open, "price_current": p.price_current,
                "profit": p.profit, "sl": p.sl, "tp": p.tp,
            }
            for p in positions
        ]
    except Exception:  # noqa: BLE001 - any MT5 hiccup must degrade, never crash
        return None


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
        now_utc = datetime.now(timezone.utc)
        from_dt = now_utc - timedelta(days=days)
        # VAL-017: deal times are the broker server's wall-clock epoch (see
        # mt5/timeutil.py), which runs AHEAD of true UTC on a UTC+2/+3 server
        # like FundedNext's. A window ending at true-UTC "now" would drop the
        # last 2-3 hours of deals — exactly today's most recent closes, which
        # feed the daily-loss anchor. No deal can be in the future, so ending
        # the window a day ahead is safe under either epoch interpretation.
        to_dt = now_utc + timedelta(days=1)
        deals = mt5.history_deals_get(from_dt, to_dt)
        if deals is None:
            return []
        by_day: dict = {}
        tz = server_timezone()
        for d in deals:
            # Only actual trade deals count as realized trading P/L — a
            # deposit/withdrawal/other balance operation (DEAL_TYPE_BALANCE,
            # credit, etc.) must never be counted as a "profitable trading
            # day" (see docs/validation/ISSUE_LOG.md VAL-002/VAL-016).
            if d.type not in (mt5.DEAL_TYPE_BUY, mt5.DEAL_TYPE_SELL):
                continue
            local_date = to_utc(d.time).astimezone(tz).date()
            by_day[local_date] = by_day.get(local_date, 0.0) + _realized_pnl(d)
        return sorted(by_day.items())
    except Exception:  # noqa: BLE001
        return None


def _realized_pnl(deal) -> float:
    """VAL-016: the balance change a trade deal actually caused. MT5 debits
    commission, swap and fee from the balance alongside `profit` (commission
    is often charged on the opening deal, whose profit is 0), so leaving them
    out makes compute_status()'s day_start_balance = balance - realized P/L
    wrong by exactly those charges. Missing attributes count as 0."""
    return sum(float(getattr(deal, name, 0.0) or 0.0) for name in ("profit", "commission", "swap", "fee"))


# ---------------------------------------------------------------------------
# Mock data — deterministic, clearly labeled "mock", never presented as live.
# ---------------------------------------------------------------------------

def _mock_seed(salt: str) -> int:
    return stable_seed(salt, "xau-sentinel-fundednext-mock")


def _mock_account_snapshot() -> AccountSnapshot:
    today = server_now().date().isoformat()
    rng = np.random.default_rng(_mock_seed(f"balance-{today}"))
    initial = config.ACCOUNT_BALANCE
    realized_today = float(rng.normal(loc=initial * 0.002, scale=initial * 0.006))
    floating = float(rng.normal(loc=0, scale=initial * 0.003))
    balance = initial + realized_today
    equity = balance + floating
    return AccountSnapshot(balance=round(balance, 2), equity=round(equity, 2), source="mock")


def _mock_open_positions() -> List[dict]:
    """Deterministic per-day mock — usually empty (this app never places
    trades on the user's behalf), occasionally shows one synthetic open
    position so the tool/UI has something real to render in a demo."""
    today = server_now().date().isoformat()
    rng = np.random.default_rng(_mock_seed(f"positions-{today}"))
    if rng.random() >= 0.3:
        return []
    price = 2650.0 + float(rng.normal(0, 5))
    direction = "BUY" if rng.random() < 0.5 else "SELL"
    return [{
        "ticket": int(rng.integers(100000, 999999)), "symbol": config.TRADING_SYMBOL, "direction": direction,
        "volume": 0.1, "price_open": round(price, 2),
        "price_current": round(price + float(rng.normal(0, 2)), 2),
        "profit": round(float(rng.normal(0, 20)), 2), "sl": None, "tp": None,
    }]


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
