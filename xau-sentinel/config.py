"""Central configuration for XAU Sentinel, loaded from environment variables / .env."""
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent


def _env_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    return default if val is None else val.strip().lower() in ("1", "true", "yes", "on")


# --- Mode ---
MODE = os.getenv("MODE", "mock").strip().lower()  # "mock" or "live"

# --- MT5 connection ---
MT5_LOGIN = os.getenv("MT5_LOGIN", "").strip()
MT5_PASSWORD = os.getenv("MT5_PASSWORD", "").strip()
MT5_SERVER = os.getenv("MT5_SERVER", "").strip()
TRADING_SYMBOL = os.getenv("TRADING_SYMBOL", "XAUUSD").strip()

# --- Session / display ---
SESSION_TIMEZONE = os.getenv("SESSION_TIMEZONE", "UTC").strip()

# --- API ---
# DEP-006: FastAPI's /docs, /redoc and /openapi.json publish the full endpoint
# map (write routes included). On by default because local dev and the E2E
# readiness checks poll /docs; production should set API_DOCS_ENABLED=false.
API_DOCS_ENABLED = _env_bool("API_DOCS_ENABLED", True)
# DEP-001: a single shared-secret token for every route + the WebSocket.
# Blank (the default) means no auth at all — the local dev / test / E2E
# default, same graceful-degradation shape as AI_API_KEY below. Set it only
# once actually exposing this beyond 127.0.0.1.
API_AUTH_TOKEN = os.getenv("API_AUTH_TOKEN", "").strip()

# --- Database ---
DB_PATH = os.getenv("DB_PATH", "").strip() or str(BASE_DIR / "data" / "xau_sentinel.db")

# --- Analysis thresholds (configurable, kept deliberately simple) ---
SWING_LOOKBACK = int(os.getenv("SWING_LOOKBACK", 3))
DISPLACEMENT_ATR_MULT = float(os.getenv("DISPLACEMENT_ATR_MULT", 1.5))
LIQUIDITY_SWEEP_BUFFER_PIPS = float(os.getenv("LIQUIDITY_SWEEP_BUFFER_PIPS", 0.5))
EQUAL_LEVEL_TOLERANCE = float(os.getenv("EQUAL_LEVEL_TOLERANCE", 0.5))
ATR_PERIOD = int(os.getenv("ATR_PERIOD", 14))
HIGH_VOL_ATR_MULT = float(os.getenv("HIGH_VOL_ATR_MULT", 1.3))
LOW_VOL_ATR_MULT = float(os.getenv("LOW_VOL_ATR_MULT", 0.7))
RETRACEMENT_MIN_PCT = float(os.getenv("RETRACEMENT_MIN_PCT", 0.2))
RETRACEMENT_MAX_PCT = float(os.getenv("RETRACEMENT_MAX_PCT", 0.79))

# --- Session windows (UTC hours) ---
ASIAN_SESSION_START_UTC = int(os.getenv("ASIAN_SESSION_START_UTC", 0))
ASIAN_SESSION_END_UTC = int(os.getenv("ASIAN_SESSION_END_UTC", 6))
LONDON_SESSION_START_UTC = int(os.getenv("LONDON_SESSION_START_UTC", 7))
LONDON_SESSION_END_UTC = int(os.getenv("LONDON_SESSION_END_UTC", 12))
NY_SESSION_START_UTC = int(os.getenv("NY_SESSION_START_UTC", 12))
NY_SESSION_END_UTC = int(os.getenv("NY_SESSION_END_UTC", 20))

# --- Risk display only — this app never places or sizes trades ---
ACCOUNT_BALANCE = float(os.getenv("ACCOUNT_BALANCE", 50000))
RISK_PER_TRADE_PCT = float(os.getenv("RISK_PER_TRADE_PCT", 0.3))

# --- Data staleness (seconds since the last tick before the UI warns rather
# than silently keep showing an old price as if it were current) ---
DATA_STALE_SECONDS = int(os.getenv("DATA_STALE_SECONDS", 120))

