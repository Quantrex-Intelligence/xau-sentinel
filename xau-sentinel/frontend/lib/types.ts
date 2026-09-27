/**
 * Hand-written to mirror api/schemas.py field-for-field. No trading logic
 * lives here — these are pure data shapes for what the FastAPI layer
 * already returns.
 */

export interface Candle {
  time: number; // unix seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface PriceInfo {
  price: number;
  bid: number;
  ask: number;
  spread: number;
  time: number;
  source: "mock" | "live";
  stale: boolean;
}

export interface ConnectionInfo {
  label: string;
  connected: boolean;
  mode: "mock" | "live";
}

export type StructureState = "BULLISH" | "BEARISH" | "RANGING" | "PULLBACK";

export interface SwingPoint {
  time: number;
  price: number;
  kind: "high" | "low";
  label: "HH" | "HL" | "LH" | "LL" | null;
}

export interface Structure {
  state: StructureState;
  last_bos: "bullish" | "bearish" | null;
  last_mss: "bullish" | "bearish" | null;
  reason: string;
  swings: SwingPoint[];
}

export type Timeframe = "H4" | "H1" | "M15" | "M5";

export interface Regime {
  regime: string;
  reason: string;
}

export interface LiquidityEvent {
  time: number | null;
  label: string;
  level_name: string;
  level_price: number;
  kind: "sweep_high" | "sweep_low" | "equal_high" | "equal_low";
}

export interface Liquidity {
  sweeps: LiquidityEvent[];
  equal_levels: LiquidityEvent[];
}

export type SetupState =
  | "NO SETUP"
  | "DEVELOPING"
  | "VALID"
  | "INVALIDATED";

/** analyze_setup's checklist values are normally boolean, but the
 * "no H1 bias yet" branch fills every step with the literal string
 * "WAITING" instead of false — a quirk of the frozen Stage 1 engine that
 * the UI must render identically to a `false` (see ui/dashboard.py). */
export type ChecklistValue = boolean | "WAITING";

export interface Setup {
  state: SetupState;
  direction: "BUY" | "SELL" | null;
  checklist: Record<string, ChecklistValue>;
  entry_zone: [number, number] | null;
  stop_loss: number | null;
  take_profit: number | null;
  rr: number | null;
  reason: string;
}

export interface Risk {
  balance: number;
  risk_per_trade_pct: number;
  today_r: number;
}

export interface MarketSnapshot {
  connection: ConnectionInfo;
  price: PriceInfo | null;
  structure: Partial<Record<Timeframe, Structure>>;
  regime: Regime | null;
  zones: Record<string, number>;
  liquidity: Liquidity;
  displacement: "bullish" | "bearish" | null;
  setup: Setup | null;
  risk: Risk;
  session: string | null;
  latest_m5_candle: Candle | null;
  data_error: string | null;
}

export interface FundedNextTradeSnapshot {
  data_available: boolean;
  account_type: FundedNextAccountType | null;
  phase: FundedNextPhase | null;
  mode: "mock" | "live" | null;
  balance: number | null;
  equity: number | null;
  today_pnl: number | null;
  daily_loss_remaining: number | null;
  daily_loss_used_pct: number | null;
  max_drawdown_remaining: number | null;
  max_drawdown_used_pct: number | null;
  daily_loss_pct_rule: number | null;
  max_loss_pct_rule: number | null;
  safety_level: SafetyLevel | null;
  reason: string | null;
  captured_at: string | null;
}

export interface Trade {
  id: number;
  trade_date: string;
  trade_time: string;
  symbol: string;
  direction: "BUY" | "SELL";
  session: string | null;
  entry: number;
  stop_loss: number;
  take_profit: number | null;
  planned_rr: number | null;
  setup: string | null;
  market_regime: string | null;
  notes: string | null;
  screenshot_path: string | null;
  exit_price: number | null;
  result: "WIN" | "LOSS" | "BE" | null;
  pnl: number | null;
  r_multiple: number | null;
  duration_minutes: number | null;
  exit_reason: string | null;
  rule_followed: string | null;
  mistake: string | null;
  exit_notes: string | null;
  status: "OPEN" | "CLOSED";
  created_at: string;
  h4_bias: string | null;
  h1_bias: string | null;
  m15_bias: string | null;
  m5_bias: string | null;
  regime: string | null;
  liquidity: string | null;
  mss: string | null;
  displacement: string | null;
  fundednext_context: FundedNextTradeSnapshot | null;
}

export interface TradeCreateInput {
  trade_date: string;
  trade_time: string;
  direction: "BUY" | "SELL";
  entry: number;
  stop_loss: number;
  take_profit?: number;
  planned_rr?: number;
  setup?: string;
  notes?: string;
}

export interface TradeCloseInput {
  exit_price: number;
  result: "WIN" | "LOSS" | "BE";
  pnl?: number;
  r_multiple?: number;
  duration_minutes?: number;
  exit_reason?: string;
  rule_followed?: string;
  mistake?: string;
  exit_notes?: string;
}

