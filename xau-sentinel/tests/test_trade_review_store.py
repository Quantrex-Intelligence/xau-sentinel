"""Tests for ai/trade_review/store.py — caches ONLY the LLM interpretation,
UNIQUE(trade_id) so a re-save overwrites rather than duplicating."""
import pytest

from ai.trade_review import store
from ai.trade_review.models import Outcome, StrategyAlignment, TradeReview


@pytest.fixture(autouse=True)
def _init(temp_db):
    store.init_table()


def _review(**overrides):
    defaults = dict(
        trade_id=1, outcome=Outcome.WIN, strategy_alignment=StrategyAlignment.ALIGNED,
        setup_alignment=StrategyAlignment.ALIGNED, execution_alignment=StrategyAlignment.ALIGNED,
        risk_alignment=StrategyAlignment.ALIGNED, interpretation="A clear, safe interpretation.",
        llm_provider="mock", llm_model="mock-model",
    )
    defaults.update(overrides)
    return TradeReview(**defaults)


def test_get_cached_returns_none_when_nothing_saved():
    assert store.get_cached(1) is None


def test_save_then_get_cached_returns_the_interpretation():
    store.save(1, _review())
    cached = store.get_cached(1)
    assert cached is not None
    assert cached.interpretation == "A clear, safe interpretation."
    assert cached.llm_provider == "mock"


def test_save_twice_overwrites_rather_than_duplicating():
    store.save(1, _review(interpretation="First version"))
    store.save(1, _review(interpretation="Second version"))
    assert store.get_cached(1).interpretation == "Second version"


def test_cache_is_scoped_per_trade_id():
    store.save(1, _review(interpretation="Trade 1 review"))
    store.save(2, _review(trade_id=2, interpretation="Trade 2 review"))
    assert store.get_cached(1).interpretation == "Trade 1 review"
    assert store.get_cached(2).interpretation == "Trade 2 review"


def test_save_preserves_llm_error_when_present():
    store.save(1, _review(interpretation="AI trade review unavailable.", llm_provider=None,
                           llm_model=None, llm_error="AI_API_KEY is not set."))
    cached = store.get_cached(1)
    assert cached.llm_error == "AI_API_KEY is not set."
    assert cached.llm_provider is None
