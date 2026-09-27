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
