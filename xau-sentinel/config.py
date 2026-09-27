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

IS_MOCK = MODE == "mock"
IS_LIVE = MODE == "live"
