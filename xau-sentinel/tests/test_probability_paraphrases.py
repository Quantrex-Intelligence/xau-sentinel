"""Regression tests for the predictive-probability safety net (ai/prompts.py).

The literal pattern list catches exact phrasings only. These cases are
realistic paraphrases a model writes when it drifts into a win forecast, and
honest disclaimers that must NOT be replaced, since replacing them would drop
correct, non-predictive interpretation.
"""
import pytest

from ai.prompts import contains_predictive_probability_claim

PARAPHRASED_CLAIMS = [
    "This setup is more likely to win than to lose.",
    "The entry has favorable odds of working out.",
    "There is a 70 percent chance this trade succeeds.",
    "Confidence of 80% in this entry.",
    "I am confident that this will work out well.",
    "High confidence this will win.",
    "Expect this trade to succeed given the structure.",
    "The chance it hits the target is good.",
    "The probability of success is high here.",
    "This trade will work if price holds the low.",
    "The trade will hit the target before the stop.",
]

LITERAL_CLAIMS = [
    "This setup has a 90% chance of winning.",
    "This is a 75% probability winner.",
    "Odds favor a continuation to the upside.",
    "This setup will win.",
    "Similar setups tend to resolve upward.",
]

DISCLAIMERS_AND_DESCRIPTIONS = [
    # Real output from the cached Trade Review that the old checklist wrongly flagged.
    "This is purely descriptive and does not imply causation or probability for the outcome.",
    "The setup is not likely to win on its own; the review only describes the evidence.",
    "No probability of success is implied by this historical comparison.",
    "Historical similarity is descriptive only and is not a probability forecast.",
    "The trade was aligned with the recorded strategy rules.",
    "The stop was placed below the sweep low, as recorded.",
    "This review does not predict the next move.",
]


@pytest.mark.parametrize("text", LITERAL_CLAIMS)
def test_real_predictive_claims_are_blocked(text):
    assert contains_predictive_probability_claim(text), text


@pytest.mark.parametrize("text", PARAPHRASED_CLAIMS)
def test_realistic_paraphrases_are_blocked(text):
    assert contains_predictive_probability_claim(text), text


@pytest.mark.parametrize("text", DISCLAIMERS_AND_DESCRIPTIONS)
def test_negated_disclaimers_and_descriptions_are_allowed(text):
    assert not contains_predictive_probability_claim(text), text
