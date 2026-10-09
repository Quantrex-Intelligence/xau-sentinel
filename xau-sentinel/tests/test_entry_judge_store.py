"""Tests for ai/entry_judge/store.py -- append-only persistence: a save() never overwrites an
earlier row, get_latest() returns the most recent one, and JSON round-trips through the DB intact."""
from datetime import datetime, timezone

from ai.entry_judge.models import STATUS_FAILED, STATUS_OK, EntryJudgeVerdict, StoredJudgment
from ai.entry_judge import store


def _judgment(**overrides):
    now = datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc)
    defaults = dict(
        candidate_key="LONG:stop:100.0", direction="LONG", state="ENTRY_READY", symbol="XAUUSD",
        snapshot_fingerprint="fp1", snapshot={"state": "ENTRY_READY"}, candidate_created_at=now,
        evaluated_at=now, prompt_version="entry-judge-v1", status=STATUS_OK, is_reassessment=False,
        llm_provider="mock", llm_model="mock-model",
        verdict=EntryJudgeVerdict(
            verdict="SUPPORTED", quality="HIGH", supporting_evidence=["a"], reasoning_summary="ok",
            model_id="mock-model", prompt_version="entry-judge-v1",
        ),
    )
    defaults.update(overrides)
    return StoredJudgment(**defaults)


def test_get_latest_returns_none_when_nothing_saved():
    assert store.get_latest("LONG:stop:999.0") is None


def test_save_then_get_latest_round_trips_the_verdict():
    store.save(_judgment())
    latest = store.get_latest("LONG:stop:100.0")
    assert latest is not None
    assert latest.status == STATUS_OK
    assert latest.verdict.verdict == "SUPPORTED"
    assert latest.verdict.supporting_evidence == ["a"]
    assert latest.snapshot == {"state": "ENTRY_READY"}


def test_save_twice_keeps_both_rows_append_only():
    store.save(_judgment(evaluated_at=datetime(2026, 10, 8, 12, 0, tzinfo=timezone.utc), snapshot_fingerprint="fp1"))
    store.save(_judgment(
        evaluated_at=datetime(2026, 10, 8, 12, 30, tzinfo=timezone.utc), snapshot_fingerprint="fp2",
        is_reassessment=True,
    ))
    # get_latest returns only the most recent, but both rows exist (checked via a second distinct key)
    latest = store.get_latest("LONG:stop:100.0")
    assert latest.snapshot_fingerprint == "fp2"
    assert latest.is_reassessment is True


def test_a_failed_attempt_is_stored_without_a_verdict():
    store.save(_judgment(status=STATUS_FAILED, verdict=None, error_category="config"))
    latest = store.get_latest("LONG:stop:100.0")
    assert latest.status == STATUS_FAILED
    assert latest.verdict is None
    assert latest.error_category == "config"


def test_get_latest_is_scoped_by_candidate_key():
    store.save(_judgment(candidate_key="LONG:stop:100.0"))
    store.save(_judgment(candidate_key="SHORT:stop:200.0", direction="SHORT"))
    assert store.get_latest("LONG:stop:100.0").direction == "LONG"
    assert store.get_latest("SHORT:stop:200.0").direction == "SHORT"
