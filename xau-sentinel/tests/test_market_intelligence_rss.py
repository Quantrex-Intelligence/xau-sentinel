"""Tests for parse_rss(): valid feed parsing, malformed XML, empty input,
and headline-less items — all must degrade gracefully (never raise) since
this module has no control over what an external feed actually returns."""
from ai.market_intelligence.providers.rss import parse_rss

_VALID_FEED = """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <item>
      <title>Fed holds rates steady</title>
      <link>https://example.com/a</link>
      <pubDate>Mon, 28 Sep 2026 14:12:00 GMT</pubDate>
      <description>The Fed announced no change.</description>
    </item>
    <item>
      <title>Gold rallies on dollar weakness</title>
      <link>https://example.com/b</link>
      <pubDate>Tue, 29 Sep 2026 09:00:00 GMT</pubDate>
      <description>Gold prices rose.</description>
    </item>
  </channel>
</rss>"""


def test_parses_valid_feed_into_expected_fields():
    articles = parse_rss(_VALID_FEED, "test_source")
    assert len(articles) == 2
    first = articles[0]
    assert first["headline"] == "Fed holds rates steady"
    assert first["url"] == "https://example.com/a"
    assert first["summary"] == "The Fed announced no change."
    assert first["source"] == "test_source"
    assert first["published_at"] is not None
    assert first["published_at"].tzinfo is not None


def test_malformed_xml_returns_empty_list_not_a_raise():
    assert parse_rss("<rss><channel><item><title>unclosed", "test_source") == []


def test_empty_string_returns_empty_list():
    assert parse_rss("", "test_source") == []
    assert parse_rss("   ", "test_source") == []


def test_feed_with_no_items_returns_empty_list():
    xml = "<rss><channel><title>Empty</title></channel></rss>"
    assert parse_rss(xml, "test_source") == []


def test_item_without_title_is_skipped():
    xml = """<rss><channel>
      <item><link>https://example.com/no-title</link></item>
      <item><title>Has a title</title></item>
    </channel></rss>"""
    articles = parse_rss(xml, "test_source")
    assert len(articles) == 1
    assert articles[0]["headline"] == "Has a title"


def test_item_with_unparseable_pubdate_has_none_published_at():
    xml = """<rss><channel>
      <item><title>Bad date</title><pubDate>not a date</pubDate></item>
    </channel></rss>"""
    articles = parse_rss(xml, "test_source")
    assert articles[0]["published_at"] is None


def test_item_missing_optional_fields_defaults_to_none():
    xml = "<rss><channel><item><title>Bare item</title></item></channel></rss>"
    articles = parse_rss(xml, "test_source")
    assert articles[0]["url"] is None
    assert articles[0]["summary"] is None
