"""Shared fixtures and synthetic-candle helpers for the XAU Sentinel test suite."""
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

# Point the whole test process at a dedicated test database BEFORE config and
# journal.database read DATABASE_URL. Otherwise tests would share the developer's
# dev database, and leftover dev rows would change exact-count assertions.
# The test database is dropped and recreated every session (see _migrated_database),
# so tests never depend on what was left behind by a previous run.
TEST_DB_NAME = "xau_sentinel_test"
load_dotenv()
_dev_url = make_url(os.environ["DATABASE_URL"])
os.environ["DATABASE_URL"] = _dev_url.set(database=TEST_DB_NAME).render_as_string(hide_password=False)
# Force mock data and the mock AI provider for the whole test process, regardless of the
# developer's .env (MODE=live, a real AI_PROVIDER). Some modules read these at import
# time, so this has to happen before config is imported. Tests that need another value
# set it themselves with monkeypatch.
os.environ["MODE"] = "mock"
os.environ["AI_PROVIDER"] = "mock"

import config  # noqa: E402  (must follow the DATABASE_URL override above)


def make_candles(rows, tf_minutes=5, start=None, now=None):
    """Builds a deterministic OHLCV DataFrame from a list of
    (open, high, low, close) or (open, high, low, close, volume) tuples,
    oldest first, matching the [time, open, high, low, close, volume,
    close_time, is_closed] shape that mt5.market_data.get_candles returns
    (close_time/is_closed added in Stage 21, VAL-006).

    `now` (default: real wall clock) is the authoritative current time
    used to compute is_closed -- every existing caller's fixtures are
    anchored at the fixed default `start` (2026-01-05, in the real past),
    so they come back fully closed either way. Pass an explicit `now` to
    deliberately construct a forming (not-yet-closed) last candle for a
    Stage 21 regression test, matching whatever `now` the surrounding
    test also passes to evaluate_deterministic()/detect_setup() -- see
    tests/test_setup.py and tests/test_strategy_evaluator.py."""
    start = start or datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)  # a Monday
    now = now or datetime.now(timezone.utc)
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

    time_col = pd.to_datetime(times, utc=True)
    close_time_col = time_col + pd.Timedelta(minutes=tf_minutes)
    return pd.DataFrame({
        "time": time_col,
        "open": opens,
        "high": highs,
        "low": lows,
        "close": closes,
        "volume": volumes,
        "close_time": close_time_col,
        "is_closed": close_time_col <= now,
    })


def flat_candles(n, price=100.0, tf_minutes=5, start=None, noise=0.05, now=None):
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
    return make_candles(rows, tf_minutes=tf_minutes, start=start, now=now)


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
    monkeypatch.setattr(config, "DIGEST_ENABLED", False)
    monkeypatch.setattr(config, "DIGEST_WEEKLY_ENABLED", False)
    monkeypatch.setattr(config, "DIGEST_MONTHLY_ENABLED", False)
    monkeypatch.setattr(config, "DIGEST_WEEKLY_DAY", "MONDAY")
    monkeypatch.setattr(config, "DIGEST_WEEKLY_TIME", "09:00")
    monkeypatch.setattr(config, "DIGEST_MONTHLY_DAY", 1)
    monkeypatch.setattr(config, "DIGEST_MONTHLY_TIME", "09:00")
    monkeypatch.setattr(config, "DIGEST_POLL_INTERVAL_SECONDS", 300)


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
def _reset_notification_delivery_state():
    """Stage 23B: ai/notifications/delivery.py keeps module-level state
    (worker start time, sent-but-unrecorded ids, rate-limit pause), reset
    here for the same reason as the monitoring engine's snapshot above."""
    from ai.notifications import delivery
    delivery.reset_state()
    yield
    delivery.reset_state()


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


@pytest.fixture(scope="session")
def _migrated_database():
    """DEP-002: applies every Alembic migration to config.DATABASE_URL
    exactly once per test session (a no-op if already at head) -- the
    Postgres equivalent of the old per-test init_db(). Only tests that
    request `temp_db` (directly or via another fixture) pay this cost, the
    same separation the old sqlite-file fixture gave non-DB tests.

    Deliberately built WITHOUT pointing Config at alembic.ini: passing a
    config file makes alembic/env.py call logging.config.fileConfig() on
    it, which defaults to disable_existing_loggers=True and silently kills
    every logger already configured elsewhere in the process (e.g.
    ai.monitoring.engine's) for the rest of the test session -- caplog then
    captures nothing from them. Setting script_location/sqlalchemy.url
    programmatically gets the same migration run without that side effect."""
    from alembic import command
    from alembic.config import Config

    _recreate_test_database()
    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent.parent / "alembic"))
    command.upgrade(cfg, "head")


def _recreate_test_database() -> None:
    """Drop and recreate the dedicated test database so every session starts
    empty. Runs against the server's maintenance DB, never the dev DB, and
    only ever touches TEST_DB_NAME."""
    assert config.DATABASE_URL.endswith(f"/{TEST_DB_NAME}"), config.DATABASE_URL
    admin_url = make_url(config.DATABASE_URL).set(database="postgres")
    admin = create_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB_NAME}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{TEST_DB_NAME}"'))
    finally:
        admin.dispose()
    # The journal engine pools connections to the test database. Dispose it so no
    # pooled connection survives the drop above.
    from journal import database
    database.engine.dispose()


@pytest.fixture
def temp_db(_migrated_database):
    """Isolates this test's DB writes inside one outer transaction against
    the shared Postgres test database, rolled back at teardown -- replaces
    the old per-test SQLite file (Postgres has no equivalent cheap per-test
    throwaway file). journal.database.get_connection() is redirected (via
    its _test_connection ContextVar) to reuse this one Connection instead of
    checking a fresh one out of the pool.

    A real SQL COMMIT always finalizes the whole transaction, savepoints or
    not -- so application code's own `conn.commit()` calls (each already
    scoped to one SAVEPOINT by get_connection() itself, see its docstring)
    are neutered to a no-op here at the instance level, the only way to let
    a unit of work "finish" from the app's point of view without it ever
    reaching the real database until the fixture's own rollback discards
    everything at teardown."""
    from journal import database

    connection = database.engine.connect()
    outer_txn = connection.begin()
    connection.commit = lambda: None
    token = database._test_connection.set(connection)
    try:
        yield connection
    finally:
        database._test_connection.reset(token)
        outer_txn.rollback()
        connection.close()


@pytest.fixture(autouse=True)
def _every_test_uses_a_rolled_back_database(temp_db):
    """Every test runs inside the rolled-back transaction, not only the tests
    that remember to ask for temp_db. Before this, any test that forgot the
    fixture wrote to, and counted rows in, whatever the shared database held."""
    yield


@pytest.fixture(autouse=True)
def _isolated_fundednext_state(monkeypatch, tmp_path):
    """Redirects the FundedNext settings/day-state JSON files to a per-test
    tmp dir, so no test ever reads or writes the developer's real
    data/fundednext_*.json."""
    from risk import day_tracker, settings_store
    monkeypatch.setattr(settings_store, "SETTINGS_PATH", tmp_path / "fundednext_settings.json")
    monkeypatch.setattr(day_tracker, "STATE_PATH", tmp_path / "fundednext_day_state.json")
