"""FundedNext risk calculation engine. Deterministic and explainable: every
number traces to a documented formula in risk/rules.py, every AccountSnapshot
comes from mt5/account.py (mock or live, never fabricated), and this module
never talks to MT5, the database, or the analysis engine directly — it only
combines numbers it's given. See spec section 9: this sits downstream of
market analysis / setup detection and never feeds back into them.
"""
import config
from mt5 import account as mt5_account
from risk.models import AccountType, FundedNextStatus, Phase, SafetyLevel, Violation
from risk.rules import ON_DEMAND_CONSISTENCY_PCT, get_rules


def compute_status(account_type: AccountType, phase: Phase, consistency_enabled: bool = False) -> FundedNextStatus:
    rules = get_rules(account_type)
    mode = "mock" if config.IS_MOCK else "live"
    initial_balance = config.ACCOUNT_BALANCE

    snapshot = mt5_account.get_account_snapshot()
    if not snapshot.available:
        return FundedNextStatus(
            account_type=account_type, phase=phase, mode=mode, data_available=False,
            safety_level=SafetyLevel.UNKNOWN,
            reason=snapshot.error or "Account data unavailable.",
        )

    # OP-002 (docs/validation/OPERATIONAL_ISSUES.md): every figure below is
    # computed relative to config.ACCOUNT_BALANCE, but nothing previously
    # checked that the connected account is even approximately that size —
    # a live check found a connected demo account 2x the configured balance
    # produced a silently nonsensical progress_to_target_pct (1250%). A 50%
    # tolerance is well outside any real trading swing on these accounts
    # (max loss/profit-target rules top out around 8-20%) but catches a
    # genuinely different account. Checked before any downstream math runs,
    # since day_start_balance/daily_loss_floor/max_loss_floor/
    # progress_to_target_pct all share this same initial_balance input.
    if abs(snapshot.balance - initial_balance) > initial_balance * config.FUNDEDNEXT_BALANCE_MISMATCH_TOLERANCE_PCT:
        return FundedNextStatus(
            account_type=account_type, phase=phase, mode=mode, data_available=False,
            safety_level=SafetyLevel.UNKNOWN,
            reason=(f"Connected account balance ({snapshot.balance:,.2f}) does not match the configured "
                    f"ACCOUNT_BALANCE ({initial_balance:,.2f}) — check the connected MT5 account or ACCOUNT_BALANCE."),
        )

    # Daily-loss anchor: derived from today's REALIZED P/L, not from
    # "whatever balance was first observed today" (day_tracker.py's old
    # approach — see docs/validation/ISSUE_LOG.md VAL-002. A trade closed
    # before the app's first check on a new day was silently absorbed into
    # that anchor, understating the actual daily loss used). If the
    # realized-P/L history can't be determined at all, this is
    # financial-safety-sensitive: fail toward an explicit UNKNOWN rather
    # than silently falling back to an anchor that might be wrong.
    today = mt5_account.server_now().date()
    history = mt5_account.get_daily_pnl_history(days=45)
    if history is None:
        return FundedNextStatus(
            account_type=account_type, phase=phase, mode=mode, data_available=False,
            safety_level=SafetyLevel.UNKNOWN,
            reason="Unable to determine today's realized P/L; the daily-loss anchor cannot be trusted.",
        )
    today_realized_pnl = next((pnl for d, pnl in history if d == today), 0.0)
    day_start_balance = snapshot.balance - today_realized_pnl

    daily_loss_amount = rules.daily_loss_pct * initial_balance
    daily_loss_floor = day_start_balance - daily_loss_amount
    daily_loss_remaining = snapshot.equity - daily_loss_floor
    daily_loss_used_pct = _used_pct(daily_loss_amount, daily_loss_remaining)

    max_loss_amount = rules.max_loss_pct * initial_balance
    max_loss_floor = initial_balance - max_loss_amount
    max_drawdown_remaining = snapshot.equity - max_loss_floor
    max_drawdown_used_pct = _used_pct(max_loss_amount, max_drawdown_remaining)

    today_pnl = snapshot.equity - day_start_balance

    # VAL-031: phase 2 has its own (lower) target — Stellar 2-Step 5%, Lite 4% —
    # not phase 1's 8%. The funded phase has none.
    profit_target_pct = {
        Phase.CHALLENGE: rules.profit_target_phase1_pct,
        Phase.CHALLENGE_PHASE2: rules.profit_target_phase2_pct,
    }.get(phase)
    profit_target = profit_target_pct * initial_balance if profit_target_pct else None
    progress_to_target_pct = (
        round((snapshot.equity - initial_balance) / profit_target * 100, 1)
        if profit_target and profit_target > 0 else None
    )

    trading_days_completed = len(history)
    trading_days_required = rules.min_trading_days if phase in _EVALUATION_PHASES else None

    largest_day_pct_of_profit = None
    if consistency_enabled and history:
        profitable_days = [pnl for _, pnl in history if pnl > 0]
        total_profit = sum(profitable_days)
        if total_profit > 0:
            largest_day_pct_of_profit = round(max(profitable_days) / total_profit * 100, 1)

    violations: list[Violation] = []
    safety_level = SafetyLevel.SAFE

    if daily_loss_remaining <= 0:
        safety_level = SafetyLevel.BREACHED
        violations.append(Violation(
            rule="Daily Loss Limit", level=SafetyLevel.BREACHED,
            message=f"Equity ({snapshot.equity:,.2f}) is at or below today's floor "
                    f"({daily_loss_floor:,.2f}) — daily loss limit breached.",
        ))
    elif daily_loss_used_pct >= config.FUNDEDNEXT_CRITICAL_THRESHOLD_PCT:
        safety_level = _escalate(safety_level, SafetyLevel.CRITICAL)
        violations.append(Violation(
            rule="Daily Loss Limit", level=SafetyLevel.CRITICAL,
            message=f"{daily_loss_used_pct * 100:.0f}% of today's permitted loss is used "
                    f"({daily_loss_remaining:,.2f} remaining before the daily floor).",
        ))
    elif daily_loss_used_pct >= config.FUNDEDNEXT_WARNING_THRESHOLD_PCT:
        safety_level = _escalate(safety_level, SafetyLevel.WARNING)
        violations.append(Violation(
            rule="Daily Loss Limit", level=SafetyLevel.WARNING,
            message=f"{daily_loss_used_pct * 100:.0f}% of today's permitted loss is used.",
        ))

    if max_drawdown_remaining <= 0:
        safety_level = SafetyLevel.BREACHED
        violations.append(Violation(
            rule="Maximum Loss Limit", level=SafetyLevel.BREACHED,
            message=f"Equity ({snapshot.equity:,.2f}) is at or below the static floor "
                    f"({max_loss_floor:,.2f}) — maximum loss limit breached.",
        ))
    elif max_drawdown_used_pct >= config.FUNDEDNEXT_CRITICAL_THRESHOLD_PCT:
        safety_level = _escalate(safety_level, SafetyLevel.CRITICAL)
        violations.append(Violation(
            rule="Maximum Loss Limit", level=SafetyLevel.CRITICAL,
            message=f"{max_drawdown_used_pct * 100:.0f}% of the maximum loss buffer is used "
                    f"({max_drawdown_remaining:,.2f} remaining before the static floor).",
        ))
    elif max_drawdown_used_pct >= config.FUNDEDNEXT_WARNING_THRESHOLD_PCT:
        safety_level = _escalate(safety_level, SafetyLevel.WARNING)
        violations.append(Violation(
            rule="Maximum Loss Limit", level=SafetyLevel.WARNING,
            message=f"{max_drawdown_used_pct * 100:.0f}% of the maximum loss buffer is used.",
        ))

    if consistency_enabled and largest_day_pct_of_profit is not None and largest_day_pct_of_profit > ON_DEMAND_CONSISTENCY_PCT * 100:
        violations.append(Violation(
            rule="Consistency Rule", level=SafetyLevel.WARNING,
            message=f"Largest single day is {largest_day_pct_of_profit:.0f}% of total profit "
                    f"(limit {ON_DEMAND_CONSISTENCY_PCT * 100:.0f}%) — On-Demand Rewards eligibility at risk.",
        ))
        safety_level = _escalate(safety_level, SafetyLevel.WARNING)

    reason = violations[0].message if violations else "All FundedNext limits within safe range."

    return FundedNextStatus(
        account_type=account_type, phase=phase, mode=mode, data_available=True,
        balance=snapshot.balance, equity=snapshot.equity,
        day_start_balance=day_start_balance, today_pnl=round(today_pnl, 2),
        daily_loss_floor=round(daily_loss_floor, 2), daily_loss_remaining=round(daily_loss_remaining, 2),
        daily_loss_used_pct=round(daily_loss_used_pct * 100, 1),
        max_loss_floor=round(max_loss_floor, 2), max_drawdown_remaining=round(max_drawdown_remaining, 2),
        max_drawdown_used_pct=round(max_drawdown_used_pct * 100, 1),
        profit_target=round(profit_target, 2) if profit_target else None,
        profit_target_pct=round(profit_target_pct * 100, 1) if profit_target_pct else None,
        progress_to_target_pct=progress_to_target_pct,
        trading_days_completed=trading_days_completed, trading_days_required=trading_days_required,
        consistency_enabled=consistency_enabled,
        consistency_limit_pct=round(ON_DEMAND_CONSISTENCY_PCT * 100, 1) if consistency_enabled else None,
        largest_day_pct_of_profit=largest_day_pct_of_profit,
        safety_level=safety_level, violations=violations, reason=reason,
    )


_EVALUATION_PHASES = (Phase.CHALLENGE, Phase.CHALLENGE_PHASE2)


def _used_pct(allowance: float, remaining: float) -> float:
    if allowance <= 0:
        return 0.0
    return max(0.0, (allowance - remaining) / allowance)


_LEVEL_SEVERITY = {
    SafetyLevel.UNKNOWN: -1, SafetyLevel.SAFE: 0, SafetyLevel.WARNING: 1,
    SafetyLevel.CRITICAL: 2, SafetyLevel.BREACHED: 3,
}


def _escalate(current: SafetyLevel, candidate: SafetyLevel) -> SafetyLevel:
    return candidate if _LEVEL_SEVERITY[candidate] > _LEVEL_SEVERITY[current] else current
