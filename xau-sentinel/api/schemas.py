"""Pydantic response models. These mirror the existing engine dataclasses
field-for-field (analysis/structure.py, analysis/setup.py, analysis/regime.py,
analysis/liquidity.py) — they exist to give the API a typed, documented
contract, not to add or reshape any information the engine doesn't already
produce."""
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, ConfigDict


class CandleOut(BaseModel):
    time: int  # unix seconds — Lightweight Charts' native time format
    open: float
    high: float
    low: float
    close: float
    volume: float


class PriceInfoOut(BaseModel):
    price: float
    bid: float
    ask: float
    spread: float
    time: int
    source: str  # "mock" | "live"
    stale: bool


class ConnectionOut(BaseModel):
    label: str
    connected: bool
    mode: str  # "mock" | "live"


class SwingPointOut(BaseModel):
    time: int
    price: float
    kind: str  # "high" | "low"
    label: Optional[str] = None  # "HH" | "HL" | "LH" | "LL"


class StructureOut(BaseModel):
    state: str
    last_bos: Optional[str] = None
    last_mss: Optional[str] = None
    reason: str
    swings: List[SwingPointOut] = []


class RegimeOut(BaseModel):
    regime: str
    reason: str


class LiquidityEventOut(BaseModel):
    time: Optional[int] = None
    label: str
    level_name: str
    level_price: float
    kind: str


class LiquidityOut(BaseModel):
    sweeps: List[LiquidityEventOut]
    equal_levels: List[LiquidityEventOut]


class SetupOut(BaseModel):
    state: str
    direction: Optional[str] = None
    # analysis.setup.detect_setup's NO-SETUP-without-H1-bias branch fills the
    # checklist with the literal string "WAITING" for every step instead of
    # False — a quirk of the frozen Stage 1 engine (ui/dashboard.py already
    # treats "anything that isn't True" as WAITING), so this stays a union
    # rather than "fixing" the engine's output shape.
    checklist: Dict[str, Union[bool, str]]
    entry_zone: Optional[Tuple[float, float]] = None
    stop_loss: Optional[float] = None
    take_profit: Optional[float] = None
    rr: Optional[float] = None
    reason: str


class RiskOut(BaseModel):
    balance: float
    risk_per_trade_pct: float
    today_r: float


class MarketSnapshotOut(BaseModel):
    """The single aggregate assembled by api/snapshot.py — used by both
    GET /api/market/analysis and every WS /ws/market tick."""
    connection: ConnectionOut
    price: Optional[PriceInfoOut] = None
    structure: Dict[str, StructureOut]  # keys: H4, H1, M15, M5
    regime: Optional[RegimeOut] = None
    zones: Dict[str, float]
    liquidity: LiquidityOut
    displacement: Optional[str] = None
    setup: Optional[SetupOut] = None
    risk: RiskOut
    session: Optional[str] = None
    latest_m5_candle: Optional[CandleOut] = None
    data_error: Optional[str] = None


class TradeCreateIn(BaseModel):
    trade_date: str
    trade_time: str
    direction: str
    entry: float
    stop_loss: float
    take_profit: Optional[float] = None
    planned_rr: Optional[float] = None
    setup: Optional[str] = None
    notes: Optional[str] = None


class TradeCloseIn(BaseModel):
    exit_price: float
    result: str  # "WIN" | "LOSS" | "BE"
    pnl: Optional[float] = None
    r_multiple: Optional[float] = None
    duration_minutes: Optional[float] = None
    exit_reason: Optional[str] = None
    rule_followed: Optional[str] = None
    mistake: Optional[str] = None
    exit_notes: Optional[str] = None


class TradeOut(BaseModel):
    """Deliberately permissive (extra="allow"): trades.list_trades()/get_trade()
    already return every DB column plus the joined journal_context columns —
    duplicating that column list here would be exactly the kind of duplicate
    business knowledge this migration is meant to avoid."""
    model_config = ConfigDict(extra="allow")

    id: int


class AnalyticsOut(BaseModel):
    total_trades: int
    wins: int
    losses: int
    breakeven: int
    win_rate: float
    total_r: float
    avg_r: float
    profit_factor: Optional[float] = None


class AlertOut(BaseModel):
    id: int
    alert_time: str
    level: str
    direction: Optional[str] = None
    message: str
    details: Optional[Any] = None


class FundedNextViolationOut(BaseModel):
    rule: str
    level: str
    message: str


class FundedNextStatusOut(BaseModel):
    account_type: str
    phase: str
    mode: str
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

    safety_level: str
    violations: List[FundedNextViolationOut] = []
    reason: str


class FundedNextRuleSetOut(BaseModel):
    account_type: str
    label: str
    daily_loss_pct: float
    max_loss_pct: float
    profit_target_phase1_pct: float
    profit_target_phase2_pct: float
    min_trading_days: int
    consistency_pct: Optional[float] = None
    drawdown_type: str


class FundedNextSettingsOut(BaseModel):
    account_type: str
    phase: str
    consistency_enabled: bool


class FundedNextSettingsIn(BaseModel):
    account_type: Optional[str] = None
    phase: Optional[str] = None
    consistency_enabled: Optional[bool] = None


class SettingsOut(BaseModel):
    mode: str
    trading_symbol: str
    session_timezone: str
    account_balance: float
    risk_per_trade_pct: float
    data_stale_seconds: int
    swing_lookback: int
    displacement_atr_mult: float
    liquidity_sweep_buffer_pips: float
    equal_level_tolerance: float
    atr_period: int
    retracement_min_pct: float
    retracement_max_pct: float


class EventOut(BaseModel):
    id: int
    event_time: str
    event_type: str
    description: str
    timeframe: Optional[str] = None
