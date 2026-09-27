"""Verified FundedNext CFD account rules — researched from official sources
on 2026-09-27, NOT guessed. This is the single place these numbers live;
nothing else in the codebase should hardcode a FundedNext percentage.

Sources:
- https://fundednext.com/general-rules (official CFD rules page)
- https://help.fundednext.com/en/articles/8394569-what-are-today-s-permitted-loss-limit-and-maximum-permitted-loss-limit-on-fundednext-cfd
- https://help.fundednext.com/en/articles/8394309-when-does-the-daily-loss-limit-reset-with-fundednext-cfd
- https://help.fundednext.com/en/articles/9430123-is-there-a-minimum-trading-day-and-profit-target-in-the-fundednext-account-of-the-stellar-2-step-model

Key mechanics confirmed from the sources above (apply to both account
types below):
- Daily loss limit and max loss limit are both measured against EQUITY
  (includes floating/unrealized P&L) — a breach can occur intraday on an
  open losing position, before it's closed.
- Max loss limit is a STATIC floor: floor = initial_balance * (1 - max_loss_pct).
  It never moves down; every dollar of profit only increases the buffer
  above it (it does not ratchet up like a trailing drawdown).
- Daily loss limit resets at 00:00 SERVER time. FundedNext's server runs
  EET/EEST (GMT+2 in winter, GMT+3 during EU daylight saving) — confirmed
  by name via multiple independent sources, though FundedNext does not
  publish an IANA timezone identifier, so this is configurable
  (config.FUNDEDNEXT_SERVER_TIMEZONE) rather than hardcoded as a fixed
  offset.
- CFD Stellar accounts (2-Step, 1-Step, Lite, Instant) have NO consistency
  rule by default in either phase — it exists only as part of the optional,
  separately-purchased "On-Demand Rewards" add-on (40% cap on any single
  day's share of total profit). Modeled here as an opt-in toggle,
  defaulting to disabled, never assumed active.
- Funded-phase minimum-trading-days / payout-cadence rules depend on which
  payout option (21-day / 3-day / on-demand) was selected at checkout —
  that choice isn't exposed through any data source this app has access
  to, so it is intentionally left unconfigured for the funded phase rather
  than guessed. Challenge-phase minimum trading days (5, both account
  types) IS a fixed evaluation requirement and is included.
"""
from risk.models import AccountType, RuleSet

RULES: dict[AccountType, RuleSet] = {
    AccountType.STELLAR_2STEP: RuleSet(
        account_type=AccountType.STELLAR_2STEP,
        label="Stellar 2-Step",
        daily_loss_pct=0.05,
        max_loss_pct=0.10,
        profit_target_phase1_pct=0.08,
        profit_target_phase2_pct=0.05,
        min_trading_days=5,
        consistency_pct=None,
        drawdown_type="static",
    ),
    AccountType.STELLAR_LITE: RuleSet(
        account_type=AccountType.STELLAR_LITE,
        label="Stellar Lite",
        daily_loss_pct=0.04,
        max_loss_pct=0.08,
        profit_target_phase1_pct=0.08,
        profit_target_phase2_pct=0.04,
        min_trading_days=5,
        consistency_pct=None,
        drawdown_type="static",
    ),
}

# The optional add-on's consistency threshold, applied only when the user
# explicitly enables it (see risk/settings_store.py) — never on by default.
ON_DEMAND_CONSISTENCY_PCT = 0.40


def get_rules(account_type: AccountType) -> RuleSet:
    return RULES[account_type]
