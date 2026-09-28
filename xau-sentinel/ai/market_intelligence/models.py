"""Data shapes for the Market Intelligence layer. Pure data — no provider,
retrieval, or context-assembly logic lives here.

Every dataclass carries `data_available` and `source` (never fabricated —
a provider that has nothing returns data_available=False, not a guess),
and every time-sensitive field has an explicit timestamp string (ISO 8601,
UTC) so staleness is always checkable rather than implied.

Stage 11: the three snapshot types also carry `freshness` (LIVE/STALE/
UNAVAILABLE/MOCK) via classify_freshness() below — the UI's at-a-glance
status badge, so the user always knows whether Sentinel is looking at real
or mock information, and whether "real" is actually current.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional


def classify_freshness(data_available: bool, source: str, generated_at: Optional[str],
                        stale_after_seconds: float) -> str:
    """MOCK takes priority over everything else — a mock value is never
    "live" no matter how recent its timestamp. UNAVAILABLE means the
    provider had nothing. Otherwise STALE once `generated_at` is older
    than `stale_after_seconds`, else LIVE. Never raises — an unparseable
    or missing timestamp on an otherwise-available result is treated as
    STALE (freshness can't be confirmed, so it's not claimed)."""
    if source == "mock":
        return "MOCK"
    if not data_available:
        return "UNAVAILABLE"
    if not generated_at:
        return "STALE"
    try:
        generated = datetime.fromisoformat(generated_at)
        if generated.tzinfo is None:
            generated = generated.replace(tzinfo=timezone.utc)
    except ValueError:
        return "STALE"
    age_seconds = (datetime.now(timezone.utc) - generated).total_seconds()
    return "LIVE" if age_seconds <= stale_after_seconds else "STALE"


@dataclass
class MacroSnapshot:
    data_available: bool
    source: str  # "mock" | (a future real provider's name)
    generated_at: Optional[str] = None
    fed_funds_rate: Optional[float] = None
    cpi_yoy: Optional[float] = None
    core_cpi_yoy: Optional[float] = None
    unemployment_rate: Optional[float] = None
    gdp_growth_yoy: Optional[float] = None
    us10y_yield: Optional[float] = None
    us2y_yield: Optional[float] = None
    reason: Optional[str] = None  # set when data_available is False
    freshness: str = "UNAVAILABLE"  # "LIVE" | "STALE" | "UNAVAILABLE" | "MOCK" — see classify_freshness()


@dataclass
class GoldFundamentals:
    """Derived alongside (never duplicating) MacroSnapshot — real_yield_10y
    is computed as us10y_yield - cpi_yoy from the SAME macro snapshot, an
    explicit cross-reference rather than a second, independently-guessed
    number."""
    data_available: bool
    source: str
    generated_at: Optional[str] = None
    usd_strength_bias: Optional[str] = None  # "STRONG" | "NEUTRAL" | "WEAK"
    real_yield_10y: Optional[float] = None
    central_bank_demand_trend: Optional[str] = None  # "ACCUMULATING" | "NEUTRAL" | "DISTRIBUTING"
    etf_flows_trend: Optional[str] = None  # "INFLOWS" | "NEUTRAL" | "OUTFLOWS"
    reason: Optional[str] = None
    freshness: str = "UNAVAILABLE"


@dataclass
class CrossAssetSnapshot:
    data_available: bool
    source: str
    generated_at: Optional[str] = None
    dxy: Optional[float] = None
    us2y_yield: Optional[float] = None
    us10y_yield: Optional[float] = None
    real_yield_10y: Optional[float] = None
    vix: Optional[float] = None
    equity_index: Optional[float] = None
    silver_price: Optional[float] = None
    reason: Optional[str] = None
    freshness: str = "UNAVAILABLE"


@dataclass
class EconomicEvent:
    name: str
    category: str  # e.g. "Inflation" | "Employment" | "Central Bank" | "Growth"
    importance: str  # "HIGH" | "MEDIUM" | "LOW"
    scheduled_at: str
    source: str
    actual: Optional[str] = None
    forecast: Optional[str] = None
    previous: Optional[str] = None


@dataclass
class NewsArticle:
    id: str  # stable identifier — see providers/news.py::_stable_id()
    headline: str
    source: str
    published_at: str
    retrieved_at: str
    url: Optional[str] = None
    category: Optional[str] = None
    importance: Optional[str] = None
    assets: List[str] = field(default_factory=list)
    summary: Optional[str] = None


@dataclass
class MarketIntelligenceContext:
    data_available: bool
    generated_at: str
    macro: Optional[MacroSnapshot] = None
    gold_fundamentals: Optional[GoldFundamentals] = None
    cross_asset: Optional[CrossAssetSnapshot] = None
    events: List[EconomicEvent] = field(default_factory=list)
    news: List[NewsArticle] = field(default_factory=list)
    sources: List[str] = field(default_factory=list)
