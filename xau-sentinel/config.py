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


# --- AI Assistant (Stage 3) — analyst/explainer over the engine's own
# output, never a trading voice. See ai/README or ai/assistant.py. ---
AI_PROVIDER = os.getenv("AI_PROVIDER", "anthropic").strip().lower()  # "anthropic" | "mock"
AI_API_KEY = os.getenv("AI_API_KEY", "").strip()
AI_MODEL = os.getenv("AI_MODEL", "claude-haiku-4-5-20251001").strip()
AI_MAX_TOKENS = int(os.getenv("AI_MAX_TOKENS", 1024))

IS_MOCK = MODE == "mock"
IS_LIVE = MODE == "live"
