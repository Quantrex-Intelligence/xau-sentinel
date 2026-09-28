"""Tests for ai/market_intelligence/providers/news.py's normalization/
dedup helpers, and ai/market_intelligence/context.py's staleness filtering
— the concrete mechanisms behind "deduplication by stable identifier" and
"do not store every article indefinitely"."""
from datetime import datetime, timedelta, timezone

from ai.market_intelligence.context import _get_news
from ai.market_intelligence.models import NewsArticle
from ai.market_intelligence.providers.news import dedupe_articles, stable_id


def _article(**overrides):
    now = datetime.now(timezone.utc)
    defaults = dict(
        id="raw-id-1", headline="Gold steadies as traders await Fed guidance", source="wire-a",
        published_at=now.isoformat(), retrieved_at=now.isoformat(), url=None,
    )
    defaults.update(overrides)
    return NewsArticle(**defaults)


def test_stable_id_is_identical_for_the_same_headline_and_source_regardless_of_raw_id():
    a = _article(id="raw-1")
    b = _article(id="raw-2")  # different provider-assigned id, same content
    assert stable_id(a) == stable_id(b)


def test_stable_id_is_case_and_whitespace_insensitive():
    a = _article(headline="Gold steadies as traders await Fed guidance")
    b = _article(headline="  GOLD STEADIES AS TRADERS   AWAIT FED GUIDANCE  ")
    assert stable_id(a) == stable_id(b)


def test_stable_id_differs_for_different_headlines():
    a = _article(headline="Gold steadies as traders await Fed guidance")
    b = _article(headline="Dollar index edges higher on yield moves")
    assert stable_id(a) != stable_id(b)


def test_stable_id_prefers_normalized_url_when_present():
    a = _article(url="https://example.com/story?utm=1", headline="Headline A")
    b = _article(url="https://example.com/story?utm=1", headline="Headline B — different text")
    assert stable_id(a) == stable_id(b)  # same URL -> same story, even with different headline text


def test_dedupe_articles_keeps_first_occurrence_only():
    first = _article(id="1", headline="Same story", retrieved_at="2026-01-01T00:00:00+00:00")
    duplicate = _article(id="2", headline="Same story", retrieved_at="2026-01-02T00:00:00+00:00")
    unrelated = _article(id="3", headline="A totally different story")

    deduped = dedupe_articles([first, duplicate, unrelated])

    assert len(deduped) == 2
    assert deduped[0].id == "1"  # first occurrence wins
    assert {a.id for a in deduped} == {"1", "3"}


def test_dedupe_articles_handles_an_empty_list():
    assert dedupe_articles([]) == []


# ---------------------------------------------------------------------------
# Staleness filtering (context.py)
# ---------------------------------------------------------------------------

def test_get_news_filters_out_articles_older_than_max_age_hours(monkeypatch):
    now = datetime.now(timezone.utc)
    fresh = _article(id="fresh", published_at=now.isoformat())
    stale = _article(id="stale", published_at=(now - timedelta(hours=100)).isoformat())

    class _FakeProvider:
        def get_recent_news(self, limit, max_age_hours):
            return [fresh, stale]

    import ai.market_intelligence.context as context_mod
    monkeypatch.setattr(context_mod, "get_news_provider", lambda: _FakeProvider())

    result = _get_news(limit=10, max_age_hours=48)
    ids = {a.id for a in result}
    assert "fresh" in ids
    assert "stale" not in ids


def test_get_news_dedupes_across_the_staleness_filter(monkeypatch):
    now = datetime.now(timezone.utc)
    first = _article(id="1", headline="Gold rallies on Fed guidance", published_at=now.isoformat())
    dup = _article(id="2", headline="Gold rallies on Fed guidance", published_at=now.isoformat())

    class _FakeProvider:
        def get_recent_news(self, limit, max_age_hours):
            return [first, dup]

    import ai.market_intelligence.context as context_mod
    monkeypatch.setattr(context_mod, "get_news_provider", lambda: _FakeProvider())

    result = _get_news(limit=10, max_age_hours=48)
    assert len(result) == 1


def test_get_news_excludes_articles_not_relevant_to_xauusd(monkeypatch):
    now = datetime.now(timezone.utc)
    relevant = _article(id="1", headline="Gold steadies as traders await Fed guidance", published_at=now.isoformat())
    irrelevant = _article(id="2", headline="Apple releases new iPhone color", published_at=now.isoformat())

    class _FakeProvider:
        def get_recent_news(self, limit, max_age_hours):
            return [relevant, irrelevant]

    import ai.market_intelligence.context as context_mod
    monkeypatch.setattr(context_mod, "get_news_provider", lambda: _FakeProvider())

    result = _get_news(limit=10, max_age_hours=48)
    ids = {a.id for a in result}
    assert "1" in ids
    assert "2" not in ids
