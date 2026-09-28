"""Tests for the Intelligence Quality Model (Stage 12) — URL/timestamp
validation, news relevance classification, event status classification,
unit consistency, cross-asset per-field quality, event-risk proximity, and
the deterministic intelligence-summary rollup. No numeric confidence score
anywhere — every assertion checks one of a small, fixed set of explicit
states."""
from datetime import datetime, timedelta, timezone

from ai.market_intelligence import quality as q
from ai.market_intelligence.models import (
    CrossAssetSnapshot, EconomicEvent, GoldFundamentals, MacroSnapshot, MarketIntelligenceContext, NewsArticle,
)


def _now():
    return datetime(2026, 9, 28, 12, 0, 0, tzinfo=timezone.utc)


def _article(**overrides):
    now = _now()
    defaults = dict(
        id="1", headline="Gold steadies as traders await Fed guidance", source="wire-a",
        published_at=now.isoformat(), retrieved_at=now.isoformat(), url=None,
    )
    defaults.update(overrides)
    return NewsArticle(**defaults)


def _event(**overrides):
    defaults = dict(
        name="US CPI", category="Inflation", importance="HIGH",
        scheduled_at=_now().isoformat(), source="real", country="US",
    )
    defaults.update(overrides)
    return EconomicEvent(**defaults)


# ---------------------------------------------------------------------------
# URL validation
# ---------------------------------------------------------------------------

def test_none_url_is_valid_nothing_to_check():
    assert q.is_valid_url(None) is True


def test_wellformed_https_url_is_valid():
    assert q.is_valid_url("https://example.com/story") is True


def test_malformed_url_missing_scheme_is_invalid():
    assert q.is_valid_url("example.com/story") is False


def test_malformed_url_with_unsupported_scheme_is_invalid():
    assert q.is_valid_url("ftp://example.com/story") is False


def test_malformed_url_empty_string_is_invalid():
    assert q.is_valid_url("") is False


# ---------------------------------------------------------------------------
# Timestamp plausibility
# ---------------------------------------------------------------------------

def test_current_timestamp_is_plausible():
    now = _now()
    assert q.is_plausible_timestamp(now, now) is True


def test_slightly_future_timestamp_within_skew_is_plausible():
    now = _now()
    assert q.is_plausible_timestamp(now + timedelta(seconds=30), now) is True


def test_far_future_timestamp_is_not_plausible():
    now = _now()
    assert q.is_plausible_timestamp(now + timedelta(days=1), now) is False


def test_ancient_timestamp_is_not_plausible():
    now = _now()
    assert q.is_plausible_timestamp(datetime(1990, 1, 1, tzinfo=timezone.utc), now) is False


def test_none_timestamp_is_not_plausible():
    assert q.is_plausible_timestamp(None, _now()) is False


# ---------------------------------------------------------------------------
# Unit consistency
# ---------------------------------------------------------------------------

def test_units_consistent_when_both_percent():
    assert q.units_consistent("3.10%", "3.00%") is True


def test_units_consistent_when_neither_percent():
    assert q.units_consistent("250.10", "249.00") is True


def test_units_inconsistent_when_mixed():
    assert q.units_consistent("3.10%", "249.00") is False


def test_units_consistent_when_either_side_missing():
    assert q.units_consistent(None, "3.00%") is True
    assert q.units_consistent("3.10%", None) is True


# ---------------------------------------------------------------------------
# News relevance
# ---------------------------------------------------------------------------

def test_relevant_headline_classified_relevant():
    assert q.classify_news_relevance("Fed officials signal potential rate-policy change") == "RELEVANT"


def test_irrelevant_headline_classified_not_relevant():
    assert q.classify_news_relevance("Apple releases new iPhone color") == "NOT_RELEVANT"


def test_generic_financial_headline_not_automatically_relevant():
    """The spec's explicit rule: a generic financial headline is not
    automatically XAUUSD-relevant just because it's about markets."""
    assert q.classify_news_relevance("Tech stocks rally on earnings beat") == "NOT_RELEVANT"


