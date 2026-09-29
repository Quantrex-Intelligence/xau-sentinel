"""Shared fixtures and synthetic-candle helpers for the XAU Sentinel test suite."""
from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

import config


def make_candles(rows, tf_minutes=5, start=None):
    """Builds a deterministic OHLCV DataFrame from a list of
    (open, high, low, close) or (open, high, low, close, volume) tuples,
    oldest first, matching the [time, open, high, low, close, volume] shape
    that mt5.market_data.get_candles returns."""
    start = start or datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)  # a Monday
    times = [start + timedelta(minutes=tf_minutes * i) for i in range(len(rows))]

    opens, highs, lows, closes, volumes = [], [], [], [], []
    for row in rows:
        if len(row) == 5:
            o, h, l, c, v = row
        else:
            o, h, l, c = row
            v = 100
        opens.append(o)
        highs.append(h)
        lows.append(l)
        closes.append(c)
        volumes.append(v)

    return pd.DataFrame({
        "time": pd.to_datetime(times, utc=True),
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
    })


def flat_candles(n, price=100.0, tf_minutes=5, start=None, noise=0.05):
    """n small-bodied candles oscillating narrowly around `price` — a
    deterministic stand-in for a quiet/ranging market."""
    rows = []
    for i in range(n):
        wig = noise if i % 2 == 0 else -noise
        o = price + wig
        c = price - wig
        h = max(o, c) + noise
        l = min(o, c) - noise
        rows.append((o, h, l, c))
    return make_candles(rows, tf_minutes=tf_minutes, start=start)


@pytest.fixture(autouse=True)
def _default_thresholds(monkeypatch):
    """Pins analysis thresholds to the shipped .env.example defaults so tests
    don't depend on whatever a developer's local .env happens to contain."""
    monkeypatch.setattr(config, "SWING_LOOKBACK", 3)
    monkeypatch.setattr(config, "DISPLACEMENT_ATR_MULT", 1.5)
    monkeypatch.setattr(config, "LIQUIDITY_SWEEP_BUFFER_PIPS", 0.5)
    monkeypatch.setattr(config, "EQUAL_LEVEL_TOLERANCE", 0.5)
    monkeypatch.setattr(config, "ATR_PERIOD", 14)
    monkeypatch.setattr(config, "HIGH_VOL_ATR_MULT", 1.3)
    monkeypatch.setattr(config, "LOW_VOL_ATR_MULT", 0.7)
    monkeypatch.setattr(config, "RETRACEMENT_MIN_PCT", 0.2)
    monkeypatch.setattr(config, "RETRACEMENT_MAX_PCT", 0.79)
    monkeypatch.setattr(config, "ASIAN_SESSION_START_UTC", 0)
    monkeypatch.setattr(config, "ASIAN_SESSION_END_UTC", 6)
    monkeypatch.setattr(config, "LONDON_SESSION_START_UTC", 7)
    monkeypatch.setattr(config, "LONDON_SESSION_END_UTC", 12)
    monkeypatch.setattr(config, "NY_SESSION_START_UTC", 12)
    monkeypatch.setattr(config, "NY_SESSION_END_UTC", 20)
    monkeypatch.setattr(config, "AI_STRATEGY_SWEEP_WINDOW_MINUTES", 60)
    monkeypatch.setattr(config, "AI_STRATEGY_SL_BUFFER", 0.30)
    monkeypatch.setattr(config, "AI_STRATEGY_MIN_RR", 3.0)
    monkeypatch.setattr(config, "AI_STRATEGY_FUNDEDNEXT_MAX_DAILY_LOSS_USED_PCT", 50.0)
    monkeypatch.setattr(config, "AI_TOOL_MAX_ROUNDS", 4)
    monkeypatch.setattr(config, "AI_MEMORY_MIN_SIMILARITY", 0.18)
    monkeypatch.setattr(config, "AI_MEMORY_TOP_K", 3)
    monkeypatch.setattr(config, "AI_SIMILARITY_WEIGHT_H1_STRUCTURE", 0.12)
    monkeypatch.setattr(config, "AI_SIMILARITY_WEIGHT_M5_STRUCTURE", 0.08)
    monkeypatch.setattr(config, "AI_SIMILARITY_WEIGHT_M15_STRUCTURE", 0.05)
    monkeypatch.setattr(config, "AI_SIMILARITY_WEIGHT_H4_STRUCTURE", 0.05)
    monkeypatch.setattr(config, "AI_SIMILARITY_WEIGHT_LIQUIDITY", 0.20)
    monkeypatch.setattr(config, "AI_SIMILARITY_WEIGHT_MSS", 0.15)
    monkeypatch.setattr(config, "AI_SIMILARITY_WEIGHT_DISPLACEMENT", 0.15)
    monkeypatch.setattr(config, "AI_SIMILARITY_WEIGHT_REGIME", 0.10)
    monkeypatch.setattr(config, "AI_SIMILARITY_WEIGHT_SESSION", 0.05)
    monkeypatch.setattr(config, "AI_SIMILARITY_WEIGHT_RR", 0.05)
    monkeypatch.setattr(config, "AI_SIMILARITY_RR_TOLERANCE", 3.0)
    monkeypatch.setattr(config, "AI_SIMILARITY_DEFAULT_TOP_K", 5)
    monkeypatch.setattr(config, "AI_SIMILARITY_DEFAULT_MIN_SIMILARITY", 0.5)
    monkeypatch.setattr(config, "MARKET_INTEL_MACRO_PROVIDER", "mock")
    monkeypatch.setattr(config, "MARKET_INTEL_CROSS_ASSET_PROVIDER", "mock")
    monkeypatch.setattr(config, "MARKET_INTEL_EVENTS_PROVIDER", "mock")
    monkeypatch.setattr(config, "MARKET_INTEL_NEWS_PROVIDER", "mock")
    monkeypatch.setattr(config, "MARKET_INTEL_NEWS_MAX_AGE_HOURS", 48.0)
    monkeypatch.setattr(config, "MARKET_INTEL_NEWS_DEFAULT_LIMIT", 10)
    monkeypatch.setattr(config, "MARKET_INTEL_EVENTS_DAYS_AHEAD", 7)
    monkeypatch.setattr(config, "MARKET_INTEL_EVENTS_DAYS_BACK", 1)
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", "")
    monkeypatch.setattr(config, "MARKET_INTEL_HTTP_TIMEOUT_SECONDS", 8.0)
    monkeypatch.setattr(config, "MARKET_INTEL_CACHE_TTL_MACRO_SECONDS", 3600)
    monkeypatch.setattr(config, "MARKET_INTEL_CACHE_TTL_EVENTS_SECONDS", 600)
    monkeypatch.setattr(config, "MARKET_INTEL_CACHE_TTL_NEWS_SECONDS", 600)
    monkeypatch.setattr(config, "MARKET_INTEL_CACHE_TTL_CROSS_ASSET_SECONDS", 120)
    monkeypatch.setattr(config, "MARKET_INTEL_STALE_AFTER_SECONDS", 7200.0)
    monkeypatch.setattr(config, "MONITORING_ENABLED", False)
    monkeypatch.setattr(config, "MONITORING_INTERVAL_SECONDS", 20)
    monkeypatch.setattr(config, "MONITORING_EVENT_WARNING_MINUTES", 30)
    monkeypatch.setattr(config, "ALERT_RETENTION_DAYS", 30)
    monkeypatch.setattr(config, "TELEGRAM_ENABLED", False)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", "")
    monkeypatch.setattr(config, "TELEGRAM_POLL_INTERVAL_SECONDS", 5)
    monkeypatch.setattr(config, "TELEGRAM_MAX_RETRIES", 3)
    monkeypatch.setattr(config, "TELEGRAM_RETRY_BACKOFF_SECONDS", 2.0)
    monkeypatch.setattr(config, "TELEGRAM_HTTP_TIMEOUT_SECONDS", 8.0)
    monkeypatch.setattr(config, "NOTIFICATION_PROVIDER", "mock")
    monkeypatch.setattr(config, "TRADE_REVIEW_MIN_PATTERN_SAMPLE", 3)
    monkeypatch.setattr(config, "STRATEGY_ANALYTICS_MIN_SAMPLE", 5)


