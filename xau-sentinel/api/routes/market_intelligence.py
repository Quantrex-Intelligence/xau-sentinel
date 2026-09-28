"""Market Intelligence routes — read-only. One aggregate endpoint for the
minimal UI panel; the LLM reaches the same data with finer granularity
through ai/tools/market_intelligence_tools.py. Every handler is a thin call
into ai.market_intelligence.context; no provider or scoring logic lives
here."""
from dataclasses import asdict

from fastapi import APIRouter

from ai.market_intelligence import context as mi_context
from ai.market_intelligence.schemas import MarketIntelligenceContextOut

router = APIRouter(prefix="/api/market-intelligence", tags=["market-intelligence"])


@router.get("", response_model=MarketIntelligenceContextOut)
def get_market_intelligence():
    ctx = mi_context.build_market_intelligence_context()
    return MarketIntelligenceContextOut(
        data_available=ctx.data_available, generated_at=ctx.generated_at,
        macro=asdict(ctx.macro) if ctx.macro else None,
        gold_fundamentals=asdict(ctx.gold_fundamentals) if ctx.gold_fundamentals else None,
        cross_asset=asdict(ctx.cross_asset) if ctx.cross_asset else None,
        events=[asdict(e) for e in ctx.events], news=[asdict(n) for n in ctx.news],
        sources=ctx.sources,
    )
