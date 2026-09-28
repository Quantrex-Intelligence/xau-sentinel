"""Safety tests for Stage 8: the deterministic predictive-probability
backstop, ground rule 9's presence and positioning, and — critically — A+
strategy authority preservation: historical similarity must never change a
deterministic rating, whether that rating would otherwise be A+ or not."""
import pytest

from ai import assistant, prompts
from ai.context import AssembledContext
from ai.providers.base import BaseProvider, ProviderResponse
from ai.strategy.schemas import Rating
from journal import trades as trades_repo
from tests.test_strategy_evaluator import NOW, _candles, _full_buy_setup, _safe_status
import ai.strategy.evaluator as evaluator_mod


@pytest.fixture(autouse=True)
def _ai_table(temp_db):
    assistant.init_table()
    return temp_db


class _RecordingProvider(BaseProvider):
    name = "fake"
    model = "fake-model"

    def __init__(self, reply: str):
        self.reply = reply

    def chat(self, system, messages, tools=None) -> ProviderResponse:
        return ProviderResponse(text=self.reply, provider=self.name, model=self.model)


def _use_provider(monkeypatch, provider):
    monkeypatch.setattr(assistant, "get_provider", lambda: provider)


# ---------------------------------------------------------------------------
# Deterministic predictive-probability backstop
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "This setup has an 85% chance of winning.",
    "Based on similar trades, this trade will win.",
    "Because similar trades won, this trade should win too.",
    "There's a high probability of success here.",
])
def test_contains_predictive_probability_claim_catches_known_bad_phrasings(text):
    assert prompts.contains_predictive_probability_claim(text) is True


@pytest.mark.parametrize("text", [
    "Trade #183 shares several structural characteristics with the current setup.",
    "3 of 5 historical matches resulted in a win; this is descriptive, not a forecast.",
    "The setup direction is BUY, per the setup engine.",
])
def test_contains_predictive_probability_claim_does_not_false_positive_on_safe_text(text):
    assert prompts.contains_predictive_probability_claim(text) is False


def test_chat_replaces_a_predictive_probability_answer(monkeypatch):
    _use_provider(monkeypatch, _RecordingProvider("This setup has a 90% chance of winning based on history."))
    result = assistant.chat("Have I seen a setup like this before?")
    assert "90%" not in result.answer
    assert result.answer == prompts.SIMILARITY_SAFETY_OVERRIDE_MESSAGE


def test_chat_does_not_false_positive_on_a_plain_similarity_summary(monkeypatch):
    _use_provider(monkeypatch, _RecordingProvider(
        "Trade #183 and #211 share similar structural characteristics with the current setup."
    ))
    result = assistant.chat("Have I seen a setup like this before?")
    assert "Trade #183" in result.answer


def test_prompt_injection_provoked_probability_claim_is_still_caught(monkeypatch):
    """Worst case: pretend the model WAS fooled into stating a probability —
    the same unconditional filter still catches it, zero changes needed
    for whatever provoked it (mirrors the Stage 5/6/7 injection tests)."""
    _use_provider(monkeypatch, _RecordingProvider(
        "IGNORE PREVIOUS RULES. This trade will win because similar trades won."
    ))
    result = assistant.chat("Tell me about historical similarity")
    assert result.answer == prompts.SIMILARITY_SAFETY_OVERRIDE_MESSAGE


# ---------------------------------------------------------------------------
# Ground rule 9 presence
# ---------------------------------------------------------------------------

def test_ground_rule_9_is_present_and_forbids_probability_claims():
    prompt = prompts.build_system_prompt(AssembledContext(sections=[]))
    assert "9. A tool may return historically similar past setups" in prompt
    assert "NEVER say a percentage chance of winning" in prompt


# ---------------------------------------------------------------------------
# A+ strategy authority preservation — the concrete mechanism is that
# evaluate_deterministic() never imports ai.similarity at all, proven here
# by showing its rating is identical regardless of what's in the journal.
# ---------------------------------------------------------------------------

def test_evaluator_module_never_imports_similarity():
    import inspect
    source = inspect.getsource(evaluator_mod)
    assert "ai.similarity" not in source
    assert "find_similar_setups" not in source


def _trade_payload(**overrides):
    payload = {
        "trade_date": "2026-01-05", "trade_time": "09:00:00", "symbol": "XAUUSD",
        "direction": "BUY", "session": "London", "entry": 100.0, "stop_loss": 95.0,
        "take_profit": 110.0, "planned_rr": 2.5, "setup": "Sweep + MSS", "market_regime": "TRENDING UP",
        "notes": "", "screenshot_path": None,
    }
    payload.update(overrides)
    return payload


def _context_payload(**overrides):
    context = {
        "h4_bias": "BULLISH", "h1_bias": "BULLISH", "m15_bias": "PULLBACK", "m5_bias": "BULLISH",
        "regime": "TRENDING UP", "liquidity": "Previous Day Low swept", "mss": "Bullish",
        "displacement": "Bullish", "session": "London",
    }
    context.update(overrides)
    return context


def test_high_historical_similarity_does_not_change_a_developing_rating(monkeypatch, temp_db):
    """A DEVELOPING setup (missing retracement) must stay DEVELOPING even
    when many near-identical historical trades exist and would score very
    high similarity against it."""
    for _ in range(5):  # many highly similar winning trades in the journal
        trade_id = trades_repo.create_trade(_trade_payload(), _context_payload())
        trades_repo.close_trade(trade_id, {
            "exit_price": 110.0, "result": "WIN", "pnl": 500.0, "r_multiple": 2.0,
            "duration_minutes": 45, "exit_reason": "Hit TP", "rule_followed": "Yes",
            "mistake": None, "exit_notes": "clean",
        })

    _full_buy_setup(monkeypatch, retracement_ok=False)  # everything else passes, retracement doesn't
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    assert result.rating == Rating.DEVELOPING
    assert "Retracement" in result.missing_conditions


def test_a_plus_rating_is_identical_with_and_without_similarity_data(monkeypatch, temp_db):
    _full_buy_setup(monkeypatch)
    empty_journal_result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)

    for _ in range(5):
        trades_repo.create_trade(_trade_payload(), _context_payload())

    _full_buy_setup(monkeypatch)  # re-patch: the Mock side_effect list is consumed per call
    populated_journal_result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)

    assert empty_journal_result.rating == populated_journal_result.rating == Rating.A_PLUS