def test_empty_headline_and_summary_is_unknown():
    assert q.classify_news_relevance("", None) == "UNKNOWN"


def test_asset_tag_short_circuits_to_relevant_even_without_keyword_match():
    assert q.classify_news_relevance("Weekly market wrap", assets=["XAUUSD"]) == "RELEVANT"


def test_relevance_is_case_insensitive():
    assert q.classify_news_relevance("GOLD PRICES SURGE ON FED COMMENTS") == "RELEVANT"


def test_relevance_checks_summary_too():
    assert q.classify_news_relevance("Markets react", summary="Treasury yields moved sharply.") == "RELEVANT"


# ---------------------------------------------------------------------------
# News quality / assessment (validation + staleness + relevance + dedup)
# ---------------------------------------------------------------------------

def test_validate_news_article_flags_malformed_url():
    article = _article(url="not-a-url")
    result = q.validate_news_article(article, _now())
    assert result.url_valid is False


def test_validate_news_article_flags_future_timestamp():
    article = _article(published_at=(_now() + timedelta(days=2)).isoformat())
    result = q.validate_news_article(article, _now())
    assert result.timestamp_valid is False


def test_validate_news_article_freshness_live_within_window():
    article = _article(published_at=_now().isoformat())
    result = q.validate_news_article(article, _now(), max_age_hours=48)
    assert result.freshness == "LIVE"


def test_validate_news_article_freshness_stale_beyond_window():
    article = _article(published_at=(_now() - timedelta(hours=100)).isoformat())
    result = q.validate_news_article(article, _now(), max_age_hours=48)
    assert result.freshness == "STALE"


def test_assess_news_quality_drops_stale_articles():
    fresh = _article(id="fresh", published_at=_now().isoformat())
    stale = _article(id="stale", published_at=(_now() - timedelta(hours=100)).isoformat())
    kept = q.assess_news_quality([fresh, stale], _now(), max_age_hours=48)
    assert {r.article.id for r in kept} == {"fresh"}


def test_assess_news_quality_drops_irrelevant_articles():
    relevant = _article(id="relevant", headline="Gold steadies as traders await Fed guidance")
    irrelevant = _article(id="irrelevant", headline="Apple releases new iPhone color")
    kept = q.assess_news_quality([relevant, irrelevant], _now())
    assert {r.article.id for r in kept} == {"relevant"}


def test_assess_news_quality_drops_future_timestamps():
    future = _article(id="future", published_at=(_now() + timedelta(days=5)).isoformat())
    kept = q.assess_news_quality([future], _now())
    assert kept == []


def test_assess_news_quality_dedupes_duplicate_stories():
    first = _article(id="1", headline="Gold rallies on Fed guidance")
    dup = _article(id="2", headline="Gold rallies on Fed guidance")
    kept = q.assess_news_quality([first, dup], _now())
    assert len(kept) == 1


def test_assess_news_quality_handles_empty_list():
    assert q.assess_news_quality([], _now()) == []


# ---------------------------------------------------------------------------
# Economic event status classification
# ---------------------------------------------------------------------------

def test_event_status_not_released_when_scheduled_in_future_with_no_actual():
    event = _event(scheduled_at=(_now() + timedelta(days=1)).isoformat(), actual=None)
    assert q.classify_event_status(event, _now()) == "NOT_RELEASED"


def test_event_status_released_when_actual_present():
    event = _event(scheduled_at=(_now() - timedelta(days=1)).isoformat(), actual="3.10%")
    assert q.classify_event_status(event, _now()) == "RELEASED"


def test_event_status_released_when_actual_present_even_if_schedule_is_future():
    event = _event(scheduled_at=(_now() + timedelta(hours=1)).isoformat(), actual="3.10%")
    assert q.classify_event_status(event, _now()) == "RELEASED"


