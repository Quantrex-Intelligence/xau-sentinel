"""Tests for the real Market Intelligence providers (Stage 11). All HTTP is
mocked at ai.market_intelligence.providers.http_client's get_json()/
get_text() — per the plan, these tests must never depend on a live external
website. Covers: success, partial failure, timeout, non-200, missing FRED
key, malformed JSON/response shape, duplicate news across feeds, stale
news, source metadata, freshness classification, and that caching actually
skips a second fetch within TTL."""
from datetime import datetime, timedelta, timezone

import httpx
import pytest

import config
from ai.market_intelligence.providers import real
from ai.market_intelligence.providers.real import (
    RealCrossAssetProvider, RealEventsProvider, RealMacroProvider, RealNewsProvider,
)

FRED_KEY = "test-fred-key"


def _fred_json(observations):
    """observations: list of (value, date) pairs, newest first (as FRED's
    sort_order=desc returns them)."""
    return {"observations": [{"value": v, "date": d} for v, d in observations]}


def _yahoo_json(price, previous_close):
    return {"chart": {"result": [{"meta": {"regularMarketPrice": price, "previousClose": previous_close}}]}}


FRED_SERIES = {
    "FEDFUNDS": [("5.25", "2026-09-01"), ("5.25", "2026-08-01")],
    "CPIAUCSL": [("3.10", "2026-09-01"), ("3.00", "2026-08-01")],
    "CPILFESL": [("2.90", "2026-09-01"), ("2.85", "2026-08-01")],
    "UNRATE": [("4.10", "2026-09-01"), ("4.00", "2026-08-01")],
    "GDPC1": [("2.50", "2026-09-01"), ("2.40", "2026-08-01")],
    "PPIACO": [("250.1", "2026-09-01"), ("249.0", "2026-08-01")],
    "DGS10": [("4.20", "2026-09-27"), ("4.18", "2026-09-26")],
    "DGS2": [("3.90", "2026-09-27"), ("3.88", "2026-09-26")],
}

YAHOO_SYMBOLS = {
    "DX-Y.NYB": (101.28, 100.50),
    "^VIX": (16.13, 16.00),
    "^GSPC": (5800.0, 5790.0),
    "SI=F": (30.5, 30.2),
}


def _make_fake_get_json(fred_series=None, yahoo_symbols=None, fail_series=None, releases=None):
    fred_series = fred_series or {}
    yahoo_symbols = yahoo_symbols or {}
    fail_series = fail_series or set()

    def fake_get_json(url, params=None, timeout=None):
        if "releases/dates" in url:
            return {"release_dates": releases or []}
        if "series/observations" in url:
            series_id = params["series_id"]
            if series_id in fail_series:
                raise httpx.ConnectError("boom", request=None)
            return _fred_json(fred_series.get(series_id, []))
        if "query1.finance.yahoo.com" in url:
            symbol = url.rsplit("/", 1)[-1]
            if symbol in fail_series:
                raise httpx.ConnectError("boom", request=None)
            price = yahoo_symbols.get(symbol)
            if price is None:
                return _yahoo_json(None, None)
            return _yahoo_json(*price)
        raise AssertionError(f"unexpected URL: {url}")

    return fake_get_json


# ---------------------------------------------------------------------------
# Macro
# ---------------------------------------------------------------------------

