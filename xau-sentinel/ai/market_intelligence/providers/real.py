"""Real, free-first Market Intelligence providers (Stage 11) — one class
per existing ABC, mirroring mock.py's exact shape. Every external call is
independently wrapped: a missing MARKET_INTEL_FRED_API_KEY, an HTTP error,
a malformed response, or a rate limit all degrade to data_available=False
with an explicit reason, never a crash and never a fabricated value.

Sources used (see the Stage 11 plan for how each was verified live):
- FRED (api.stlouisfed.org) — official U.S. government economic data.
  Needs a free, self-service API key (MARKET_INTEL_FRED_API_KEY). Used for
  every macro figure, Treasury yields, and recent/upcoming economic events.
- Yahoo Finance's public chart JSON endpoint — unauthenticated, no key.
  Used for DXY, VIX, S&P 500, and silver, where FRED has no equivalent
  daily-enough series.
- Federal Reserve's own RSS (federalreserve.gov/feeds/press_monetary.xml)
  and MarketWatch's top-stories RSS, filtered by a gold/macro keyword list.

stooq.com was evaluated and rejected: it now serves an active JavaScript
proof-of-work anti-bot challenge, which is explicitly an access restriction
this project must not bypass.
"""
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

import config
from ai.market_intelligence.models import (
    CrossAssetSnapshot, EconomicEvent, GoldFundamentals, MacroSnapshot, NewsArticle, classify_freshness,
)
from ai.market_intelligence.providers import cache, http_client, rss
from ai.market_intelligence.providers.dedup import stable_id
from ai.market_intelligence.providers.base import (
    BaseCrossAssetProvider, BaseEventsProvider, BaseMacroProvider, BaseNewsProvider,
)
from ai.market_intelligence.providers.timeutil import parse_timestamp
from ai.market_intelligence.quality import classify_news_relevance

_FRED_BASE = "https://api.stlouisfed.org/fred"
_YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
_FED_RSS = "https://www.federalreserve.gov/feeds/press_monetary.xml"
_MARKETWATCH_RSS = "https://feeds.content.dowjones.io/public/rss/mw_topstories"

_TRACKED_EVENT_SERIES = [
    # (series_id, name, category, importance, fred `units` param)
    ("CPIAUCSL", "US CPI (YoY)", "Inflation", "HIGH", "pc1"),
    ("CPILFESL", "US Core CPI (YoY)", "Inflation", "HIGH", "pc1"),
    ("PAYEMS", "US Non-Farm Payrolls", "Employment", "HIGH", "lin"),
    ("UNRATE", "US Unemployment Rate", "Employment", "HIGH", "lin"),
    ("GDPC1", "US GDP Growth (YoY)", "Growth", "MEDIUM", "pc1"),
    ("PPIACO", "US Producer Price Index", "Inflation", "MEDIUM", "lin"),
    ("FEDFUNDS", "Fed Funds Rate", "Central Bank", "HIGH", "lin"),
]

