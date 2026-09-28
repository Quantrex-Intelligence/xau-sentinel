"""RSS 2.0 parsing — stdlib xml.etree.ElementTree only, no new dependency.
Malformed or empty XML degrades to [] rather than raising, the same
"no exceptions for no data" contract every other provider follows.
"""
import xml.etree.ElementTree as ET
from typing import List, Optional

from ai.market_intelligence.providers.timeutil import parse_timestamp


def parse_rss(xml_text: str, source_name: str) -> List[dict]:
    """Returns a list of {"headline", "url", "published_at" (a parsed,
    tz-aware datetime or None), "summary", "source"} dicts — the raw
    material ai/market_intelligence/providers/real.py turns into
    NewsArticle objects. A headline-less <item> is skipped (not a usable
    article); nothing here fabricates a missing field."""
    if not xml_text or not xml_text.strip():
        return []

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    articles = []
    for item in root.findall("./channel/item"):
        headline = _text(item, "title")
        if not headline:
            continue
        articles.append({
            "headline": headline,
            "url": _text(item, "link"),
            "published_at": parse_timestamp(_text(item, "pubDate")),
            "summary": _text(item, "description"),
            "source": source_name,
        })
    return articles


def _text(item: ET.Element, tag: str) -> Optional[str]:
    el = item.find(tag)
    if el is None or el.text is None:
        return None
    stripped = el.text.strip()
    return stripped or None