def test_macro_snapshot_unavailable_when_no_fred_key(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", "")
    snapshot = RealMacroProvider().get_macro_snapshot()
    assert snapshot.data_available is False
    assert "MARKET_INTEL_FRED_API_KEY" in snapshot.reason
    assert snapshot.freshness == "UNAVAILABLE"


def test_macro_snapshot_available_with_all_series_succeeding(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", FRED_KEY)
    monkeypatch.setattr(real.http_client, "get_json", _make_fake_get_json(fred_series=FRED_SERIES))

    snapshot = RealMacroProvider().get_macro_snapshot()
    assert snapshot.data_available is True
    assert snapshot.source == "real"
    assert snapshot.fed_funds_rate == 5.25
    assert snapshot.cpi_yoy == 3.10
    assert snapshot.us10y_yield == 4.20
    assert snapshot.freshness == "LIVE"


def test_fred_api_key_never_appears_in_the_snapshot_or_in_logs(monkeypatch, caplog):
    """FRED's key travels as a `params={"api_key": ...}` query param (real.py
    lines 81/299), the same category of leak risk VAL-036 already covers
    generically for every httpx request (log_safety.py pins httpx/httpcore
    to WARNING regardless of the root logger's own level, which is exactly
    what config.py/api/main.py's DEP-002-era logging fix raised) -- this
    proves the key doesn't leak through the two paths actually reachable
    from this app: the provider's own returned snapshot object, and
    anything logged during a real fetch."""
    secret = "sk-fred-secret-should-never-leak-anywhere"
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", secret)
    monkeypatch.setattr(real.http_client, "get_json", _make_fake_get_json(fred_series=FRED_SERIES))

    with caplog.at_level("DEBUG"):
        snapshot = RealMacroProvider().get_macro_snapshot()

    assert secret not in repr(snapshot)
    assert secret not in str(vars(snapshot))
    assert all(secret not in r.getMessage() for r in caplog.records)


def test_macro_snapshot_partial_failure_still_available(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", FRED_KEY)
    monkeypatch.setattr(
        real.http_client, "get_json",
        _make_fake_get_json(fred_series=FRED_SERIES, fail_series={"GDPC1", "PPIACO"}),
    )

    snapshot = RealMacroProvider().get_macro_snapshot()
    assert snapshot.data_available is True
    assert snapshot.fed_funds_rate == 5.25
    assert snapshot.gdp_growth_yoy is None


def test_macro_snapshot_unavailable_when_all_series_fail(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", FRED_KEY)
    monkeypatch.setattr(
        real.http_client, "get_json",
        _make_fake_get_json(fail_series=set(FRED_SERIES.keys())),
    )

    snapshot = RealMacroProvider().get_macro_snapshot()
    assert snapshot.data_available is False
    assert snapshot.reason == "FRED returned no usable data."
    assert snapshot.freshness == "UNAVAILABLE"


def test_macro_snapshot_skips_fred_missing_value_marker(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", FRED_KEY)
    series = dict(FRED_SERIES)
    series["FEDFUNDS"] = [(".", "2026-09-01"), ("5.00", "2026-08-01")]
    monkeypatch.setattr(real.http_client, "get_json", _make_fake_get_json(fred_series=series))

    snapshot = RealMacroProvider().get_macro_snapshot()
    assert snapshot.fed_funds_rate == 5.00


def test_macro_snapshot_non_200_response_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", FRED_KEY)

    def raise_status(*a, **k):
        raise httpx.HTTPStatusError("rate limited", request=None, response=None)

    monkeypatch.setattr(real.http_client, "get_json", raise_status)
    snapshot = RealMacroProvider().get_macro_snapshot()
    assert snapshot.data_available is False


def test_macro_snapshot_timeout_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", FRED_KEY)

    def raise_timeout(*a, **k):
        raise httpx.TimeoutException("timed out", request=None)

    monkeypatch.setattr(real.http_client, "get_json", raise_timeout)
    snapshot = RealMacroProvider().get_macro_snapshot()
    assert snapshot.data_available is False


def test_macro_snapshot_malformed_json_shape_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", FRED_KEY)
    monkeypatch.setattr(real.http_client, "get_json", lambda *a, **k: {"unexpected": "shape"})
    snapshot = RealMacroProvider().get_macro_snapshot()
    assert snapshot.data_available is False


# ---------------------------------------------------------------------------
# Gold fundamentals
# ---------------------------------------------------------------------------

def test_gold_fundamentals_computes_real_yield_and_usd_bias(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", FRED_KEY)
    monkeypatch.setattr(
        real.http_client, "get_json",
        _make_fake_get_json(fred_series=FRED_SERIES, yahoo_symbols=YAHOO_SYMBOLS),
    )

    gold = RealMacroProvider().get_gold_fundamentals()
    assert gold.data_available is True
    assert gold.real_yield_10y == round(4.20 - 3.10, 2)
    assert gold.usd_strength_bias == "STRONG"  # (101.28-100.50)/100.50*100 > 0.5
    assert gold.central_bank_demand_trend is None
    assert gold.etf_flows_trend is None


def test_gold_fundamentals_partial_when_no_fred_key_but_yahoo_available(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", "")
    monkeypatch.setattr(real.http_client, "get_json", _make_fake_get_json(yahoo_symbols=YAHOO_SYMBOLS))

    gold = RealMacroProvider().get_gold_fundamentals()
    assert gold.data_available is True
    assert gold.real_yield_10y is None
    assert gold.usd_strength_bias == "STRONG"


def test_gold_fundamentals_unavailable_when_nothing_succeeds(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", "")
    monkeypatch.setattr(real.http_client, "get_json", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("boom", request=None)))

    gold = RealMacroProvider().get_gold_fundamentals()
    assert gold.data_available is False
    assert "MARKET_INTEL_FRED_API_KEY" in gold.reason


def test_usd_strength_bias_neutral_within_threshold(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", "")
    monkeypatch.setattr(real.http_client, "get_json", _make_fake_get_json(yahoo_symbols={"DX-Y.NYB": (100.1, 100.0)}))
    gold = RealMacroProvider().get_gold_fundamentals()
    assert gold.usd_strength_bias == "NEUTRAL"


def test_usd_strength_bias_weak_below_negative_threshold(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", "")
    monkeypatch.setattr(real.http_client, "get_json", _make_fake_get_json(yahoo_symbols={"DX-Y.NYB": (99.0, 100.0)}))
    gold = RealMacroProvider().get_gold_fundamentals()
    assert gold.usd_strength_bias == "WEAK"


# ---------------------------------------------------------------------------
# Cross-asset
# ---------------------------------------------------------------------------

def test_cross_asset_snapshot_available_with_all_sources(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", FRED_KEY)
    monkeypatch.setattr(
        real.http_client, "get_json",
        _make_fake_get_json(fred_series=FRED_SERIES, yahoo_symbols=YAHOO_SYMBOLS),
    )

    snapshot = RealCrossAssetProvider().get_cross_asset_snapshot()
    assert snapshot.data_available is True
    assert snapshot.dxy == 101.28
    assert snapshot.vix == 16.13
    assert snapshot.equity_index == 5800.0
    assert snapshot.silver_price == 30.5
    assert snapshot.us10y_yield == 4.20
    assert snapshot.real_yield_10y == round(4.20 - 3.10, 2)
    assert snapshot.freshness == "LIVE"


def test_cross_asset_snapshot_partial_availability_is_acceptable(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", "")
    monkeypatch.setattr(real.http_client, "get_json", _make_fake_get_json(yahoo_symbols={"DX-Y.NYB": YAHOO_SYMBOLS["DX-Y.NYB"]}))

    snapshot = RealCrossAssetProvider().get_cross_asset_snapshot()
    assert snapshot.data_available is True
    assert snapshot.dxy == 101.28
    assert snapshot.vix is None
    assert snapshot.us10y_yield is None


def test_cross_asset_snapshot_unavailable_when_everything_fails(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", "")
    monkeypatch.setattr(real.http_client, "get_json", lambda *a, **k: (_ for _ in ()).throw(httpx.ConnectError("boom", request=None)))

    snapshot = RealCrossAssetProvider().get_cross_asset_snapshot()
    assert snapshot.data_available is False
    assert snapshot.freshness == "UNAVAILABLE"


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

def test_events_returns_empty_when_no_fred_key(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", "")
    events = RealEventsProvider().get_economic_events()
    assert events == []


def test_events_builds_named_events_with_actual_and_previous(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", FRED_KEY)
    today = datetime.now(timezone.utc).date().isoformat()
    series = {k: [(v[0][0], today), (v[1][0], today)] for k, v in FRED_SERIES.items()}
    monkeypatch.setattr(real.http_client, "get_json", _make_fake_get_json(fred_series=series))

    events = RealEventsProvider().get_economic_events(days_ahead=0, days_back=7)
    cpi_events = [e for e in events if e.name == "US CPI (YoY)"]
    assert len(cpi_events) == 1
    assert cpi_events[0].actual == "3.10%"
    assert cpi_events[0].previous == "3.00%"
    assert cpi_events[0].forecast is None
    assert cpi_events[0].source == "real"
    assert cpi_events[0].importance == "HIGH"


def test_events_excludes_observations_older_than_days_back(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", FRED_KEY)
    old_date = (datetime.now(timezone.utc) - timedelta(days=400)).date().isoformat()
    series = {"FEDFUNDS": [("5.25", old_date), ("5.20", old_date)]}
    monkeypatch.setattr(real.http_client, "get_json", _make_fake_get_json(fred_series=series))

    events = RealEventsProvider().get_economic_events(days_ahead=0, days_back=1)
    assert all(e.name != "Fed Funds Rate" for e in events)


def test_events_one_series_failing_does_not_affect_others(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", FRED_KEY)
    today = datetime.now(timezone.utc).date().isoformat()
    series = {k: [(v[0][0], today), (v[1][0], today)] for k, v in FRED_SERIES.items()}
    monkeypatch.setattr(
        real.http_client, "get_json",
        _make_fake_get_json(fred_series=series, fail_series={"UNRATE"}),
    )

    events = RealEventsProvider().get_economic_events(days_ahead=0, days_back=7)
    names = {e.name for e in events}
    assert "US Unemployment Rate" not in names
    assert "Fed Funds Rate" in names


def test_upcoming_release_dates_matched_by_keyword(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", FRED_KEY)
    future = (datetime.now(timezone.utc) + timedelta(days=3)).date().isoformat()
    releases = [
        {"release_id": 1, "release_name": "Employment Situation", "date": future},
        {"release_id": 2, "release_name": "Some Unrelated Release", "date": future},
    ]
    monkeypatch.setattr(real.http_client, "get_json", _make_fake_get_json(releases=releases))

    events = RealEventsProvider().get_economic_events(days_ahead=7, days_back=0)
    upcoming = [e for e in events if e.actual is None and e.name.startswith("US Non-Farm")]
    assert len(upcoming) == 1
    assert upcoming[0].forecast is None
    assert upcoming[0].previous is None


def test_upcoming_release_dates_skipped_when_days_ahead_zero(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", FRED_KEY)
    calls = []

    def fake_get_json(url, params=None, timeout=None):
        calls.append(url)
        if "releases/dates" in url:
            raise AssertionError("should not be called when days_ahead <= 0")
        return _fred_json([])

    monkeypatch.setattr(real.http_client, "get_json", fake_get_json)
    RealEventsProvider().get_economic_events(days_ahead=0, days_back=1)
    assert not any("releases/dates" in c for c in calls)


def test_upcoming_release_dates_failure_does_not_break_recent_events(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", FRED_KEY)
    today = datetime.now(timezone.utc).date().isoformat()

    def fake_get_json(url, params=None, timeout=None):
        if "releases/dates" in url:
            raise httpx.ConnectError("boom", request=None)
        return _fred_json([("5.25", today), ("5.20", today)])

    monkeypatch.setattr(real.http_client, "get_json", fake_get_json)
    events = RealEventsProvider().get_economic_events(days_ahead=7, days_back=7)
    assert any(e.name == "Fed Funds Rate" for e in events)


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------

_FED_RSS_XML = """<rss><channel>
  <item><title>Federal Reserve issues FOMC statement</title><link>https://fed.example/a</link>
    <pubDate>Mon, 28 Sep 2026 14:00:00 GMT</pubDate><description>Rate decision.</description></item>
</channel></rss>"""

_MARKETWATCH_RSS_XML = """<rss><channel>
  <item><title>Gold prices climb on Fed outlook</title><link>https://mw.example/a</link>
    <pubDate>Mon, 28 Sep 2026 15:00:00 GMT</pubDate><description>Gold rallied.</description></item>
  <item><title>Local sports team wins championship</title><link>https://mw.example/b</link>
    <pubDate>Mon, 28 Sep 2026 15:30:00 GMT</pubDate><description>Unrelated news.</description></item>
</channel></rss>"""


def _fake_get_text(fed_xml=_FED_RSS_XML, mw_xml=_MARKETWATCH_RSS_XML, fail=None):
    fail = fail or set()

    def fake_get_text(url, params=None, timeout=None):
        if "federalreserve.gov" in url:
            if "fed" in fail:
                raise httpx.ConnectError("boom", request=None)
            return fed_xml
        if "dowjones.io" in url:
            if "marketwatch" in fail:
                raise httpx.ConnectError("boom", request=None)
            return mw_xml
        raise AssertionError(f"unexpected URL: {url}")

    return fake_get_text


def test_news_combines_fed_and_relevant_marketwatch_articles(monkeypatch):
    monkeypatch.setattr(real.http_client, "get_text", _fake_get_text())
    articles = RealNewsProvider().get_recent_news(limit=10)

    headlines = {a.headline for a in articles}
    assert "Federal Reserve issues FOMC statement" in headlines
    assert "Gold prices climb on Fed outlook" in headlines
    assert "Local sports team wins championship" not in headlines


def test_news_fed_articles_tagged_high_importance_macro(monkeypatch):
    monkeypatch.setattr(real.http_client, "get_text", _fake_get_text())
    articles = RealNewsProvider().get_recent_news(limit=10)
    fed_article = next(a for a in articles if a.source == "federal_reserve")
    assert fed_article.importance == "HIGH"
    assert fed_article.category == "macro"
    assert "XAUUSD" in fed_article.assets


def test_news_marketwatch_articles_tagged_medium_importance(monkeypatch):
    monkeypatch.setattr(real.http_client, "get_text", _fake_get_text())
    articles = RealNewsProvider().get_recent_news(limit=10)
    mw_article = next(a for a in articles if a.source == "marketwatch")
    assert mw_article.importance == "MEDIUM"


def test_news_respects_limit(monkeypatch):
    monkeypatch.setattr(real.http_client, "get_text", _fake_get_text())
    articles = RealNewsProvider().get_recent_news(limit=1)
    assert len(articles) == 1


def test_news_one_feed_failing_does_not_affect_the_other(monkeypatch):
    monkeypatch.setattr(real.http_client, "get_text", _fake_get_text(fail={"fed"}))
    articles = RealNewsProvider().get_recent_news(limit=10)
    assert any(a.source == "marketwatch" for a in articles)
    assert not any(a.source == "federal_reserve" for a in articles)


def test_news_both_feeds_failing_returns_empty_list_not_a_raise(monkeypatch):
    monkeypatch.setattr(real.http_client, "get_text", _fake_get_text(fail={"fed", "marketwatch"}))
    articles = RealNewsProvider().get_recent_news(limit=10)
    assert articles == []


def test_news_malformed_xml_from_one_feed_degrades_gracefully(monkeypatch):
    monkeypatch.setattr(real.http_client, "get_text", _fake_get_text(fed_xml="<rss><channel><item><title>unclosed"))
    articles = RealNewsProvider().get_recent_news(limit=10)
    assert any(a.source == "marketwatch" for a in articles)


def test_news_article_has_stable_id_and_source_metadata(monkeypatch):
    monkeypatch.setattr(real.http_client, "get_text", _fake_get_text())
    articles = RealNewsProvider().get_recent_news(limit=10)
    for a in articles:
        assert a.id
        assert a.source
        assert a.retrieved_at
        assert a.published_at


# ---------------------------------------------------------------------------
# Caching: a second call within TTL must not re-invoke http_client
# ---------------------------------------------------------------------------

def test_macro_snapshot_caches_fred_calls_within_ttl(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", FRED_KEY)
    monkeypatch.setattr(config, "MARKET_INTEL_CACHE_TTL_MACRO_SECONDS", 3600)
    call_count = {"n": 0}
    fake = _make_fake_get_json(fred_series=FRED_SERIES)

    def counting_get_json(*a, **k):
        call_count["n"] += 1
        return fake(*a, **k)

    monkeypatch.setattr(real.http_client, "get_json", counting_get_json)

    RealMacroProvider().get_macro_snapshot()
    first_count = call_count["n"]
    RealMacroProvider().get_macro_snapshot()
    assert call_count["n"] == first_count  # second call served entirely from cache


def test_cross_asset_yahoo_calls_are_cached_within_ttl(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_FRED_API_KEY", "")
    monkeypatch.setattr(config, "MARKET_INTEL_CACHE_TTL_CROSS_ASSET_SECONDS", 3600)
    call_count = {"n": 0}
    fake = _make_fake_get_json(yahoo_symbols=YAHOO_SYMBOLS)

    def counting_get_json(*a, **k):
        call_count["n"] += 1
        return fake(*a, **k)

    monkeypatch.setattr(real.http_client, "get_json", counting_get_json)

    RealCrossAssetProvider().get_cross_asset_snapshot()
    first_count = call_count["n"]
    RealCrossAssetProvider().get_cross_asset_snapshot()
    assert call_count["n"] == first_count


def test_news_rss_fetch_is_cached_within_ttl(monkeypatch):
    monkeypatch.setattr(config, "MARKET_INTEL_CACHE_TTL_NEWS_SECONDS", 3600)
    call_count = {"n": 0}
    fake = _fake_get_text()

    def counting_get_text(*a, **k):
        call_count["n"] += 1
        return fake(*a, **k)

    monkeypatch.setattr(real.http_client, "get_text", counting_get_text)

    RealNewsProvider().get_recent_news(limit=10)
    first_count = call_count["n"]
    RealNewsProvider().get_recent_news(limit=10)
    assert call_count["n"] == first_count
