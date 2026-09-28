"""Intelligence Quality Model (Stage 12) — hardens the Stage 9-11 Market
Intelligence pipeline before it feeds automated alerts/contextual AI
analysis. Pure functions and small dataclasses only; no HTTP, no caching,
no provider logic (that stays in providers/) — this module only VALIDATES
and CLASSIFIES what a provider already returned.

Explicit states throughout, never a numeric "confidence score" — the
spec's own instruction. Every state is one of a small, fixed set of
strings a human or the LLM can read directly:

    Freshness: LIVE | STALE | UNAVAILABLE | MOCK        (models.classify_freshness)
    Relevance: RELEVANT | NOT_RELEVANT | UNKNOWN          (news only — see below)
    EventStatus: NOT_RELEASED | RELEASED | NOT_AVAILABLE
    CategoryQuality.quality: GOOD | DEGRADED | UNAVAILABLE | MOCK

Relevance is a NEWS-only concept here: macro/gold-fundamentals/cross-asset/
events are tracked BECAUSE they are gold-relevant by category (that's the
entire reason they exist in this pipeline) — there is nothing to classify.
News comes from general-purpose feeds (MarketWatch in particular), so it is
the one category that can genuinely contain an irrelevant headline.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
from urllib.parse import urlparse

from ai.market_intelligence.models import (
    CrossAssetSnapshot, EconomicEvent, MarketIntelligenceContext, NewsArticle, classify_freshness,
)
from ai.market_intelligence.providers.dedup import dedupe_articles

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Small clock-skew allowance for "future" timestamps — not a tunable
# business parameter, a safety bound, so it stays an internal constant
# rather than a new config.py env var.
_MAX_FUTURE_SKEW_SECONDS = 5 * 60
_EARLIEST_PLAUSIBLE = datetime(2000, 1, 1, tzinfo=timezone.utc)

# Moved from providers/real.py (Stage 11) — single source of truth so the
# real news provider's own pre-filter and this module's post-hoc
# validation never drift apart into two different keyword lists.
RELEVANCE_KEYWORDS = [
    "gold", "fed", "federal reserve", "fomc", "inflation", "cpi", "treasury", "yield",
    "dollar", "interest rate", "employment", "jobs report", "unemployment", "gdp", "ppi", "powell",
]

_RELEVANT_ASSET_TAGS = {"XAUUSD"}

# The 4 categories both mock.py and real.py already use for economic
# events — not invented, just documented once. Used only to build the
# event-risk view's `assets` field (section 8); never stored on the model.
_EVENT_CATEGORY_ASSETS: Dict[str, List[str]] = {
    "Inflation": ["XAUUSD", "USD"],
    "Employment": ["XAUUSD", "USD"],
    "Growth": ["XAUUSD", "USD"],
    "Central Bank": ["XAUUSD", "USD", "US10Y", "US2Y"],
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Field-level validation
# ---------------------------------------------------------------------------

def is_valid_url(url: Optional[str]) -> bool:
    """None is valid — nothing to check, not a failure (most mock articles
    and some real ones legitimately have no URL). A present URL must be an
    absolute http(s) URL."""
    if url is None:
        return True
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def is_plausible_timestamp(dt: Optional[datetime], now: Optional[datetime] = None) -> bool:
    """Rejects timestamps more than a few minutes in the future (allowing
    small clock skew) or implausibly ancient — never raises, None is not
    plausible (nothing to judge)."""
    if dt is None:
        return False
    now = now or _now()
    if dt > now.replace(microsecond=0) and (dt - now).total_seconds() > _MAX_FUTURE_SKEW_SECONDS:
        return False
    if dt < _EARLIEST_PLAUSIBLE:
        return False
    return True


def units_consistent(actual: Optional[str], previous: Optional[str]) -> bool:
    """actual/previous are pre-formatted, unit-tagged strings (see
    providers/real.py::_format_units) — both should carry a '%' suffix or
    neither should. Trivially consistent when either side is absent (there
    is nothing to compare)."""
    if actual is None or previous is None:
        return True
    return actual.strip().endswith("%") == previous.strip().endswith("%")


# ---------------------------------------------------------------------------
# News relevance + quality
# ---------------------------------------------------------------------------

def classify_news_relevance(
    headline: str, summary: Optional[str] = None,
    category: Optional[str] = None, assets: Optional[List[str]] = None,
) -> str:
    """RELEVANT/NOT_RELEVANT/UNKNOWN — never automatically RELEVANT just
    because a headline is financial in general (the spec's explicit "do
    not allow generic financial headlines to automatically become XAUUSD-
    relevant" rule)."""
    if assets and _RELEVANT_ASSET_TAGS.intersection(assets):
        return "RELEVANT"

    haystack = f"{headline or ''} {summary or ''}".strip().lower()
    if not haystack:
        return "UNKNOWN"
    if any(kw in haystack for kw in RELEVANCE_KEYWORDS):
        return "RELEVANT"
    return "NOT_RELEVANT"


@dataclass
class NewsQuality:
    article: NewsArticle
    url_valid: bool
    timestamp_valid: bool
    relevance: str
    freshness: str  # "LIVE" | "STALE" | "UNAVAILABLE"


def validate_news_article(article: NewsArticle, now: Optional[datetime] = None,
                           max_age_hours: float = 48) -> NewsQuality:
    now = now or _now()
    published = _parse_iso(article.published_at)
    timestamp_valid = is_plausible_timestamp(published, now)

    if published is None:
        freshness = "UNAVAILABLE"
    else:
        age_hours = (now - published).total_seconds() / 3600
        freshness = "LIVE" if 0 <= age_hours <= max_age_hours else "STALE"

    return NewsQuality(
        article=article, url_valid=is_valid_url(article.url), timestamp_valid=timestamp_valid,
        relevance=classify_news_relevance(article.headline, article.summary, article.category, article.assets),
        freshness=freshness,
    )


def assess_news_quality(articles: List[NewsArticle], now: Optional[datetime] = None,
                         max_age_hours: float = 48) -> List[NewsQuality]:
    """THE single place that decides which news articles are trustworthy
    enough to reach the rest of the pipeline: dedupe (by content, see
    providers/dedup.py — deterministic, never an LLM), drop implausible/
    future timestamps, drop stale ones, drop confirmed-irrelevant ones.
    Both ai/market_intelligence/context.py and
    ai/tools/market_intelligence_tools.py call through this so the two
    paths can never disagree about what counts as "current, relevant
    news" again."""
    now = now or _now()
    deduped = dedupe_articles(articles)

    kept: List[NewsQuality] = []
    for article in deduped:
        quality = validate_news_article(article, now, max_age_hours)
        if not quality.timestamp_valid:
            continue
        if quality.freshness == "STALE":
            continue
        if quality.relevance == "NOT_RELEVANT":
            continue
        kept.append(quality)
    return kept


# ---------------------------------------------------------------------------
# Economic event quality
# ---------------------------------------------------------------------------

def classify_event_status(event: EconomicEvent, now: Optional[datetime] = None) -> str:
    """RELEASED when we have an actual value, regardless of schedule drift.
    NOT_RELEASED when the scheduled time hasn't arrived yet — no actual is
    expected. NOT_AVAILABLE when the scheduled time has passed but we still
    have no actual — a real, meaningful state (e.g. a source's release
    lag), never silently treated the same as "hasn't happened yet"."""
    if event.actual is not None:
        return "RELEASED"
    now = now or _now()
    scheduled = _parse_iso(event.scheduled_at)
    if scheduled is not None and scheduled > now:
        return "NOT_RELEASED"
    return "NOT_AVAILABLE"


@dataclass
class EventQuality:
    event: EconomicEvent
    timestamp_valid: bool
    name_valid: bool
    importance_valid: bool
    country_valid: bool
    units_consistent: bool
    status: str  # NOT_RELEASED | RELEASED | NOT_AVAILABLE


def validate_event(event: EconomicEvent, now: Optional[datetime] = None) -> EventQuality:
    now = now or _now()
    scheduled = _parse_iso(event.scheduled_at)
    return EventQuality(
        event=event,
        timestamp_valid=is_plausible_timestamp(scheduled, now),
        name_valid=bool(event.name and event.name.strip()),
        importance_valid=event.importance in ("HIGH", "MEDIUM", "LOW"),
        country_valid=bool(event.country and event.country.strip()),
        units_consistent=units_consistent(event.actual, event.previous),
        status=classify_event_status(event, now),
    )


@dataclass
class EventRiskItem:
    event: str
    importance: str
    event_time: str
    status: str  # "UPCOMING" | "RELEASED" | "NOT_AVAILABLE"
    minutes_until: int
    assets: List[str]
    source: str


def build_event_risk_context(events: List[EconomicEvent], now: Optional[datetime] = None) -> List[EventRiskItem]:
    """A concise, structured view of event RISK (proximity + importance),
    never a prediction of the event's outcome — no forecast value is
    computed or guessed here, only timing and known metadata."""
    now = now or _now()
    items: List[EventRiskItem] = []
    for event in events:
        scheduled = _parse_iso(event.scheduled_at)
        if scheduled is None:
            continue
        minutes_until = round((scheduled - now).total_seconds() / 60)
        data_status = classify_event_status(event, now)
        status = "UPCOMING" if minutes_until >= 0 else data_status
        items.append(EventRiskItem(
            event=event.name, importance=event.importance, event_time=event.scheduled_at,
            status=status, minutes_until=minutes_until,
            assets=_EVENT_CATEGORY_ASSETS.get(event.category, ["XAUUSD"]),
            source=event.source,
        ))
    return sorted(items, key=lambda i: abs(i.minutes_until))


# ---------------------------------------------------------------------------
# Cross-asset per-field quality
# ---------------------------------------------------------------------------

@dataclass
class FieldQuality:
    field: str
    value: Optional[float]
    freshness: str  # "LIVE" | "STALE" | "UNAVAILABLE" | "MOCK" — see the module docstring's scope note


_CROSS_ASSET_FIELDS = ("dxy", "us10y_yield", "us2y_yield", "vix", "equity_index", "silver_price")


def classify_cross_asset_field_quality(snapshot: Optional[CrossAssetSnapshot]) -> List[FieldQuality]:
    """Per-field AVAILABLE vs UNAVAILABLE (a field is UNAVAILABLE when its
    value is None, independent of the others — Stage 11's "partial
    availability is acceptable" made real here at the field level).
    STALE/LIVE is inherited from the snapshot's own freshness for whatever
    fields ARE available: true per-field staleness divergence would need
    per-field cache timestamps threaded out of providers/real.py's private
    Yahoo/FRED calls, which this stage intentionally does not add (see the
    module docstring)."""
    if snapshot is None:
        return [FieldQuality(field=f, value=None, freshness="UNAVAILABLE") for f in _CROSS_ASSET_FIELDS]

    result = []
    for name in _CROSS_ASSET_FIELDS:
        value = getattr(snapshot, name, None)
        freshness = snapshot.freshness if value is not None else "UNAVAILABLE"
        result.append(FieldQuality(field=name, value=value, freshness=freshness))
    return result


# ---------------------------------------------------------------------------
# Category quality + overall intelligence summary
# ---------------------------------------------------------------------------

@dataclass
class CategoryQuality:
    category: str
    available: bool
    freshness: str
    source: Optional[str]
    timestamp: Optional[str]
    relevance: str  # RELEVANT for every category except news (see module docstring)
    quality: str = field(init=False)  # GOOD | DEGRADED | UNAVAILABLE | MOCK — derived, never a new signal

    def __post_init__(self):
        if self.freshness == "MOCK":
            self.quality = "MOCK"
        elif not self.available:
            self.quality = "UNAVAILABLE"
        elif self.freshness == "STALE":
            self.quality = "DEGRADED"
        else:
            self.quality = "GOOD"


def category_quality(category: str, available: bool, freshness: str, source: Optional[str],
                      timestamp: Optional[str], relevance: str = "RELEVANT") -> CategoryQuality:
    return CategoryQuality(
        category=category, available=available, freshness=freshness,
        source=source, timestamp=timestamp, relevance=relevance,
    )


@dataclass
class IntelligenceSummary:
    macro: CategoryQuality
    gold_fundamentals: CategoryQuality
    cross_asset: CategoryQuality
    events: CategoryQuality
    news: CategoryQuality
    nearest_high_impact_event: Optional[EventRiskItem]
    relevant_news_count: int
    overall: str  # AVAILABLE | PARTIALLY_AVAILABLE | UNAVAILABLE


def build_intelligence_summary(ctx: MarketIntelligenceContext, now: Optional[datetime] = None) -> IntelligenceSummary:
    """Answers "what important external information is currently
    available?" deterministically — no numeric confidence score, only the
    explicit per-category states plus a categorical rollup."""
    now = now or _now()

    macro_q = category_quality(
        "macro", bool(ctx.macro and ctx.macro.data_available),
        ctx.macro.freshness if ctx.macro else "UNAVAILABLE",
        ctx.macro.source if ctx.macro else None, ctx.macro.generated_at if ctx.macro else None,
    )
    gold_q = category_quality(
        "gold_fundamentals", bool(ctx.gold_fundamentals and ctx.gold_fundamentals.data_available),
        ctx.gold_fundamentals.freshness if ctx.gold_fundamentals else "UNAVAILABLE",
        ctx.gold_fundamentals.source if ctx.gold_fundamentals else None,
        ctx.gold_fundamentals.generated_at if ctx.gold_fundamentals else None,
    )
    cross_q = category_quality(
        "cross_asset", bool(ctx.cross_asset and ctx.cross_asset.data_available),
        ctx.cross_asset.freshness if ctx.cross_asset else "UNAVAILABLE",
        ctx.cross_asset.source if ctx.cross_asset else None, ctx.cross_asset.generated_at if ctx.cross_asset else None,
    )

    high_events = [e for e in ctx.events if e.importance == "HIGH"]
    events_q = category_quality(
        "events", bool(ctx.events),
        "LIVE" if ctx.events and ctx.events[0].source != "mock" else ("MOCK" if ctx.events else "UNAVAILABLE"),
        ctx.events[0].source if ctx.events else None, None,
    )

    relevant_news = [n for n in ctx.news if classify_news_relevance(n.headline, n.summary, n.category, n.assets) == "RELEVANT"]
    news_q = category_quality(
        "news", bool(ctx.news),
        "LIVE" if ctx.news and ctx.news[0].source not in ("mock", "mock-wire") else ("MOCK" if ctx.news else "UNAVAILABLE"),
        ctx.news[0].source if ctx.news else None, ctx.news[0].retrieved_at if ctx.news else None,
        relevance="RELEVANT" if relevant_news else ("UNKNOWN" if not ctx.news else "NOT_RELEVANT"),
    )

    risk_items = build_event_risk_context(high_events, now)
    nearest = next((i for i in risk_items if i.status == "UPCOMING"), None) or (risk_items[0] if risk_items else None)

    available_count = sum(q.available for q in (macro_q, cross_q, events_q, news_q))
    if available_count == 0:
        overall = "UNAVAILABLE"
    elif available_count == 4:
        overall = "AVAILABLE"
    else:
        overall = "PARTIALLY_AVAILABLE"

    return IntelligenceSummary(
        macro=macro_q, gold_fundamentals=gold_q, cross_asset=cross_q, events=events_q, news=news_q,
        nearest_high_impact_event=nearest, relevant_news_count=len(relevant_news), overall=overall,
    )