# --- FundedNext risk monitor (Stage 2, read-only decision support) ---
# FundedNext's daily-loss reset happens at 00:00 "server time," which they
# describe only as GMT+2 in winter / GMT+3 during EU daylight saving (an
# EET/EEST pattern) without publishing an IANA zone name — configurable
# since it's a documented-but-not-precisely-named detail. See risk/rules.py.
FUNDEDNEXT_SERVER_TIMEZONE = os.getenv("FUNDEDNEXT_SERVER_TIMEZONE", "Europe/Nicosia").strip()
FUNDEDNEXT_WARNING_THRESHOLD_PCT = float(os.getenv("FUNDEDNEXT_WARNING_THRESHOLD_PCT", 0.5))
FUNDEDNEXT_CRITICAL_THRESHOLD_PCT = float(os.getenv("FUNDEDNEXT_CRITICAL_THRESHOLD_PCT", 0.8))
# OP-002 (docs/validation/OPERATIONAL_ISSUES.md): how far the connected MT5
# account's balance may diverge from ACCOUNT_BALANCE before compute_status()
# treats it as data it can't trust, rather than a real trading swing.
FUNDEDNEXT_BALANCE_MISMATCH_TOLERANCE_PCT = float(os.getenv("FUNDEDNEXT_BALANCE_MISMATCH_TOLERANCE_PCT", 0.5))


# --- AI Assistant (Stage 3) — analyst/explainer over the engine's own
# output, never a trading voice. See ai/README or ai/assistant.py. ---
AI_PROVIDER = os.getenv("AI_PROVIDER", "anthropic").strip().lower()  # "anthropic" | "mock"
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL", "claude-haiku-4-5-20251001").strip()
AI_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", 1024))


# --- Stage 4: A+ Strategy Evaluation ---
# Explicit, user-specified rules (locked spec, 2026) — never invented. See
# ai/strategy/rules.py. All four values trace directly to numbered items in
# the locked specification: sweep recency/expiry window (item 10), stop-loss
# buffer beyond the swept level (item 8), minimum reward:risk (item 9), and
# the FundedNext daily-loss-used gate (item 11).
AI_STRATEGY_SWEEP_WINDOW_MINUTES = int(os.getenv("AI_STRATEGY_SWEEP_WINDOW_MINUTES", 60))
AI_STRATEGY_SL_BUFFER = float(os.getenv("AI_STRATEGY_SL_BUFFER", 0.30))
AI_STRATEGY_MIN_RR = float(os.getenv("AI_STRATEGY_MIN_RR", 3.0))
AI_STRATEGY_FUNDEDNEXT_MAX_DAILY_LOSS_USED_PCT = float(
    os.getenv("AI_STRATEGY_FUNDEDNEXT_MAX_DAILY_LOSS_USED_PCT", 50.0)
)


# --- Stage 5: Strategy & Trading Knowledge RAG ---
# Local, dependency-free retrieval over the project's own documented rules
# (see ai/knowledge/). AI_EMBEDDING_PROVIDER is the swap point for a real
# dense-model backend later (Voyage/OpenAI/local sentence-transformers) —
# "local" never calls out, needs no key, and is fully deterministic.
AI_EMBEDDING_PROVIDER = os.getenv("AI_EMBEDDING_PROVIDER", "local").strip().lower()
AI_KNOWLEDGE_MIN_SIMILARITY = float(os.getenv("AI_KNOWLEDGE_MIN_SIMILARITY", 0.18))
AI_KNOWLEDGE_TOP_K = int(os.getenv("AI_KNOWLEDGE_TOP_K", 3))
AI_KNOWLEDGE_CHUNK_SIZE = int(os.getenv("AI_KNOWLEDGE_CHUNK_SIZE", 800))
AI_KNOWLEDGE_CHUNK_OVERLAP = int(os.getenv("AI_KNOWLEDGE_CHUNK_OVERLAP", 100))


