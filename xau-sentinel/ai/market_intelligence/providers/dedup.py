"""News normalization/deduplication — split out from news.py (Stage 11) so
both the news factory (news.py) and the real news provider (real.py, which
needs stable_id() to assign each article's id) can depend on this without
a circular import between them. news.py re-exports these names unchanged
for backward compatibility with every existing caller/test.

Dedupes by a stable identifier derived from CONTENT (normalized URL, or
normalized headline + source when no URL exists), not by trusting each
provider's own `id` field, since two different providers reporting the
same real-world story would carry different internal ids.
"""
import hashlib
import re
from typing import List

from ai.market_intelligence.models import NewsArticle

_WHITESPACE_RE = re.compile(r"\s+")


def _normalize(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text.strip().lower())


def stable_id(article: NewsArticle) -> str:
    """A content-derived key — hashlib (stable across processes), never
    Python's randomized hash(). Two articles with the same normalized URL,
    or the same normalized headline+source when neither has a URL, are
    treated as the same story regardless of which provider reported it or
    what internal id it carried. Each part is normalized BEFORE joining —
    normalizing the already-concatenated string would leave a stray space
    after the separator whenever the headline itself had leading
    whitespace, silently producing a different key for what should hash
    identically."""
    if article.url:
        basis = _normalize(article.url)
    else:
        basis = f"{_normalize(article.source)}:{_normalize(article.headline)}"
    return hashlib.blake2b(basis.encode("utf-8"), digest_size=16).hexdigest()


def dedupe_articles(articles: List[NewsArticle]) -> List[NewsArticle]:
    """Keeps the first occurrence of each stable_id, in input order."""
    seen = set()
    deduped = []
    for article in articles:
        key = stable_id(article)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(article)
    return deduped
