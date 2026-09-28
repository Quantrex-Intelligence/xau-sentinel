"""Offline, deterministic mock providers — the only concrete backends this
stage ships. Same technique as mt5/account.py's mock generators: a
per-calendar-day seed (np.random.default_rng, not Python's randomized
hash()) so values are stable within a day and change daily, never
presented as real data (every result carries source="mock", and every
synthetic headline/event name is explicitly tagged "[MOCK]").
"""
from datetime import datetime, timedelta, timezone
from typing import List

import numpy as np

from ai.market_intelligence.models import (
    CrossAssetSnapshot, EconomicEvent, GoldFundamentals, MacroSnapshot, NewsArticle,
)
from ai.market_intelligence.providers.base import (
    BaseCrossAssetProvider, BaseEventsProvider, BaseMacroProvider, BaseNewsProvider,
)


def _mock_seed(salt: str) -> int:
    return abs(hash((salt, "xau-sentinel-market-intelligence-mock"))) % (2**32)


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class MockMacroProvider(BaseMacroProvider):
    name = "mock"

    def get_macro_snapshot(self) -> MacroSnapshot:
        rng = np.random.default_rng(_mock_seed(f"macro-{_today()}"))
        return MacroSnapshot(
            data_available=True, source=self.name, generated_at=_now_iso(),
            fed_funds_rate=round(5.25 + float(rng.normal(0, 0.05)), 2),
            cpi_yoy=round(3.0 + float(rng.normal(0, 0.15)), 2),
            core_cpi_yoy=round(3.3 + float(rng.normal(0, 0.1)), 2),
            unemployment_rate=round(4.0 + float(rng.normal(0, 0.1)), 2),
            gdp_growth_yoy=round(2.1 + float(rng.normal(0, 0.2)), 2),
            us10y_yield=round(4.2 + float(rng.normal(0, 0.08)), 2),
            us2y_yield=round(4.5 + float(rng.normal(0, 0.08)), 2),
        )

    def get_gold_fundamentals(self) -> GoldFundamentals:
        macro = self.get_macro_snapshot()
        rng = np.random.default_rng(_mock_seed(f"gold-fundamentals-{_today()}"))
        real_yield = round(macro.us10y_yield - macro.cpi_yoy, 2) if (
            macro.us10y_yield is not None and macro.cpi_yoy is not None
        ) else None
        usd_bias = ["STRONG", "NEUTRAL", "WEAK"][int(rng.integers(0, 3))]
        demand_trend = ["ACCUMULATING", "NEUTRAL", "DISTRIBUTING"][int(rng.integers(0, 3))]
        flows_trend = ["INFLOWS", "NEUTRAL", "OUTFLOWS"][int(rng.integers(0, 3))]
        return GoldFundamentals(
            data_available=True, source=self.name, generated_at=_now_iso(),
            usd_strength_bias=usd_bias, real_yield_10y=real_yield,
            central_bank_demand_trend=demand_trend, etf_flows_trend=flows_trend,
        )


class MockCrossAssetProvider(BaseCrossAssetProvider):
    name = "mock"

    def get_cross_asset_snapshot(self) -> CrossAssetSnapshot:
        rng = np.random.default_rng(_mock_seed(f"cross-asset-{_today()}"))
        us10y = round(4.2 + float(rng.normal(0, 0.08)), 2)
        cpi_proxy = round(3.0 + float(rng.normal(0, 0.15)), 2)  # independent mock read, not shared state
        return CrossAssetSnapshot(
            data_available=True, source=self.name, generated_at=_now_iso(),
            dxy=round(104.0 + float(rng.normal(0, 0.6)), 2),
            us2y_yield=round(4.5 + float(rng.normal(0, 0.08)), 2),
            us10y_yield=us10y,
            real_yield_10y=round(us10y - cpi_proxy, 2),
            vix=round(max(8.0, 15.0 + float(rng.normal(0, 2.5))), 2),
            equity_index=round(5200.0 + float(rng.normal(0, 40)), 2),
            silver_price=round(30.0 + float(rng.normal(0, 0.8)), 2),
        )


_MOCK_EVENT_TEMPLATES = [
    ("[MOCK] US CPI (YoY)", "Inflation", "HIGH"),
    ("[MOCK] US Non-Farm Payrolls", "Employment", "HIGH"),
    ("[MOCK] FOMC Rate Decision", "Central Bank", "HIGH"),
    ("[MOCK] US Unemployment Rate", "Employment", "MEDIUM"),
    ("[MOCK] US GDP Growth Rate", "Growth", "MEDIUM"),
    ("[MOCK] US Retail Sales", "Growth", "LOW"),
]


class MockEventsProvider(BaseEventsProvider):
    name = "mock"

    def get_economic_events(self, days_ahead: int = 7, days_back: int = 1) -> List[EconomicEvent]:
        rng = np.random.default_rng(_mock_seed(f"events-{_today()}"))
        now = datetime.now(timezone.utc)
        events = []
        for i, (name, category, importance) in enumerate(_MOCK_EVENT_TEMPLATES):
            offset_days = float(rng.uniform(-days_back, days_ahead))
            scheduled_at = now + timedelta(days=offset_days)
            is_past = scheduled_at <= now
            forecast = round(float(rng.normal(3.0, 0.3)), 1)
            events.append(EconomicEvent(
                name=name, category=category, importance=importance,
                scheduled_at=scheduled_at.isoformat(), source=self.name,
                forecast=f"{forecast}%",
                actual=f"{round(forecast + float(rng.normal(0, 0.2)), 1)}%" if is_past else None,
                previous=f"{round(forecast - float(rng.normal(0, 0.2)), 1)}%",
            ))
        return sorted(events, key=lambda e: e.scheduled_at)


_MOCK_NEWS_TEMPLATES = [
    ("[MOCK] Gold steadies as traders await Fed guidance", "macro", "MEDIUM", ["XAUUSD", "USD"]),
    ("[MOCK] Dollar index edges higher on yield moves", "cross_asset", "LOW", ["DXY", "USD"]),
    ("[MOCK] Central bank gold buying trend continues", "fundamentals", "MEDIUM", ["XAUUSD"]),
    ("[MOCK] Markets digest latest inflation data", "macro", "HIGH", ["XAUUSD", "USD", "SPX"]),
]


class MockNewsProvider(BaseNewsProvider):
    name = "mock"

    def get_recent_news(self, limit: int = 10, max_age_hours: float = 48) -> List[NewsArticle]:
        rng = np.random.default_rng(_mock_seed(f"news-{_today()}"))
        now = datetime.now(timezone.utc)
        articles = []
        for headline, category, importance, assets in _MOCK_NEWS_TEMPLATES:
            age_hours = float(rng.uniform(0, max(1.0, max_age_hours)))
            published_at = now - timedelta(hours=age_hours)
            articles.append(NewsArticle(
                id=f"mock:{headline}", headline=headline, source="mock-wire",
                published_at=published_at.isoformat(), retrieved_at=now.isoformat(),
                url=None, category=category, importance=importance, assets=list(assets),
                summary=f"{headline} — offline mock summary, not a real news source.",
            ))
        return articles[:limit]
