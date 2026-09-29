"""Caches ONLY the LLM interpretation for a trade review (Stage 16) — not
the deterministic fields (strategy_alignment/deviations/outcome/etc.),
which are cheap, pure recomputations from trades/journal_context/
fundednext_context every request and would otherwise duplicate facts
those tables already own (spec section 22's explicit guidance). One new
table, added the established way: CREATE TABLE IF NOT EXISTS through
journal.database.get_connection() — journal/database.py's frozen schema
is never touched.
"""
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from journal.database import get_connection
from ai.trade_review.models import TradeReview

TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER NOT NULL UNIQUE,
    interpretation TEXT,
    llm_provider TEXT,
    llm_model TEXT,
    llm_error TEXT,
    generated_at TEXT NOT NULL
);
"""


@dataclass
class CachedInterpretation:
    interpretation: Optional[str]
    llm_provider: Optional[str]
    llm_model: Optional[str]
    llm_error: Optional[str]
    generated_at: str


def init_table() -> None:
    with get_connection() as conn:
        conn.executescript(TABLE_SCHEMA)
        conn.commit()


def _row_to_cached(row: sqlite3.Row) -> CachedInterpretation:
    return CachedInterpretation(
        interpretation=row["interpretation"], llm_provider=row["llm_provider"],
        llm_model=row["llm_model"], llm_error=row["llm_error"], generated_at=row["generated_at"],
    )


def get_cached(trade_id: int) -> Optional[CachedInterpretation]:
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM trade_reviews WHERE trade_id = ?", (trade_id,)).fetchone()
    return _row_to_cached(row) if row else None


def save(trade_id: int, review: TradeReview) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """INSERT INTO trade_reviews (trade_id, interpretation, llm_provider, llm_model, llm_error, generated_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(trade_id) DO UPDATE SET
                   interpretation = excluded.interpretation, llm_provider = excluded.llm_provider,
                   llm_model = excluded.llm_model, llm_error = excluded.llm_error,
                   generated_at = excluded.generated_at""",
            (trade_id, review.interpretation, review.llm_provider, review.llm_model, review.llm_error, now),
        )
        conn.commit()
