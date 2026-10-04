"""Read-only assembly of the Analysis Engine V2 view.

    MT5 candles (existing market_data path) -> analysis.v2.engine -> AnalysisV2Out

Nothing here writes to the journal, risk state, alerts, or any broker. It does
not call an LLM, does not feed A+ or monitoring, and does not change any
existing engine output. The clock is injectable so responses are reproducible.
"""
import math
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

import config
from analysis.v2.engine import AnalysisV2, build_analysis
from analysis.v2.observations import TIMEFRAMES
from mt5 import connection, market_data

from api.schemas_analysis_v2 import (
    AnalysisV2Out, ComponentOut, Confluence, Context, Dimension, EventOut, Facts, Freshness,
    Interpretation, KeyAreaOut, Lean, Observations, ScenarioOut, Source, SweepOut,
    TimeframeSource, TimeframeStructure, VolumeOut,
)

# Bars requested per timeframe. These cover the V2 minimums with headroom:
# M5 needs 120, H1 and M15 need 60, H4 needs 40.
BARS = {"M5": 400, "M15": 300, "H1": 320, "H4": 320}


def _f(value) -> Optional[float]:
    if value is None:
        return None
    value = float(value)
    return None if math.isnan(value) or math.isinf(value) else value


def _iso(ts) -> Optional[str]:
    if ts is None:
        return None
    ts = pd.Timestamp(ts)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert("UTC").isoformat()


def _dim(d) -> Dimension:
    return Dimension(state=d.state, detail=d.detail)


def _sweep(e) -> SweepOut:
    return SweepOut(time_utc=_iso(e.time), label=e.label, level_name=e.level_name,
                    level_price=_f(e.level_price), kind=e.kind)


def _event(e) -> EventOut:
    return EventOut(kind=e.kind, timeframe=e.timeframe, time_utc=_iso(e.time), direction=e.direction,
                    price=_f(e.price), detail=e.detail)


def _structure(s) -> TimeframeStructure:
    return TimeframeStructure(
        timeframe=s.timeframe, state=s.state, reason=s.reason, last_bos=s.last_bos, last_mss=s.last_mss,
        last_high=_f(s.last_high), last_low=_f(s.last_low),
        last_high_label=s.last_high_label, last_low_label=s.last_low_label,
    )


def _observations(obs) -> Observations:
    vol = obs.volume_m5 or {}
    return Observations(
        current_price=_f(obs.current_price), atr_m5=_f(obs.atr_m5), atr_h1=_f(obs.atr_h1),
        atr_percentile_m5=_f(obs.atr_percentile_m5), atr_change_m5=_f(obs.atr_change_m5),
        range_ratio_m5=_f(obs.range_ratio_m5), displacement_m5=obs.displacement_m5,
        volume_m5=VolumeOut(relative_volume=_f(vol.get("relative_volume")),
                            volume_percentile=_f(vol.get("volume_percentile")),
                            state=vol.get("state", "UNKNOWN")),
        session=obs.session,
        zones={k: float(v) for k, v in obs.zones.items()},
        zone_distances_atr={k: float(v) for k, v in obs.zone_distances_atr.items() if _f(v) is not None},
        recent_high=_f(obs.recent_high), recent_low=_f(obs.recent_low),
        sweeps=[_sweep(e) for e in obs.sweeps],
        equal_levels=[_sweep(e) for e in obs.equal_levels],
    )


def _key_area(a) -> KeyAreaOut:
    return KeyAreaOut(
        low=float(a.area.low), high=float(a.area.high), side=a.area.side,
        strength_status=a.area.strength_status, strength_reason=a.area.strength_reason,
        relation=a.relation, distance_atr=_f(a.distance_atr), reasons=list(a.reasons),
        components=[ComponentOut(label=c.label, price=float(c.price), timeframe=c.evidence.timeframe,
                                 kind=c.evidence.kind, source=c.evidence.source, note=c.evidence.note)
                    for c in a.area.components],
        events=[_event(e) for e in a.events],
    )


def _lean(l) -> Lean:
    return Lean(source=l.source, timeframe=l.timeframe, lean=l.lean, detail=l.detail)


def _confluence(c) -> Confluence:
    return Confluence(
        reference=c.reference, reference_reason=c.reference_reason,
        supporting=[_lean(l) for l in c.supporting], contradicting=[_lean(l) for l in c.contradicting],
        neutral=[_lean(l) for l in c.neutral], bullish=[_lean(l) for l in c.bullish],
        bearish=[_lean(l) for l in c.bearish], cross_timeframe_conflicts=list(c.cross_timeframe_conflicts),
    )


def _context(ctx) -> Context:
    return Context(
        direction=_dim(ctx.direction), structure={k: _dim(v) for k, v in ctx.structure.items()},
        regime=_dim(ctx.regime), volatility=_dim(ctx.volatility), volume=_dim(ctx.volume),
        liquidity=_dim(ctx.liquidity), momentum=_dim(ctx.momentum), session=_dim(ctx.session),
        price_location=_dim(ctx.price_location),
    )