def test_event_status_not_available_when_past_scheduled_with_no_actual():
    event = _event(scheduled_at=(_now() - timedelta(days=1)).isoformat(), actual=None)
    assert q.classify_event_status(event, _now()) == "NOT_AVAILABLE"


def test_validate_event_never_invents_missing_actual_or_forecast():
    event = _event(actual=None, forecast=None, previous=None)
    result = q.validate_event(event, _now())
    assert result.event.actual is None
    assert result.event.forecast is None


def test_validate_event_flags_missing_country():
    event = _event(country=None)
    result = q.validate_event(event, _now())
    assert result.country_valid is False


def test_validate_event_flags_invalid_importance():
    event = _event(importance="EXTREME")
    result = q.validate_event(event, _now())
    assert result.importance_valid is False


def test_validate_event_flags_incompatible_units():
    event = _event(actual="3.10%", previous="250.00")
    result = q.validate_event(event, _now())
    assert result.units_consistent is False


def test_validate_event_flags_implausible_timestamp():
    event = _event(scheduled_at=(_now() + timedelta(days=10)).isoformat())
    result = q.validate_event(event, _now())
    assert result.timestamp_valid is False


# ---------------------------------------------------------------------------
# Event risk context — proximity, never a forecast of the result
# ---------------------------------------------------------------------------

def test_event_risk_context_computes_minutes_until():
    event = _event(scheduled_at=(_now() + timedelta(minutes=42)).isoformat())
    items = q.build_event_risk_context([event], _now())
    assert items[0].minutes_until == 42
    assert items[0].status == "UPCOMING"


def test_event_risk_context_never_includes_a_predicted_value():
    """No field on EventRiskItem may carry a forecast/predicted number —
    only timing and known metadata (the spec's explicit "identify event
    risk, not forecast the number")."""
    event = _event(scheduled_at=(_now() + timedelta(minutes=10)).isoformat())
    items = q.build_event_risk_context([event], _now())
    item_fields = vars(items[0])
    assert "forecast" not in item_fields
    assert "predicted" not in item_fields


def test_event_risk_context_assigns_assets_from_category():
    event = _event(category="Central Bank", scheduled_at=(_now() + timedelta(hours=1)).isoformat())
    items = q.build_event_risk_context([event], _now())
    assert "US10Y" in items[0].assets


def test_event_risk_context_sorted_by_proximity():
    near = _event(name="Near", scheduled_at=(_now() + timedelta(minutes=10)).isoformat())
    far = _event(name="Far", scheduled_at=(_now() + timedelta(days=3)).isoformat())
    items = q.build_event_risk_context([far, near], _now())
    assert [i.event for i in items] == ["Near", "Far"]


def test_event_risk_context_status_not_available_for_past_event_with_no_actual():
    event = _event(scheduled_at=(_now() - timedelta(hours=1)).isoformat(), actual=None)
    items = q.build_event_risk_context([event], _now())
    assert items[0].status == "NOT_AVAILABLE"


# ---------------------------------------------------------------------------
# Cross-asset per-field quality
# ---------------------------------------------------------------------------

def test_cross_asset_field_quality_marks_missing_field_unavailable():
    snapshot = CrossAssetSnapshot(
        data_available=True, source="real", generated_at=_now().isoformat(),
        dxy=101.28, vix=None, freshness="LIVE",
    )
    fields = {f.field: f for f in q.classify_cross_asset_field_quality(snapshot)}
    assert fields["dxy"].freshness == "LIVE"
    assert fields["vix"].freshness == "UNAVAILABLE"
    assert fields["vix"].value is None


def test_cross_asset_field_quality_tolerates_partial_availability():
    """Stage 11's own example: DXY/US10Y live, US2Y/VIX unavailable — must
    not invalidate the whole snapshot."""
    snapshot = CrossAssetSnapshot(
        data_available=True, source="real", generated_at=_now().isoformat(),
        dxy=101.28, us10y_yield=4.2, us2y_yield=None, vix=None, freshness="LIVE",
    )
    fields = {f.field: f for f in q.classify_cross_asset_field_quality(snapshot)}
    assert fields["dxy"].freshness == "LIVE"
    assert fields["us10y_yield"].freshness == "LIVE"
    assert fields["us2y_yield"].freshness == "UNAVAILABLE"
    assert fields["vix"].freshness == "UNAVAILABLE"