# --- Stage 6: AI Tool Calling ---
# Caps how many LLM <-> tool round trips a single chat turn can take before
# a final answer is forced with no more tools offered — bounds latency/cost
# and guarantees the loop always terminates. See ai/assistant.py.
AI_TOOL_MAX_ROUNDS = int(os.getenv("AI_TOOL_MAX_ROUNDS", 4))


# --- Stage 7: Trading Memory ---
# Retrieval thresholds for the user-confirmed memory layer, separate from
# Stage 5's knowledge-base thresholds above (same shape, same reasoning —
# see ai/memory/retrieval.py).
AI_MEMORY_MIN_SIMILARITY = float(os.getenv("AI_MEMORY_MIN_SIMILARITY", 0.18))
AI_MEMORY_TOP_K = int(os.getenv("AI_MEMORY_TOP_K", 3))


# --- Stage 8: Historical Setup Similarity ---
# An explicit, documented weighted-feature heuristic (see ai/similarity/
# scoring.py) — NOT statistically derived or tuned against outcomes. H1 is
# weighted highest among the four structure timeframes because the
# project's own seeded knowledge doc already treats it as the primary
# signal (see ai/knowledge/seed_documents.py). Sums to 1.0; feel free to
# retune, but retuning does not make these "correct" weights, only
# different ones.
AI_SIMILARITY_WEIGHT_H1_STRUCTURE = float(os.getenv("AI_SIMILARITY_WEIGHT_H1_STRUCTURE", 0.12))
AI_SIMILARITY_WEIGHT_M5_STRUCTURE = float(os.getenv("AI_SIMILARITY_WEIGHT_M5_STRUCTURE", 0.08))
AI_SIMILARITY_WEIGHT_M15_STRUCTURE = float(os.getenv("AI_SIMILARITY_WEIGHT_M15_STRUCTURE", 0.05))
AI_SIMILARITY_WEIGHT_H4_STRUCTURE = float(os.getenv("AI_SIMILARITY_WEIGHT_H4_STRUCTURE", 0.05))
AI_SIMILARITY_WEIGHT_LIQUIDITY = float(os.getenv("AI_SIMILARITY_WEIGHT_LIQUIDITY", 0.20))
AI_SIMILARITY_WEIGHT_MSS = float(os.getenv("AI_SIMILARITY_WEIGHT_MSS", 0.15))
AI_SIMILARITY_WEIGHT_DISPLACEMENT = float(os.getenv("AI_SIMILARITY_WEIGHT_DISPLACEMENT", 0.15))
AI_SIMILARITY_WEIGHT_REGIME = float(os.getenv("AI_SIMILARITY_WEIGHT_REGIME", 0.10))
AI_SIMILARITY_WEIGHT_SESSION = float(os.getenv("AI_SIMILARITY_WEIGHT_SESSION", 0.05))
AI_SIMILARITY_WEIGHT_RR = float(os.getenv("AI_SIMILARITY_WEIGHT_RR", 0.05))
# R:R difference (in R units) that maps to 0 similarity for that one feature.
AI_SIMILARITY_RR_TOLERANCE = float(os.getenv("AI_SIMILARITY_RR_TOLERANCE", 3.0))
AI_SIMILARITY_DEFAULT_TOP_K = int(os.getenv("AI_SIMILARITY_DEFAULT_TOP_K", 5))
AI_SIMILARITY_DEFAULT_MIN_SIMILARITY = float(os.getenv("AI_SIMILARITY_DEFAULT_MIN_SIMILARITY", 0.5))