_UPCOMING_RELEASE_KEYWORDS = {
    "Employment Situation": ("US Non-Farm Payrolls / Unemployment", "Employment", "HIGH"),
    "Consumer Price Index": ("US CPI", "Inflation", "HIGH"),
    "Gross Domestic Product": ("US GDP", "Growth", "MEDIUM"),
    "Producer Price Index": ("US PPI", "Inflation", "MEDIUM"),
    "Federal Open Market Committee": ("FOMC Meeting", "Central Bank", "HIGH"),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# FRED — shared by the macro, gold-fundamentals, cross-asset, and events
# providers below, so yields/CPI are only ever fetched (and cached) once.
# ---------------------------------------------------------------------------

def _fred_observations(series_id: str, units: str = "lin", limit: int = 2) -> List[Tuple[float, str]]:
    """Up to `limit` most recent (value, date) pairs, skipping FRED's "."
    missing-value marker. Returns [] on any failure — no API key, HTTP
    error, or malformed response — never raises."""
    if not config.MARKET_INTEL_FRED_API_KEY:
        return []

    def _fetch():
        return http_client.get_json(
            f"{_FRED_BASE}/series/observations",
            params={
                "series_id": series_id, "api_key": config.MARKET_INTEL_FRED_API_KEY, "file_type": "json",
                "sort_order": "desc", "limit": limit, "units": units,
            },
        )

    try:
        data = cache.get_or_fetch(
            f"fred:{series_id}:{units}:{limit}", config.MARKET_INTEL_CACHE_TTL_MACRO_SECONDS, _fetch,
        )
    except Exception:  # noqa: BLE001 - network/HTTP/JSON failure all degrade to "no data"
        return []

    results = []
    for obs in data.get("observations") or []:
        raw_value = obs.get("value")
        if raw_value in (None, ".", ""):
            continue
        try:
            results.append((float(raw_value), obs.get("date")))
        except (TypeError, ValueError):
            continue
    return results


def _fred_latest_value(series_id: str, units: str = "lin") -> Optional[float]:
    observations = _fred_observations(series_id, units=units, limit=1)
    return observations[0][0] if observations else None


def _format_units(value: Optional[float], units: str) -> Optional[str]:
    """Preserves the ORIGINAL unit/representation per series — never
    silently compares or converts incompatible units. `pc1` series are a
    percent-change figure (shown with a % sign); `lin` series for the
    tracked events (rates, index levels, payroll counts) are shown as-is,
    matching what FRED itself reports for that series."""
    if value is None:
        return None
    return f"{value:.2f}%" if units == "pc1" else f"{value:.2f}"


# ---------------------------------------------------------------------------
# Macro + Gold Fundamentals
# ---------------------------------------------------------------------------

class RealMacroProvider(BaseMacroProvider):
    name = "real"

    def get_macro_snapshot(self) -> MacroSnapshot:
        if not config.MARKET_INTEL_FRED_API_KEY:
            return MacroSnapshot(
                data_available=False, source=self.name,
                reason="MARKET_INTEL_FRED_API_KEY is not set — see .env.example.",
                freshness=classify_freshness(False, self.name, None, config.MARKET_INTEL_STALE_AFTER_SECONDS),
            )

        fed_funds = _fred_latest_value("FEDFUNDS")
        cpi_yoy = _fred_latest_value("CPIAUCSL", units="pc1")
        core_cpi_yoy = _fred_latest_value("CPILFESL", units="pc1")
        unemployment = _fred_latest_value("UNRATE")
        gdp_growth = _fred_latest_value("GDPC1", units="pc1")
        us10y = _fred_latest_value("DGS10")
        us2y = _fred_latest_value("DGS2")

        if all(v is None for v in (fed_funds, cpi_yoy, core_cpi_yoy, unemployment, gdp_growth, us10y, us2y)):
            return MacroSnapshot(
                data_available=False, source=self.name, reason="FRED returned no usable data.",
                freshness=classify_freshness(False, self.name, None, config.MARKET_INTEL_STALE_AFTER_SECONDS),
            )

        generated_at = _now_iso()
        return MacroSnapshot(
            data_available=True, source=self.name, generated_at=generated_at,
            fed_funds_rate=fed_funds, cpi_yoy=cpi_yoy, core_cpi_yoy=core_cpi_yoy,
            unemployment_rate=unemployment, gdp_growth_yoy=gdp_growth,
            us10y_yield=us10y, us2y_yield=us2y,
            freshness=classify_freshness(True, self.name, generated_at, config.MARKET_INTEL_STALE_AFTER_SECONDS),
        )

    def get_gold_fundamentals(self) -> GoldFundamentals:
        us10y = _fred_latest_value("DGS10")
        cpi_yoy = _fred_latest_value("CPIAUCSL", units="pc1")
        real_yield = round(us10y - cpi_yoy, 2) if us10y is not None and cpi_yoy is not None else None
        usd_bias = _usd_strength_bias()

        if real_yield is None and usd_bias is None:
            reason = (
                "MARKET_INTEL_FRED_API_KEY is not set — see .env.example."
                if not config.MARKET_INTEL_FRED_API_KEY else "No real gold-fundamentals data available."
            )
            return GoldFundamentals(
                data_available=False, source=self.name, reason=reason,
                freshness=classify_freshness(False, self.name, None, config.MARKET_INTEL_STALE_AFTER_SECONDS),
            )

        generated_at = _now_iso()
        return GoldFundamentals(
            data_available=True, source=self.name, generated_at=generated_at,
            usd_strength_bias=usd_bias, real_yield_10y=real_yield,
            # No free, reliable source exists for these — left honestly
            # absent rather than invented (the spec's own explicit example
            # of what NOT to fabricate).
            central_bank_demand_trend=None, etf_flows_trend=None,
            freshness=classify_freshness(True, self.name, generated_at, config.MARKET_INTEL_STALE_AFTER_SECONDS),
        )


def _yahoo_quote(symbol: str) -> Optional[Tuple[float, Optional[float]]]:
    """Returns (latest_price, previous_close) from Yahoo's public chart
    JSON endpoint, or None on any failure."""
    def _fetch():
        return http_client.get_json(
            _YAHOO_CHART.format(symbol=symbol), params={"range": "5d", "interval": "1d"},
        )

    try:
        data = cache.get_or_fetch(f"yahoo:{symbol}", config.MARKET_INTEL_CACHE_TTL_CROSS_ASSET_SECONDS, _fetch)
        result = data["chart"]["result"][0]
        meta = result["meta"]
        price = meta.get("regularMarketPrice")
        previous_close = meta.get("previousClose") or meta.get("chartPreviousClose")
        if price is None:
            return None
        return float(price), (float(previous_close) if previous_close is not None else None)
    except Exception:  # noqa: BLE001 - network/HTTP/JSON-shape failure all degrade to "no data"
        return None


def _usd_strength_bias() -> Optional[str]:
    """A simple, documented threshold over a REAL DXY move — not invented
    sentiment. >0.5% up over the last ~5 sessions -> STRONG, < -0.5% ->
    WEAK, otherwise NEUTRAL. None if DXY itself is unavailable."""
    quote = _yahoo_quote("DX-Y.NYB")
    if quote is None or quote[1] in (None, 0):
        return None
    price, previous = quote
    change_pct = (price - previous) / previous * 100
    if change_pct > 0.5:
        return "STRONG"
    if change_pct < -0.5:
        return "WEAK"
    return "NEUTRAL"


class RealCrossAssetProvider(BaseCrossAssetProvider):
    name = "real"

    def get_cross_asset_snapshot(self) -> CrossAssetSnapshot:
        dxy = _yahoo_quote("DX-Y.NYB")
        vix = _yahoo_quote("^VIX")
        spx = _yahoo_quote("^GSPC")
        silver = _yahoo_quote("SI=F")
        us10y = _fred_latest_value("DGS10")
        us2y = _fred_latest_value("DGS2")
        cpi_yoy = _fred_latest_value("CPIAUCSL", units="pc1")
        real_yield = round(us10y - cpi_yoy, 2) if us10y is not None and cpi_yoy is not None else None

        if all(v is None for v in (dxy, vix, spx, silver, us10y, us2y)):
            return CrossAssetSnapshot(
                data_available=False, source=self.name, reason="No real cross-asset data available.",
                freshness=classify_freshness(False, self.name, None, config.MARKET_INTEL_STALE_AFTER_SECONDS),
            )

        generated_at = _now_iso()
        return CrossAssetSnapshot(
            data_available=True, source=self.name, generated_at=generated_at,
            dxy=dxy[0] if dxy else None, vix=vix[0] if vix else None,
            equity_index=spx[0] if spx else None, silver_price=silver[0] if silver else None,
            us10y_yield=us10y, us2y_yield=us2y, real_yield_10y=real_yield,
            freshness=classify_freshness(True, self.name, generated_at, config.MARKET_INTEL_STALE_AFTER_SECONDS),
        )


# ---------------------------------------------------------------------------
# Economic Events
# ---------------------------------------------------------------------------

class RealEventsProvider(BaseEventsProvider):
    name = "real"

    def get_economic_events(self, days_ahead: int = 7, days_back: int = 1) -> List[EconomicEvent]:
        if not config.MARKET_INTEL_FRED_API_KEY:
            return []

        now = datetime.now(timezone.utc)
        cutoff_back = now - timedelta(days=days_back)
        events: List[EconomicEvent] = []

        for series_id, name, category, importance, units in _TRACKED_EVENT_SERIES:
            observations = _fred_observations(series_id, units=units, limit=2)
            if not observations:
                continue
            actual_value, actual_date_raw = observations[0]
            scheduled_at = parse_timestamp(actual_date_raw)
            if scheduled_at is None or scheduled_at < cutoff_back:
                continue
            previous_value = observations[1][0] if len(observations) > 1 else None
            events.append(EconomicEvent(
                name=name, category=category, importance=importance,
                scheduled_at=scheduled_at.isoformat(), source=self.name,
                actual=_format_units(actual_value, units),
                forecast=None,  # FRED has no consensus-forecast data — never invented
                previous=_format_units(previous_value, units),
                country="US",  # every currently tracked FRED series is a US release
            ))

        events.extend(self._upcoming_release_dates(now, days_ahead))
        return sorted(events, key=lambda e: e.scheduled_at)

    def _upcoming_release_dates(self, now: datetime, days_ahead: int) -> List[EconomicEvent]:
        """Best-effort, independently isolated: a failure here never
        affects the "recent" events above."""
        if days_ahead <= 0:
            return []

        def _fetch():
            return http_client.get_json(
                f"{_FRED_BASE}/releases/dates",
                params={
                    "api_key": config.MARKET_INTEL_FRED_API_KEY, "file_type": "json",
                    "include_release_dates_with_no_data": "true",
                    "realtime_start": now.date().isoformat(),
                    "realtime_end": (now + timedelta(days=days_ahead)).date().isoformat(),
                    "sort_order": "asc", "limit": 200,
                },
            )

        try:
            data = cache.get_or_fetch(
                f"fred:releases:dates:{days_ahead}", config.MARKET_INTEL_CACHE_TTL_EVENTS_SECONDS, _fetch,
            )
        except Exception:  # noqa: BLE001
            return []

        events = []
        for entry in data.get("release_dates", []):
            release_name = entry.get("release_name", "")
            matched = next((v for k, v in _UPCOMING_RELEASE_KEYWORDS.items() if k in release_name), None)
            if matched is None:
                continue
            scheduled_at = parse_timestamp(entry.get("date"))
            if scheduled_at is None:
                continue
            name, category, importance = matched
            events.append(EconomicEvent(
                name=name, category=category, importance=importance,
                scheduled_at=scheduled_at.isoformat(), source=self.name,
                actual=None, forecast=None, previous=None, country="US",
            ))
        return events


# ---------------------------------------------------------------------------
# News
# ---------------------------------------------------------------------------

class RealNewsProvider(BaseNewsProvider):
    name = "real"

    def get_recent_news(self, limit: int = 10, max_age_hours: float = 48) -> List[NewsArticle]:
        articles = self._fed_articles() + self._marketwatch_articles()
        return articles[:limit]

    def _fed_articles(self) -> List[NewsArticle]:
        raw = self._fetch_feed(_FED_RSS, "rss:fed", "federal_reserve")
        return [self._to_article(r, category="macro", importance="HIGH", assets=["XAUUSD", "USD"]) for r in raw]

    def _marketwatch_articles(self) -> List[NewsArticle]:
        raw = self._fetch_feed(_MARKETWATCH_RSS, "rss:marketwatch", "marketwatch")
        relevant = [r for r in raw if self._is_relevant(r)]
        return [self._to_article(r, category="macro", importance="MEDIUM", assets=["XAUUSD"]) for r in relevant]

    @staticmethod
    def _fetch_feed(url: str, cache_key: str, source_name: str) -> List[dict]:
        try:
            xml_text = cache.get_or_fetch(
                cache_key, config.MARKET_INTEL_CACHE_TTL_NEWS_SECONDS, lambda: http_client.get_text(url),
            )
        except Exception:  # noqa: BLE001 - one feed being down must never affect the other
            return []
        return rss.parse_rss(xml_text, source_name)

    @staticmethod
    def _is_relevant(raw: dict) -> bool:
        return classify_news_relevance(raw.get("headline"), raw.get("summary")) == "RELEVANT"

    @staticmethod
    def _to_article(raw: dict, category: str, importance: str, assets: List[str]) -> NewsArticle:
        published_at = raw.get("published_at") or datetime.now(timezone.utc)
        article = NewsArticle(
            id="", headline=raw["headline"], source=raw["source"],
            published_at=published_at.isoformat(), retrieved_at=_now_iso(),
            url=raw.get("url"), category=category, importance=importance,
            assets=list(assets), summary=raw.get("summary"),
        )
        article.id = stable_id(article)
        return article
