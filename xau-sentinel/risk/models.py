"""Data shapes for the FundedNext risk monitor. Pure data — no calculation
logic lives here (see fundednext.py) and nothing here talks to MT5 or the
database directly."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AccountType(str, Enum):
    STELLAR_2STEP = "stellar_2step"
    STELLAR_LITE = "stellar_lite"


class Phase(str, Enum):
    # "challenge" is the first evaluation phase; its stored value is kept
    # unchanged so existing saved settings and journal snapshots still load.
    CHALLENGE = "challenge"
    CHALLENGE_PHASE2 = "challenge_phase2"  # VAL-031: both Stellar accounts are two-step
    FUNDED = "funded"


class SafetyLevel(str, Enum):
    SAFE = "SAFE"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    BREACHED = "BREACHED"
    UNKNOWN = "UNKNOWN"


@dataclass
class RuleSet:
    """One account type's verified FundedNext rules. See risk/rules.py for
    sourcing — every field here traces to fundednext.com/general-rules or
    help.fundednext.com, never guessed."""
    account_type: AccountType
    label: str
    daily_loss_pct: float          # of initial balance; equity-based
    max_loss_pct: float            # of initial balance; static floor, equity-based
    profit_target_phase1_pct: float
    profit_target_phase2_pct: float
    min_trading_days: int          # each challenge phase (1 and 2); not the funded phase
    consistency_pct: Optional[float]  # None = not enforced by default (opt-in add-on)
    drawdown_type: str = "static"  # "static" | "trailing" — both current account types are static


@dataclass
class AccountSnapshot:
    """Raw account figures for one point in time — from MT5 (live) or the
    mock generator, never computed here."""
    balance: float
    equity: float
    source: str  # "mock" | "live"
    available: bool = True
    error: Optional[str] = None


@dataclass
class Violation:
    rule: str
    level: SafetyLevel
    message: str


@dataclass
class FundedNextStatus:
    account_type: AccountType
    phase: Phase
    mode: str  # "mock" | "live"
    data_available: bool

    balance: Optional[float] = None
    equity: Optional[float] = None

    day_start_balance: Optional[float] = None
    today_pnl: Optional[float] = None
    daily_loss_floor: Optional[float] = None
    daily_loss_remaining: Optional[float] = None
    daily_loss_used_pct: Optional[float] = None

    max_loss_floor: Optional[float] = None
    max_drawdown_remaining: Optional[float] = None
    max_drawdown_used_pct: Optional[float] = None

    profit_target: Optional[float] = None
    profit_target_pct: Optional[float] = None
    progress_to_target_pct: Optional[float] = None

    trading_days_completed: Optional[int] = None
    trading_days_required: Optional[int] = None

    consistency_enabled: bool = False
    consistency_limit_pct: Optional[float] = None
    largest_day_pct_of_profit: Optional[float] = None

    safety_level: SafetyLevel = SafetyLevel.UNKNOWN
    violations: list[Violation] = field(default_factory=list)
    reason: str = ""
