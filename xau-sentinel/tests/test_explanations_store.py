"""Tests for ai/explanations/store.py — caching semantics: a cache hit
skips regeneration, POST .../generate always overwrites, and
UNIQUE(subject_type, subject_id) enforces one row per subject."""
import pytest

from ai.explanations import store
from ai.explanations.models import AlertExplanation


@pytest.fixture(autouse=True)
def _init(temp_db):
    store.init_table()


def _explanation(**overrides):
    defaults = dict(
        subject_type="alert", subject_id=1, explanation_type="APLUS_SETUP_DETECTED",
        summary="A+ setup detected — BUY.", deterministic_facts=["Direction: BUY"],
    )
    defaults.update(overrides)
    return AlertExplanation(**defaults)


def test_get_cached_returns_none_when_nothing_saved():
    assert store.get_cached("alert", 1) is None


def test_save_then_get_cached_returns_the_same_explanation():
    store.save(_explanation())
    cached = store.get_cached("alert", 1)
    assert cached is not None
    assert cached.summary == "A+ setup detected — BUY."
    assert cached.deterministic_facts == ["Direction: BUY"]


def test_save_twice_overwrites_rather_than_duplicating():
    store.save(_explanation(summary="First version"))
    store.save(_explanation(summary="Second version"))
    cached = store.get_cached("alert", 1)
    assert cached.summary == "Second version"


def test_cache_is_scoped_by_subject_type_and_id():
    store.save(_explanation(subject_type="alert", subject_id=1, summary="Alert explanation"))
    store.save(_explanation(subject_type="trade", subject_id=1, summary="Trade explanation"))
    assert store.get_cached("alert", 1).summary == "Alert explanation"
    assert store.get_cached("trade", 1).summary == "Trade explanation"
    assert store.get_cached("alert", 2) is None


def test_save_preserves_all_list_fields_through_json_round_trip():
    explanation = _explanation(
        deterministic_facts=["Direction: BUY", "Entry: 3700.0"],
        supporting_context=["Macro: Fed funds 5.25%"],
        uncertainties=["No historical matches found."],
        sources=["fundednext", "knowledge_rag"],
    )
    store.save(explanation)
    cached = store.get_cached("alert", 1)
    assert cached.deterministic_facts == ["Direction: BUY", "Entry: 3700.0"]
    assert cached.supporting_context == ["Macro: Fed funds 5.25%"]
    assert cached.uncertainties == ["No historical matches found."]
    assert cached.sources == ["fundednext", "knowledge_rag"]
