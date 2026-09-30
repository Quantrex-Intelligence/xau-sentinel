"""PostgreSQL persistence/cache for explanations (Stage 15, DEP-002). Table
is defined in journal/schema.py alongside every other table; this module
only builds and executes Core queries against it through
journal.database.get_connection().

(subject_type, subject_id) is a sufficient, honest cache key — an alert is
immutable once created (only `acknowledged` ever changes, which doesn't
affect explanation content), so a cached explanation is intentionally a
fixed, point-in-time artifact, not a live view (see the Stage 15 plan). A
forced regeneration (POST .../generate) explicitly overwrites it via
ON CONFLICT DO UPDATE.
"""
import json
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from journal.database import get_connection
from journal.schema import explanations
from ai.explanations.models import AlertExplanation


def _row_to_explanation(row) -> AlertExplanation:
    payload = json.loads(row.payload)
    return AlertExplanation(**payload)


def get_cached(subject_type: str, subject_id: int) -> Optional[AlertExplanation]:
    with get_connection() as conn:
        row = conn.execute(
            select(explanations).where(
                explanations.c.subject_type == subject_type, explanations.c.subject_id == subject_id,
            )
        ).fetchone()
    return _row_to_explanation(row) if row else None


def save(explanation: AlertExplanation) -> AlertExplanation:
    """ON CONFLICT DO UPDATE — a forced regeneration explicitly overwrites
    any existing cached row for this (subject_type, subject_id)."""
    payload = json.dumps(explanation.__dict__)
    with get_connection() as conn:
        stmt = pg_insert(explanations).values(
            subject_type=explanation.subject_type, subject_id=explanation.subject_id,
            explanation_type=explanation.explanation_type, payload=payload,
            llm_provider=explanation.llm_provider, llm_model=explanation.llm_model,
            llm_error=explanation.llm_error, generated_at=explanation.generated_at,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["subject_type", "subject_id"],
            set_={
                "explanation_type": stmt.excluded.explanation_type, "payload": stmt.excluded.payload,
                "llm_provider": stmt.excluded.llm_provider, "llm_model": stmt.excluded.llm_model,
                "llm_error": stmt.excluded.llm_error, "generated_at": stmt.excluded.generated_at,
            },
        )
        conn.execute(stmt)
        conn.commit()
    return explanation
