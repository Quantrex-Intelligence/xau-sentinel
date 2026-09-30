"""Caches ONLY the LLM interpretation for a trade review (Stage 16) — not
the deterministic fields (strategy_alignment/deviations/outcome/etc.),
which are cheap, pure recomputations from trades/journal_context/
fundednext_context every request and would otherwise duplicate facts
those tables already own (spec section 22's explicit guidance). Table is
defined in journal/schema.py alongside every other table (DEP-002); this
module only builds and executes Core queries against it through
journal.database.get_connection().
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from journal.database import get_connection
from journal.schema import trade_reviews
from ai.trade_review.models import TradeReview


@dataclass
class CachedInterpretation:
    interpretation: Optional[str]
    llm_provider: Optional[str]
    llm_model: Optional[str]
    llm_error: Optional[str]
    generated_at: str


def _row_to_cached(row) -> CachedInterpretation:
    return CachedInterpretation(
        interpretation=row.interpretation, llm_provider=row.llm_provider,
        llm_model=row.llm_model, llm_error=row.llm_error, generated_at=row.generated_at.isoformat(),
    )


def get_cached(trade_id: int) -> Optional[CachedInterpretation]:
    with get_connection() as conn:
        row = conn.execute(select(trade_reviews).where(trade_reviews.c.trade_id == trade_id)).fetchone()
    return _row_to_cached(row) if row else None


def save(trade_id: int, review: TradeReview) -> None:
    now = datetime.now(timezone.utc)
    with get_connection() as conn:
        stmt = pg_insert(trade_reviews).values(
            trade_id=trade_id, interpretation=review.interpretation, llm_provider=review.llm_provider,
            llm_model=review.llm_model, llm_error=review.llm_error, generated_at=now,
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["trade_id"],
            set_={
                "interpretation": stmt.excluded.interpretation, "llm_provider": stmt.excluded.llm_provider,
                "llm_model": stmt.excluded.llm_model, "llm_error": stmt.excluded.llm_error,
                "generated_at": stmt.excluded.generated_at,
            },
        )
        conn.execute(stmt)
        conn.commit()
