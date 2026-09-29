"""SQLite persistence/cache for explanations (Stage 15). One new table,
added the established way: CREATE TABLE IF NOT EXISTS through
journal.database.get_connection() — the same pattern ai/monitoring/store.py
and ai/notifications/store.py already established.

(subject_type, subject_id) is a sufficient, honest cache key — an alert is
immutable once created (only `acknowledged` ever changes, which doesn't
affect explanation content), so a cached explanation is intentionally a
fixed, point-in-time artifact, not a live view (see the Stage 15 plan). A
forced regeneration (POST .../generate) explicitly overwrites it via
INSERT OR REPLACE.
"""
import json
import sqlite3
from typing import Optional

from journal.database import get_connection
from ai.explanations.models import AlertExplanation

TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS explanations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    subject_type TEXT NOT NULL,
    subject_id INTEGER NOT NULL,
    explanation_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    llm_provider TEXT,
    llm_model TEXT,
    llm_error TEXT,
    generated_at TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_explanations_subject ON explanations(subject_type, subject_id);
"""


def init_table() -> None:
    with get_connection() as conn:
        conn.executescript(TABLE_SCHEMA)
        conn.commit()


def _row_to_explanation(row: sqlite3.Row) -> AlertExplanation:
    payload = json.loads(row["payload"])
    return AlertExplanation(**payload)


def get_cached(subject_type: str, subject_id: int) -> Optional[AlertExplanation]:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM explanations WHERE subject_type = ? AND subject_id = ?",
            (subject_type, subject_id),
        ).fetchone()
    return _row_to_explanation(row) if row else None


def save(explanation: AlertExplanation) -> AlertExplanation:
    """INSERT OR REPLACE — a forced regeneration explicitly overwrites any
    existing cached row for this (subject_type, subject_id)."""
    payload = json.dumps(explanation.__dict__)
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO explanations
               (subject_type, subject_id, explanation_type, payload, llm_provider, llm_model, llm_error, generated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(subject_type, subject_id) DO UPDATE SET
                   explanation_type = excluded.explanation_type, payload = excluded.payload,
                   llm_provider = excluded.llm_provider, llm_model = excluded.llm_model,
                   llm_error = excluded.llm_error, generated_at = excluded.generated_at""",
            (explanation.subject_type, explanation.subject_id, explanation.explanation_type, payload,
             explanation.llm_provider, explanation.llm_model, explanation.llm_error, explanation.generated_at),
        )
        conn.commit()
    return explanation