@pytest.fixture(autouse=True)
def _reset_monitoring_engine_state():
    """ai/monitoring/engine.py's `_last_snapshot` is module-level, process-
    lifetime state (by design — see its own docstring). Without this, one
    test's snapshot could leak into a later test and make a genuine
    transition look like a no-op, or vice versa."""
    from ai.monitoring import engine
    engine.reset_state()
    yield
    engine.reset_state()


@pytest.fixture(autouse=True)
def _clear_market_intelligence_cache():
    """ai/market_intelligence/providers/cache.py is a module-level, process-
    lifetime in-memory cache (by design — see its own docstring). Without
    this, one test's mocked HTTP response could leak into a later test that
    happens to use the same cache key (e.g. the same FRED series_id) but
    expects a different mocked response."""
    from ai.market_intelligence.providers import cache
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def temp_db(monkeypatch, tmp_path):
    """Points the journal DB at an isolated per-test sqlite file."""
    db_path = tmp_path / "test.db"
    monkeypatch.setattr(config, "DB_PATH", str(db_path))
    from journal.database import init_db
    init_db()
    return str(db_path)


@pytest.fixture(autouse=True)
def _isolated_fundednext_state(monkeypatch, tmp_path):
    """Redirects the FundedNext settings/day-state JSON files to a per-test
    tmp dir, so no test ever reads or writes the developer's real
    data/fundednext_*.json."""
    from risk import day_tracker, settings_store
    monkeypatch.setattr(settings_store, "SETTINGS_PATH", tmp_path / "fundednext_settings.json")
    monkeypatch.setattr(day_tracker, "STATE_PATH", tmp_path / "fundednext_day_state.json")
