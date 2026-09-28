"""Pydantic contracts for the Market Intelligence layer — typed mirrors of
what ai/market_intelligence/context.py and the providers already produce,
never a place new data gets invented."""
from typing import List, Optional

from pydantic import BaseModel


class MacroSnapshotOut(BaseModel):
    data_available: bool
    source: str
    generated_at: Optional[str] = None
    fed_funds_rate: Optional[float] = None
    cpi_yoy: Optional[float] = None
    core_cpi_yoy: Optional[float] = None
    unemployment_rate: Optional[float] = None
    gdp_growth_yoy: Optional[float] = None
    us10y_yield: Optional[float] = None
    us2y_yield: Optional[float] = None
    reason: Optional[str] = None
    freshness: str = "UNAVAILABLE"


class GoldFundamentalsOut(BaseModel):
    data_available: bool
    source: str
    generated_at: Optional[str] = None
    usd_strength_bias: Optional[str] = None
    real_yield_10y: Optional[float] = None
    central_bank_demand_trend: Optional[str] = None
    etf_flows_trend: Optional[str] = None
    reason: Optional[str] = None
    freshness: str = "UNAVAILABLE"


class CrossAssetSnapshotOut(BaseModel):
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


class EconomicEventOut(BaseModel):
    name: str
    category: str
    importance: str
    scheduled_at: str
    source: str
    actual: Optional[str] = None
    forecast: Optional[str] = None
    previous: Optional[str] = None
    country: Optional[str] = None


class NewsArticleOut(BaseModel):
    id: str
    headline: str
    source: str
    published_at: str
    retrieved_at: str
    url: Optional[str] = None
    category: Optional[str] = None
    importance: Optional[str] = None
    assets: List[str] = []
    summary: Optional[str] = None


class MarketIntelligenceContextOut(BaseModel):
    data_available: bool
    generated_at: str
    macro: Optional[MacroSnapshotOut] = None
    gold_fundamentals: Optional[GoldFundamentalsOut] = None
    cross_asset: Optional[CrossAssetSnapshotOut] = None
    events: List[EconomicEventOut] = []
    news: List[NewsArticleOut] = []
    sources: List[str] = []