export interface Analytics {
  total_trades: number;
  wins: number;
  losses: number;
  breakeven: number;
  win_rate: number;
  total_r: number;
  avg_r: number;
  profit_factor: number | null;
}

export interface AlertItem {
  id: number;
  alert_time: string;
  level: string;
  direction: string | null;
  message: string;
  details: Record<string, unknown> | null;
}

export type FundedNextAccountType = "stellar_2step" | "stellar_lite";
export type FundedNextPhase = "challenge" | "funded";
export type SafetyLevel = "SAFE" | "WARNING" | "CRITICAL" | "BREACHED" | "UNKNOWN";

export interface FundedNextViolation {
  rule: string;
  level: SafetyLevel;
  message: string;
}

export interface FundedNextStatus {
  account_type: FundedNextAccountType;
  phase: FundedNextPhase;
  mode: "mock" | "live";
  data_available: boolean;

  balance: number | null;
  equity: number | null;

  day_start_balance: number | null;
  today_pnl: number | null;
  daily_loss_floor: number | null;
  daily_loss_remaining: number | null;
  daily_loss_used_pct: number | null;

  max_loss_floor: number | null;
  max_drawdown_remaining: number | null;
  max_drawdown_used_pct: number | null;

  profit_target: number | null;
  profit_target_pct: number | null;
  progress_to_target_pct: number | null;

  trading_days_completed: number | null;
  trading_days_required: number | null;

  consistency_enabled: boolean;
  consistency_limit_pct: number | null;
  largest_day_pct_of_profit: number | null;

  safety_level: SafetyLevel;
  violations: FundedNextViolation[];
  reason: string;
}

export interface FundedNextRuleSet {
  account_type: FundedNextAccountType;
  label: string;
  daily_loss_pct: number;
  max_loss_pct: number;
  profit_target_phase1_pct: number;
  profit_target_phase2_pct: number;
  min_trading_days: number;
  consistency_pct: number | null;
  drawdown_type: string;
}

export interface FundedNextSettings {
  account_type: FundedNextAccountType;
  phase: FundedNextPhase;
  consistency_enabled: boolean;
}

export interface Settings {
  mode: "mock" | "live";
  trading_symbol: string;
  session_timezone: string;
  account_balance: number;
  risk_per_trade_pct: number;
  data_stale_seconds: number;
  swing_lookback: number;
  displacement_atr_mult: number;
  liquidity_sweep_buffer_pips: number;
  equal_level_tolerance: number;
  atr_period: number;
  retracement_min_pct: number;
  retracement_max_pct: number;
}

export interface EventItem {
  id: number;
  event_time: string;
  event_type: string;
  description: string;
  timeframe: string | null;
}

/** Mirrors ai/schemas.py's AnswerCategory — how a statement relates to
 * ground truth. FACT/CALCULATION trace to a deterministic engine;
 * INTERPRETATION is the LLM's own reading; UNKNOWN means the data needed
 * to answer isn't available. */
export type AnswerCategory = "FACT" | "CALCULATION" | "INTERPRETATION" | "UNKNOWN";

/** One traceable input an AI answer was built from — the "Context used"
 * transparency panel renders this list directly. */
export interface ContextSource {
  label: string;
  category: AnswerCategory;
  available: boolean;
  detail: string | null;
}

export interface ChatRequest {
  message: string;
  conversation_id?: string;
  /** Subset of "market" | "risk" | "journal". Omit for the server's default. */
  context_scope?: string[];
  /** When set, replaces context_scope entirely — explain THIS trade using
   * only what was captured at entry. */
  trade_id?: number;
}

export interface ChatResponse {
  answer: string;
  conversation_id: string;
  context_used: string[];
  sources: ContextSource[];
  category: AnswerCategory;
  provider: string | null;
  model: string | null;
  created_at: string;
}

export interface AiConfig {
  configured: boolean;
  provider: string;
  model: string | null;
  reason: string | null;
}

/** Mirrors ai/strategy/schemas.py — the Stage 4 A+ strategy evaluation. */
export type StrategyRating = "A+" | "DEVELOPING" | "INVALID";
export type StrategyCriterionStatus = "passed" | "failed" | "unknown";

export interface StrategyCriterion {
  name: string;
  status: StrategyCriterionStatus;
  evidence: string;
  required: boolean;
}

export interface FundedNextGate {
  data_available: boolean;
  safety_level: string | null;
  daily_loss_used_pct: number | null;
  max_daily_loss_used_pct_allowed: number;
  reason: string | null;
}

export interface StrategyEvaluation {
  rating: StrategyRating;
  direction: "BUY" | "SELL" | null;
  criteria: StrategyCriterion[];
  context_evidence: string[];
  missing_conditions: string[];
  invalidation: string | null;
  entry: number | null;
  stop_loss: number | null;
  target: number | null;
  rr: number | null;
  fundednext: FundedNextGate;
  evaluated_at: string;
  candidate_sweep_time: string | null;
  llm_explanation: string | null;
  llm_provider: string | null;
  llm_model: string | null;
  llm_error: string | null;
}
