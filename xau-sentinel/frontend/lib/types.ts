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

/** Mirrors ai/knowledge/schemas.py's KnowledgeSourceOut (Stage 5) — a
 * retrieved reference document chunk, distinct from ContextSource above:
 * this is background documentation, never a live fact. */
export interface KnowledgeSource {
  source: string;
  category: string;
  version: string;
  title: string;
  similarity: number;
  excerpt: string;
}

export interface KnowledgeDocument {
  id: number;
  source: string;
  category: string;
  version: string;
  title: string;
  is_active: boolean;
  created_at: string;
}

/** Mirrors ai/tools/schemas.py's ToolUsageOut (Stage 6) — one read-only
 * tool the assistant actually called this turn, in call order. */
export interface ToolUsage {
  name: string;
  label: string;
  data_available: boolean;
  timestamp: string | null;
}

/** Mirrors api/routes/ai.py's ToolInfoOut — GET /api/ai/tools introspection,
 * never execution. */
export interface ToolInfo {
  name: string;
  label: string;
  description: string;
}

/** Mirrors ai/memory/models.py's MemoryCategory (Stage 7). */
export type MemoryCategory = "USER_PREFERENCE" | "STRATEGY_MEMORY" | "TRADE_LESSON" | "PATTERN_OBSERVATION";
export type MemoryStatus = "ACTIVE" | "ARCHIVED";

/** Mirrors ai/memory/schemas.py's MemoryRecordOut — a user-confirmed
 * memory record. `source` is always "user_confirmed"; the app never sets
 * or offers to set anything else. */
export interface MemoryRecord {
  id: number;
  category: MemoryCategory;
  content: string;
  source: string;
  status: MemoryStatus;
  created_at: string;
  updated_at: string;
  strategy_version: string | null;
}

export interface MemoryCreateInput {
  category: MemoryCategory;
  content: string;
  strategy_version?: string;
}

/** Mirrors ai/memory/schemas.py's MemoryUsedOut — one memory referenced for
 * a chat turn, distinct from KnowledgeSource (project docs) and ContextSource
 * (live deterministic facts): this is the user's own confirmed context. */
export interface MemoryUsage {
  id: number;
  category: MemoryCategory;
  excerpt: string;
  similarity: number;
  updated_at: string;
}

/** Mirrors ai/similarity/schemas.py (Stage 8) — deterministic, weighted
 * FEATURE similarity against historical journal trades. Never a win
 * probability or confidence score — no such field exists anywhere here. */
export interface SetupFeatures {
  direction: string | null;
  h4_structure: string | null;
  h1_structure: string | null;
  m15_structure: string | null;
  m5_structure: string | null;
  regime: string | null;
  liquidity_kind: string | null;
  mss_direction: string | null;
  displacement: string | null;
  session: string | null;
  planned_rr: number | null;
}

export interface SimilarityOutcome {
  status: "OPEN" | "CLOSED";
  result: "WIN" | "LOSS" | "BE" | null;
  r_multiple: number | null;
  pnl: number | null;
  duration_minutes: number | null;
  entry_date: string | null;
  entry_time: string | null;
}

export interface SimilarSetup {
  trade_id: number;
  similarity: number;
  entry_snapshot: SetupFeatures;
  outcome: SimilarityOutcome;
  matched_features: string[];
  different_features: string[];
}

export interface SimilarityResult {
  query_features: SetupFeatures;
  matches: SimilarSetup[];
  considered_count: number;
  excluded_count: number;
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
  /** Reference knowledge retrieved for this turn, alongside (never
   * replacing) `sources` above. Empty when nothing was relevant enough. */
  knowledge_used: KnowledgeSource[];
  /** Read-only tools the model actually called this turn, alongside (never
   * replacing) `sources`/`knowledge_used`. Empty when the answer needed no
   * tool call. */
  tools_used: ToolUsage[];
  /** User-confirmed trading memory referenced this turn, alongside (never
   * replacing) the above. Empty when nothing active was relevant enough. */
  memory_used: MemoryUsage[];
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

/** Mirrors ai/market_intelligence/schemas.py (Stage 9) — macro, gold
 * fundamentals, cross-asset, economic events, and news, all external and
 * time-stamped. Never authoritative over the deterministic engine, the A+
 * evaluation, or FundedNext risk facts. */
export interface MacroSnapshot {
  data_available: boolean;
  source: string;
  generated_at: string | null;
  fed_funds_rate: number | null;
  cpi_yoy: number | null;
  core_cpi_yoy: number | null;
  unemployment_rate: number | null;
  gdp_growth_yoy: number | null;
  us10y_yield: number | null;
  us2y_yield: number | null;
  reason: string | null;
}

export interface GoldFundamentals {
  data_available: boolean;
  source: string;
  generated_at: string | null;
  usd_strength_bias: string | null;
  real_yield_10y: number | null;
  central_bank_demand_trend: string | null;
  etf_flows_trend: string | null;
  reason: string | null;
}

export interface CrossAssetSnapshot {
  data_available: boolean;
  source: string;
  generated_at: string | null;
  dxy: number | null;
  us2y_yield: number | null;
  us10y_yield: number | null;
  real_yield_10y: number | null;
  vix: number | null;
  equity_index: number | null;
  silver_price: number | null;
  reason: string | null;
}

export interface EconomicEvent {
  name: string;
  category: string;
  importance: string;
  scheduled_at: string;
  source: string;
  actual: string | null;
  forecast: string | null;
  previous: string | null;
}

export interface NewsArticle {
  id: string;
  headline: string;
  source: string;
  published_at: string;
  retrieved_at: string;
  url: string | null;
  category: string | null;
  importance: string | null;
  assets: string[];
  summary: string | null;
}

export interface MarketIntelligenceContext {
  data_available: boolean;
  generated_at: string;
  macro: MacroSnapshot | null;
  gold_fundamentals: GoldFundamentals | null;
  cross_asset: CrossAssetSnapshot | null;
  events: EconomicEvent[];
  news: NewsArticle[];
  sources: string[];
}
