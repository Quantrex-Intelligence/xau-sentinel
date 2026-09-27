"""SQLite schema and connection management for the trading journal.

Tables: trades, journal_context, market_events, alerts. Only what the journal
and event feed actually need is stored — no raw market data lives here.
"""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_date TEXT NOT NULL,
    trade_time TEXT NOT NULL,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    session TEXT,
    entry REAL NOT NULL,
    stop_loss REAL NOT NULL,
    take_profit REAL,
    planned_rr REAL,
    setup TEXT,
    market_regime TEXT,
    notes TEXT,
    screenshot_path TEXT,
    exit_price REAL,
    result TEXT,
    pnl REAL,
    r_multiple REAL,
    duration_minutes REAL,
    exit_reason TEXT,
    rule_followed TEXT,
    mistake TEXT,
    exit_notes TEXT,
    status TEXT NOT NULL DEFAULT 'OPEN',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS journal_context (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL REFERENCES trades(id) ON DELETE CASCADE,
    h4_bias TEXT,
    h1_bias TEXT,
    m15_bias TEXT,
    m5_bias TEXT,
    regime TEXT,
    liquidity TEXT,
    mss TEXT,
    displacement TEXT,
    session TEXT,
    captured_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS market_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_time TEXT NOT NULL,
    event_type TEXT NOT NULL,
    description TEXT NOT NULL,
    timeframe TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    alert_time TEXT NOT NULL,
    level TEXT NOT NULL,
    direction TEXT,
    message TEXT NOT NULL,
    details TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def init_db() -> None:
    Path(config.DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.executescript(SCHEMA)
        conn.commit()


@contextmanager
def get_connection():
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()
