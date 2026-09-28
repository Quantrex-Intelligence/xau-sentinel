"""Abstract provider interfaces — one per Market Intelligence category. No
exceptions for "no data available": every method returns its typed
dataclass with data_available=False instead (mirrors mt5/account.py's
AccountSnapshot(available=False, error=...) pattern), so a provider failure
is always explicit data, never a crash and never a fabricated value."""
from abc import ABC, abstractmethod
from typing import List

from ai.market_intelligence.models import (
    CrossAssetSnapshot, EconomicEvent, GoldFundamentals, MacroSnapshot, NewsArticle,
)


class BaseMacroProvider(ABC):
    """Covers both broad macro (category 1) and gold-specific fundamentals
    (category 2) — the two share a provider because gold fundamentals are
    themselves largely a reading of the same Fed/rates/inflation data,
    never a second, independent source of the same underlying numbers."""
    name: str = "base"

    @abstractmethod
    def get_macro_snapshot(self) -> MacroSnapshot:
        raise NotImplementedError

    @abstractmethod
    def get_gold_fundamentals(self) -> GoldFundamentals:
        raise NotImplementedError


class BaseCrossAssetProvider(ABC):
    name: str = "base"

    @abstractmethod
    def get_cross_asset_snapshot(self) -> CrossAssetSnapshot:
        raise NotImplementedError


class BaseEventsProvider(ABC):
    name: str = "base"

    @abstractmethod
    def get_economic_events(self, days_ahead: int = 7, days_back: int = 1) -> List[EconomicEvent]:
        """Returns [] when genuinely none are known — never a fabricated
        placeholder event."""
        raise NotImplementedError


class BaseNewsProvider(ABC):
    name: str = "base"

    @abstractmethod
    def get_recent_news(self, limit: int = 10, max_age_hours: float = 48) -> List[NewsArticle]:
        """Returns [] when genuinely none are known. Callers should not
        assume the provider itself applies max_age_hours/dedup — see
        ai/market_intelligence/context.py, which applies both uniformly
        regardless of provider."""
        raise NotImplementedError
