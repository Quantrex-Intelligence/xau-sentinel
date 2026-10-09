"""PostgreSQL persistence for Entry Model V2 LLM Setup Judge assessments (journal/schema.py's
entry_model_judgments table). Append-only: `save()` always INSERTs a new row, never
ON CONFLICT DO UPDATE -- unlike ai/explanations/store.py's cache semantics, this task requires a
reassessment of the same candidate to be distinguishable from the original evaluation, so nothing
here ever overwrites an earlier row. Every write does its own explicit conn.commit(), matching
every other store module in this codebase (journal.database.get_connection() never auto-commits).
"""
import json
from dataclasses import asdict
from typing import Optional

from sqlalchemy import desc, insert, select

from journal.database import get_connection
from journal.schema import entry_model_judgments
from ai.entry_judge.models import EntryJudgeVerdict, StoredJudgment


def _row_to_judgment(row) -> StoredJudgment:
    verdict = None
    if row.verdict_payload:
        verdict = EntryJudgeVerdict(**json.loads(row.verdict_payload))
    return StoredJudgment(
        id=row.id, candidate_key=row.candidate_key, direction=row.direction, state=row.state,
        symbol=row.symbol, snapshot_fingerprint=row.snapshot_fingerprint,
        snapshot=json.loads(row.snapshot), candidate_created_at=row.candidate_created_at,
        evaluated_at=row.evaluated_at, llm_provider=row.llm_provider, llm_model=row.llm_model,
        prompt_version=row.prompt_version, status=row.status, error_category=row.error_category,
        verdict=verdict, is_reassessment=row.is_reassessment,
    )


def get_latest(candidate_key: str) -> Optional[StoredJudgment]:
    """Most recent row for this candidate_key, or None if it has never been judged. This is the
    read side of the reevaluation control: the caller compares its own fresh snapshot's fingerprint
    against this row's to decide whether a new LLM call is even needed."""
    with get_connection() as conn:
        row = conn.execute(
            select(entry_model_judgments)
            .where(entry_model_judgments.c.candidate_key == candidate_key)
            .order_by(desc(entry_model_judgments.c.evaluated_at), desc(entry_model_judgments.c.id))
            .limit(1)
        ).fetchone()
    return _row_to_judgment(row) if row else None


def save(judgment: StoredJudgment) -> StoredJudgment:
    """Always a new row -- see module docstring. Returns `judgment` unchanged (its own id stays
    None; callers that need the assigned id can re-fetch via get_latest())."""
    verdict_payload = json.dumps(asdict(judgment.verdict)) if judgment.verdict is not None else None
    with get_connection() as conn:
        conn.execute(insert(entry_model_judgments).values(
            candidate_key=judgment.candidate_key, direction=judgment.direction, state=judgment.state,
            symbol=judgment.symbol, snapshot_fingerprint=judgment.snapshot_fingerprint,
            snapshot=json.dumps(judgment.snapshot, default=str),
            candidate_created_at=judgment.candidate_created_at, evaluated_at=judgment.evaluated_at,
            llm_provider=judgment.llm_provider, llm_model=judgment.llm_model,
            prompt_version=judgment.prompt_version, status=judgment.status,
            error_category=judgment.error_category,
            verdict=(judgment.verdict.verdict if judgment.verdict else None),
            quality=(judgment.verdict.quality if judgment.verdict else None),
            verdict_payload=verdict_payload, is_reassessment=judgment.is_reassessment,
        ))
        conn.commit()
    return judgment
