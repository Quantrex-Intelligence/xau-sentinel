"""Tests for ai/similarity/scoring.py: deterministic weighted comparison,
missing-feature renormalization, RR tolerance, and matched/different lists."""
from ai.similarity.models import SetupFeatures
from ai.similarity.scoring import score


def _features(**overrides):
    base = dict(
        direction="BUY", h4_structure="BULLISH", h1_structure="BULLISH",
        m15_structure="PULLBACK", m5_structure="BULLISH", regime="TRENDING UP",
        liquidity_kind="sweep_low", mss_direction="bullish", displacement="bullish",
        session="London", planned_rr=2.5,
    )
    base.update(overrides)
    return SetupFeatures(**base)


def test_identical_features_score_1():
    similarity, matched, different = score(_features(), _features())
    assert similarity == 1.0
    assert different == []
    assert set(matched) == {
        "h1_structure", "m5_structure", "m15_structure", "h4_structure",
        "liquidity_kind", "mss_direction", "displacement", "regime", "session", "planned_rr",
    }


def test_completely_different_categorical_features_score_0():
    query = _features()
    candidate = _features(
        h4_structure="BEARISH", h1_structure="BEARISH", m15_structure="RANGING", m5_structure="BEARISH",
        regime="TRENDING DOWN", liquidity_kind="sweep_high", mss_direction="bearish",
        displacement="bearish", session="New York",
    )
    similarity, matched, different = score(query, candidate)
    assert similarity < 0.2  # only RR (identical here) contributes anything
    assert "h1_structure" in different


def test_categorical_match_is_case_insensitive():
    query = _features(mss_direction="Bullish", displacement="Bullish")
    candidate = _features(mss_direction="bullish", displacement="bullish")
    similarity, matched, _ = score(query, candidate)
    assert similarity == 1.0
    assert "mss_direction" in matched
    assert "displacement" in matched


def test_missing_feature_on_either_side_is_excluded_not_penalized():
    query = _features(regime=None)
    candidate = _features(regime="TRENDING UP")
    similarity, matched, different = score(query, candidate)
    assert "regime" not in matched
    assert "regime" not in different
    # Every other feature still matches exactly -> still a perfect score
    # over what WAS comparable.
    assert similarity == 1.0


def test_all_features_missing_scores_zero_not_an_error():
    empty = SetupFeatures()
    similarity, matched, different = score(empty, empty)
    assert similarity == 0.0
    assert matched == []
    assert different == []


def test_rr_similarity_decreases_with_distance_and_respects_tolerance(monkeypatch):
    import config
    monkeypatch.setattr(config, "AI_SIMILARITY_RR_TOLERANCE", 3.0)
    query = _features(planned_rr=2.0)

    exact = _features(planned_rr=2.0)
    close = _features(planned_rr=2.5)
    far = _features(planned_rr=10.0)

    sim_exact, matched_exact, _ = score(query, exact)
    sim_close, _, _ = score(query, close)
    sim_far, _, different_far = score(query, far)

    assert sim_exact == 1.0
    assert "planned_rr" in matched_exact
    assert sim_close > sim_far
    assert sim_far < sim_exact
    assert "planned_rr" in different_far


def test_rr_never_scores_below_zero_for_a_huge_difference(monkeypatch):
    import config
    monkeypatch.setattr(config, "AI_SIMILARITY_RR_TOLERANCE", 1.0)
    similarity, _, different = score(_features(planned_rr=1.0), _features(planned_rr=1000.0))
    assert similarity >= 0.0
    assert "planned_rr" in different


def test_weights_from_config_are_actually_used(monkeypatch):
    """Zeroing out every weight except one isolates that single feature's
    contribution — proves the config values genuinely drive the score,
    not a hardcoded internal table."""
    import config
    for attr in (
        "AI_SIMILARITY_WEIGHT_H1_STRUCTURE", "AI_SIMILARITY_WEIGHT_M5_STRUCTURE",
        "AI_SIMILARITY_WEIGHT_M15_STRUCTURE", "AI_SIMILARITY_WEIGHT_H4_STRUCTURE",
        "AI_SIMILARITY_WEIGHT_LIQUIDITY", "AI_SIMILARITY_WEIGHT_MSS",
        "AI_SIMILARITY_WEIGHT_DISPLACEMENT", "AI_SIMILARITY_WEIGHT_REGIME", "AI_SIMILARITY_WEIGHT_RR",
    ):
        monkeypatch.setattr(config, attr, 0.0)
    monkeypatch.setattr(config, "AI_SIMILARITY_WEIGHT_SESSION", 1.0)

    # h1_structure mismatches, but its weight is zeroed — the score must be
    # driven entirely by session (weight 1.0), which matches.
    candidate = _features(session="London", h1_structure="BEARISH")
    similarity, matched, different = score(_features(session="London"), candidate)
    assert similarity == 1.0
    assert "session" in matched
    assert "h1_structure" in different  # recorded as a real mismatch even though it's zero-weighted