# --- Stage 9: Market Intelligence Layer ---
# One provider setting per category, each keyed the same way AI_PROVIDER/
# AI_EMBEDDING_PROVIDER already are. Stage 11 adds a real backend ("real",
# see ai/market_intelligence/providers/real.py) alongside "mock" — the
# default per category follows the app's own MODE (the same mock/live
# convention mt5/account.py already uses everywhere else), so MODE=mock
# (the safe, offline default) keeps Market Intelligence mock too, and
# MODE=live automatically tries real sources — still overridable
# individually via each MARKET_INTEL_*_PROVIDER env var regardless of MODE.
_MARKET_INTEL_DEFAULT_PROVIDER = "real" if MODE == "live" else "mock"
MARKET_INTEL_MACRO_PROVIDER = os.getenv("MARKET_INTEL_MACRO_PROVIDER", _MARKET_INTEL_DEFAULT_PROVIDER).strip().lower()
MARKET_INTEL_CROSS_ASSET_PROVIDER = os.getenv(
    "MARKET_INTEL_CROSS_ASSET_PROVIDER", _MARKET_INTEL_DEFAULT_PROVIDER
).strip().lower()
MARKET_INTEL_EVENTS_PROVIDER = os.getenv("MARKET_INTEL_EVENTS_PROVIDER", _MARKET_INTEL_DEFAULT_PROVIDER).strip().lower()
MARKET_INTEL_NEWS_PROVIDER = os.getenv("MARKET_INTEL_NEWS_PROVIDER", _MARKET_INTEL_DEFAULT_PROVIDER).strip().lower()
# News older than this is filtered out at context-assembly time — "do not
# store every article indefinitely."
MARKET_INTEL_NEWS_MAX_AGE_HOURS = float(os.getenv("MARKET_INTEL_NEWS_MAX_AGE_HOURS", 48))
MARKET_INTEL_NEWS_DEFAULT_LIMIT = int(os.getenv("MARKET_INTEL_NEWS_DEFAULT_LIMIT", 10))
MARKET_INTEL_EVENTS_DAYS_AHEAD = int(os.getenv("MARKET_INTEL_EVENTS_DAYS_AHEAD", 7))
MARKET_INTEL_EVENTS_DAYS_BACK = int(os.getenv("MARKET_INTEL_EVENTS_DAYS_BACK", 1))


# --- Stage 11: Real Free Market Intelligence Providers ---
# FRED (Federal Reserve Economic Data) is free but needs a self-service API
# key — https://fred.stlouisfed.org/docs/api/api_key.html. Left blank, the
# real macro/events providers degrade to data_available=False (an explicit,
# never-fabricated "unavailable"), never a crash — the app still boots and
# runs with no key configured, exactly as the spec requires. Yahoo Finance's
# public chart endpoint and the two RSS feeds need no key at all.
MARKET_INTEL_FRED_API_KEY = os.getenv("MARKET_INTEL_FRED_API_KEY", "").strip()
MARKET_INTEL_HTTP_TIMEOUT_SECONDS = float(os.getenv("MARKET_INTEL_HTTP_TIMEOUT_SECONDS", 8.0))
# Per-category cache TTLs — a real provider is never hit more often than
# this, no matter how often the UI polls or the A+ evidence builder runs.
MARKET_INTEL_CACHE_TTL_MACRO_SECONDS = int(os.getenv("MARKET_INTEL_CACHE_TTL_MACRO_SECONDS", 3600))
MARKET_INTEL_CACHE_TTL_EVENTS_SECONDS = int(os.getenv("MARKET_INTEL_CACHE_TTL_EVENTS_SECONDS", 600))
MARKET_INTEL_CACHE_TTL_NEWS_SECONDS = int(os.getenv("MARKET_INTEL_CACHE_TTL_NEWS_SECONDS", 600))
MARKET_INTEL_CACHE_TTL_CROSS_ASSET_SECONDS = int(os.getenv("MARKET_INTEL_CACHE_TTL_CROSS_ASSET_SECONDS", 120))
# A real snapshot older than this is classified STALE rather than LIVE in
# the UI — see ai/market_intelligence/models.py::classify_freshness().
MARKET_INTEL_STALE_AFTER_SECONDS = float(os.getenv("MARKET_INTEL_STALE_AFTER_SECONDS", 7200))

IS_MOCK = MODE == "mock"
IS_LIVE = MODE == "live"

