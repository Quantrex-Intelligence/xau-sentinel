"""Stage 19 regression tests for the broadened safety filters (see
docs/validation/ISSUE_LOG.md VAL-001). The original 5/4-pattern sets only
caught their own literal example phrasings — every phrase below was
confirmed, during the Stage 18 Validation Phase, to slip through the
pre-Stage-19 regexes by direct execution. This file proves the broadened
sets now catch them, without breaking any of the existing "must not
false-positive" fixtures (re-run unmodified in their own test files as
the regression proof for that half)."""
import pytest

from ai.prompts import contains_actionable_directive, contains_predictive_probability_claim

# ---------------------------------------------------------------------------
# Actionable directives — every category the stage spec named.
# ---------------------------------------------------------------------------

DIRECTIVE_PHRASES = [
    # direct buy/sell instructions
    "Go long now.",
    "Short gold here.",
    "Buy immediately.",
    "Take the long.",
    # imperative trading language
    "Enter now.",
    "Exit now.",
    "Close your position now.",
    "Take profit now.",
    # indirect recommendations
    "It would be wise to go long here.",
    "Consider entering a long position here.",
    "My advice: buy.",
    "I would recommend buying here.",
    "The setup favors entering long.",
    # conditional trade instructions
    "If price breaks 2350, buy.",
    "If the sweep holds, enter long here.",
    # entry/exit instructions
    "Open a long position.",
    "Move your stop to breakeven.",
    "You should add to your position.",
    "You should take this trade.",
    # markdown noise defeating a literal word-boundary match
    "**Buy** now while the sweep is fresh.",
    "BUY_NOW at the current price.",
]


@pytest.mark.parametrize("text", DIRECTIVE_PHRASES)
def test_actionable_directive_filter_catches_realistic_paraphrases(text):
    assert contains_actionable_directive(text) is True


# ---------------------------------------------------------------------------
# Predictive probability / confidence / future-performance claims.
# ---------------------------------------------------------------------------

PROBABILITY_PHRASES = [
    # probability/win-rate predictions
    "This pattern tends to resolve upward.",
    "This setup is likely to win.",
    # confidence/probability phrasing
    "Odds favor a bounce here.",
    "There is a strong chance of a reversal.",
    "Strong chance of success here.",
    # paraphrased future-performance claims
    "This setup is likely to play out well.",
    "Historically this leads to a bounce.",
    "The price will rally from here.",
]


@pytest.mark.parametrize("text", PROBABILITY_PHRASES)
def test_predictive_probability_filter_catches_realistic_paraphrases(text):
    assert contains_predictive_probability_claim(text) is True


# ---------------------------------------------------------------------------
# Must still NOT false-positive on plain fact restatement (re-asserted here
# for visibility; the canonical regression proof is the existing safety
# test files, re-run unmodified alongside this one).
# ---------------------------------------------------------------------------

SAFE_PHRASES = [
    "The setup direction is BUY, per the setup engine.",
    "According to the FundedNext risk rules, the daily loss limit resets at 00:00 server time.",
    "Setup direction: BUY. Rating: A+.",
    "H1 structure is BULLISH.",
]


@pytest.mark.parametrize("text", SAFE_PHRASES)
def test_actionable_directive_filter_does_not_false_positive(text):
    assert contains_actionable_directive(text) is False


SAFE_SIMILARITY_PHRASES = [
    "Trade #183 shares several structural characteristics with the current setup.",
    "3 of 5 historical matches resulted in a win; this is descriptive, not a forecast.",
    "The setup direction is BUY, per the setup engine.",
]


@pytest.mark.parametrize("text", SAFE_SIMILARITY_PHRASES)
def test_predictive_probability_filter_does_not_false_positive(text):
    assert contains_predictive_probability_claim(text) is False