def _scenario(s) -> ScenarioOut:
    return ScenarioOut(
        name=s.name, direction=s.direction, condition=s.condition,
        supporting_conditions=list(s.supporting_conditions),
        confirmation_requirements=list(s.confirmation_requirements),
        invalidation_conditions=list(s.invalidation_conditions),
        key_area_refs=list(s.key_area_refs), event_refs=list(s.event_refs), disclaimer=s.disclaimer,
    )


def _provider() -> str:
    if config.IS_LIVE:
        return "MT5 live"
    if config.IS_MOCK:
        return "MOCK (synthetic, not market data)"
    return config.MODE


def _source(candles: dict) -> Source:
    timeframes = {}
    for tf, df in candles.items():
        if df is None or len(df) == 0:
            continue
        closed = bool(df["is_closed"].iloc[-1]) if "is_closed" in df.columns else None
        timeframes[tf] = TimeframeSource(bars=len(df), last_bar_open_utc=_iso(df["time"].iloc[-1]),
                                         last_bar_closed=closed)
    return Source(provider=_provider(), mode=config.MODE, symbol=config.TRADING_SYMBOL,
                  server_timezone=config.FUNDEDNEXT_SERVER_TIMEZONE, timeframes=timeframes)


def _freshness(analysis: AnalysisV2, now: datetime) -> Freshness:
    """Age of the last CLOSED M5 bar. The forming bar is never used here."""
    threshold = 5 * 60 + config.DATA_STALE_SECONDS
    as_of = analysis.observations.as_of
    close = None
    age = None
    if as_of is not None:
        close = pd.Timestamp(as_of).tz_localize("UTC") if pd.Timestamp(as_of).tzinfo is None else pd.Timestamp(as_of)
        close = close + pd.Timedelta(minutes=5)
        age = (pd.Timestamp(now).tz_convert("UTC") - close).total_seconds()
    return Freshness(
        generated_at_utc=_iso(now), as_of_utc=_iso(as_of),
        m5_bar_close_utc=_iso(close), age_seconds=_f(age), threshold_seconds=float(threshold),
        stale=analysis.status == "STALE",
    )


def _status_reason(analysis: AnalysisV2) -> str:
    if analysis.status == "OK":
        return "Closed M5 history and a current price are available."
    if analysis.status == "STALE":
        return "The M5 feed is older than the staleness window; the analysis describes history, not now."
    issues = "; ".join(analysis.observations.data_issues) or "no closed M5 bars"
    return f"Not enough closed market data for a read: {issues}."


def _unavailable(now: datetime, reason: str) -> AnalysisV2Out:
    return AnalysisV2Out(
        status="UNAVAILABLE",
        status_reason=f"MT5 data is unavailable: {reason}",
        freshness=Freshness(generated_at_utc=_iso(now), threshold_seconds=float(5 * 60 + config.DATA_STALE_SECONDS),
                            stale=True),
        source=Source(provider="unavailable", mode=config.MODE, symbol=config.TRADING_SYMBOL,
                      server_timezone=config.FUNDEDNEXT_SERVER_TIMEZONE, timeframes={}),
        notes=[], data_issues=[], facts=Facts(), events=[], interpretation=Interpretation(), scenarios=[],
    )


def fetch_candles() -> dict:
    """Closed and forming candles for each timeframe, through the existing data path."""
    if config.IS_LIVE and not connection.is_connected():
        connection.connect()
    return {tf: market_data.get_candles(tf, BARS[tf]) for tf in TIMEFRAMES}


def build_payload(now: Optional[datetime] = None, candles: Optional[dict] = None) -> AnalysisV2Out:
    """`candles` may be supplied directly (tests, or a caller that already has
    them). Otherwise they are fetched from MT5 and any data error becomes an
    UNAVAILABLE response rather than an exception."""
    now = now or datetime.now(timezone.utc)
    if candles is None:
        try:
            candles = fetch_candles()
        except market_data.MarketDataError as exc:
            return _unavailable(now, str(exc))

    analysis = build_analysis(candles, now=now)
    obs = analysis.observations
    return AnalysisV2Out(
        status=analysis.status,
        status_reason=_status_reason(analysis),
        freshness=_freshness(analysis, now),
        source=_source(candles),
        notes=list(analysis.notes),
        data_issues=list(obs.data_issues),
        facts=Facts(
            observations=_observations(obs) if obs.ready else None,
            structure={tf: _structure(s) for tf, s in obs.structure.items()},
        ),
        events=[_event(e) for e in analysis.events],
        interpretation=Interpretation(
            context=_context(analysis.context) if analysis.context else None,
            key_areas=[_key_area(a) for a in analysis.areas],
            confluence=_confluence(analysis.confluence) if analysis.confluence else None,
            narrative=list(analysis.narrative),
        ),
        scenarios=[_scenario(s) for s in analysis.scenarios],
    )