# --- Real-Time Monitoring & In-App Alert Engine (Stage 13) — an
# application-level polling loop that watches the existing deterministic
# engines (setup state, A+ evaluator, FundedNext risk, Market Intelligence
# quality) for state transitions and turns them into typed, deduplicated,
# acknowledgeable alerts. See ai/monitoring/.
MONITORING_ENABLED = os.getenv("MONITORING_ENABLED", "true").strip().lower() == "true"
MONITORING_INTERVAL_SECONDS = int(os.getenv("MONITORING_INTERVAL_SECONDS", 20))
MONITORING_EVENT_WARNING_MINUTES = int(os.getenv("MONITORING_EVENT_WARNING_MINUTES", 30))
ALERT_RETENTION_DAYS = int(os.getenv("ALERT_RETENTION_DAYS", 30))

# --- Telegram Alert Delivery (Stage 14) — a downstream notification sink
# for Stage 13's already-decided monitoring alerts; never re-runs the
# deterministic engines. Disabled by default. Optional: left disabled/
# unconfigured, the app still boots and runs normally. See ai/notifications/.
TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "false").strip().lower() == "true"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_POLL_INTERVAL_SECONDS = int(os.getenv("TELEGRAM_POLL_INTERVAL_SECONDS", 5))
TELEGRAM_MAX_RETRIES = int(os.getenv("TELEGRAM_MAX_RETRIES", 3))
TELEGRAM_RETRY_BACKOFF_SECONDS = float(os.getenv("TELEGRAM_RETRY_BACKOFF_SECONDS", 2))
TELEGRAM_HTTP_TIMEOUT_SECONDS = float(os.getenv("TELEGRAM_HTTP_TIMEOUT_SECONDS", 8.0))
# "telegram" (default) or "mock" (offline, deterministic, no bot required —
# used by tests/E2E, mirrors AI_PROVIDER's mock/real convention).
NOTIFICATION_PROVIDER = os.getenv("NOTIFICATION_PROVIDER", "telegram").strip().lower()

# --- Trade Review & Behavioral Intelligence (Stage 16) — a recurring
# behavioral pattern is only reported across at least this many trades;
# below it, the summary explicitly states the sample is insufficient
# rather than inventing significance. See ai/trade_review/.
TRADE_REVIEW_MIN_PATTERN_SAMPLE = int(os.getenv("TRADE_REVIEW_MIN_PATTERN_SAMPLE", 3))

# --- Strategy Analytics (Stage 17) — a dimension breakdown row below this
# many closed trades is labeled INSUFFICIENT SAMPLE; the raw count is
# still shown, never hidden. See ai/strategy_analytics/.
STRATEGY_ANALYTICS_MIN_SAMPLE = int(os.getenv("STRATEGY_ANALYTICS_MIN_SAMPLE", 5))

# --- Periodic Trading Digest (Stage 18) — a scheduled weekly/monthly
# reporting layer over Stage 16/17's own computations. DIGEST_ENABLED is
# the master safe default (false); the weekly/monthly sub-flags gate each
# schedule independently once the master flag is on. See ai/digest/.
DIGEST_ENABLED = os.getenv("DIGEST_ENABLED", "false").strip().lower() == "true"
DIGEST_WEEKLY_ENABLED = os.getenv("DIGEST_WEEKLY_ENABLED", "false").strip().lower() == "true"
DIGEST_MONTHLY_ENABLED = os.getenv("DIGEST_MONTHLY_ENABLED", "false").strip().lower() == "true"
DIGEST_WEEKLY_DAY = os.getenv("DIGEST_WEEKLY_DAY", "MONDAY").strip().upper()
DIGEST_WEEKLY_TIME = os.getenv("DIGEST_WEEKLY_TIME", "09:00").strip()
DIGEST_MONTHLY_DAY = int(os.getenv("DIGEST_MONTHLY_DAY", 1))
DIGEST_MONTHLY_TIME = os.getenv("DIGEST_MONTHLY_TIME", "09:00").strip()
DIGEST_POLL_INTERVAL_SECONDS = int(os.getenv("DIGEST_POLL_INTERVAL_SECONDS", 300))