def test_cross_asset_field_quality_handles_none_snapshot():
    fields = q.classify_cross_asset_field_quality(None)
    assert all(f.freshness == "UNAVAILABLE" for f in fields)
    assert len(fields) == 6


# ---------------------------------------------------------------------------
# Category quality
# ---------------------------------------------------------------------------

def test_category_quality_good_when_live_and_available():
    cq = q.category_quality("macro", True, "LIVE", "real", _now().isoformat())
    assert cq.quality == "GOOD"


def test_category_quality_degraded_when_stale():
    cq = q.category_quality("macro", True, "STALE", "real", _now().isoformat())
    assert cq.quality == "DEGRADED"


def test_category_quality_unavailable_when_not_available():
    cq = q.category_quality("macro", False, "UNAVAILABLE", None, None)
    assert cq.quality == "UNAVAILABLE"


def test_category_quality_mock_takes_priority():
    cq = q.category_quality("macro", True, "MOCK", "mock", _now().isoformat())
    assert cq.quality == "MOCK"


# ---------------------------------------------------------------------------
# Intelligence summary rollup — deterministic, no numeric confidence
# ---------------------------------------------------------------------------

def _mi_context(**overrides):
    defaults = dict(
        data_available=True, generated_at=_now().isoformat(),
        macro=MacroSnapshot(data_available=True, source="mock", generated_at=_now().isoformat(), freshness="MOCK"),
        gold_fundamentals=GoldFundamentals(data_available=True, source="mock", freshness="MOCK"),
        cross_asset=CrossAssetSnapshot(data_available=True, source="mock", generated_at=_now().isoformat(), freshness="MOCK"),
        events=[_event(importance="HIGH", scheduled_at=(_now() + timedelta(minutes=38)).isoformat())],
        news=[_article()],
        sources=["mock"],
    )
    defaults.update(overrides)
    return MarketIntelligenceContext(**defaults)


def test_intelligence_summary_overall_available_when_all_categories_present():
    summary = q.build_intelligence_summary(_mi_context(), _now())
    assert summary.overall == "AVAILABLE"


def test_intelligence_summary_overall_unavailable_when_nothing_present():
    ctx = MarketIntelligenceContext(data_available=False, generated_at=_now().isoformat())
    summary = q.build_intelligence_summary(ctx, _now())
    assert summary.overall == "UNAVAILABLE"


def test_intelligence_summary_overall_partially_available_with_mixed_categories():
    ctx = _mi_context(cross_asset=None, events=[])
    summary = q.build_intelligence_summary(ctx, _now())
    assert summary.overall == "PARTIALLY_AVAILABLE"


def test_intelligence_summary_reports_relevant_news_count_not_raw_count():
    ctx = _mi_context(news=[
        _article(id="1", headline="Gold steadies as traders await Fed guidance"),
        _article(id="2", headline="Apple releases new iPhone color"),
    ])
    summary = q.build_intelligence_summary(ctx, _now())
    assert summary.relevant_news_count == 1


def test_intelligence_summary_nearest_high_impact_event_populated():
    ctx = _mi_context()
    summary = q.build_intelligence_summary(ctx, _now())
    assert summary.nearest_high_impact_event is not None
    assert summary.nearest_high_impact_event.minutes_until == 38


def test_intelligence_summary_no_numeric_confidence_score_field():
    """Structural guard against ever reintroducing an arbitrary numeric
    confidence score, per the spec's explicit prohibition."""
    import dataclasses
    field_names = {f.name for f in dataclasses.fields(q.IntelligenceSummary)}
    for banned in ("confidence", "score", "probability"):
        assert not any(banned in name for name in field_names)
