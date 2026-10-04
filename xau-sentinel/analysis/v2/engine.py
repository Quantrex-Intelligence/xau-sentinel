"""Analysis Engine V2 orchestrator.

    MT5 RAW DATA -> OBSERVATIONS -> CONTEXT -> EVENTS -> KEY AREAS
                 -> CONFLUENCE/CONTRADICTIONS -> NARRATIVE -> CONDITIONAL SCENARIOS

Takes the same candle dictionary the live path already builds, reads only the
closed bars of each timeframe, and never mutates its input. The live engine
(analysis/setup.py, the A+ rules, the snapshot path) is untouched and is not a
dependency of this module. A+ is one possible consumer of V2, not its centre.

Status values:
    OK                 enough closed history on M5 and a usable current price
    STALE              M5 feed older than the configured staleness window
    INSUFFICIENT_DATA  M5 cannot support a read; the other fields are empty
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import pandas as pd

from analysis.structure import closed_only, is_feed_stale
from analysis.v2 import key_areas as ka
from analysis.v2.confluence import Confluence, build_confluence
from analysis.v2.context import MarketContext, build_context
from analysis.v2.events import Event, price_events, sort_events, structure_events
from analysis.v2.narrative import build_narrative
from analysis.v2.observations import TIMEFRAMES, Observations, build_observations
from analysis.v2.relations import AreaState, classify_area
from analysis.v2.scenarios import Scenario, build_scenarios


@dataclass(frozen=True)
class AnalysisV2:
    status: str
    observations: Observations
    context: Optional[MarketContext]
    areas: Tuple[AreaState, ...]
    events: Tuple[Event, ...]
    confluence: Optional[Confluence]
    narrative: Tuple[str, ...]
    scenarios: Tuple[Scenario, ...]
    notes: Tuple[str, ...] = field(default_factory=tuple)


def _closed_candles(candles: Dict[str, pd.DataFrame]) -> Dict[str, pd.DataFrame]:
    """Closed bars only, per timeframe. A frame without an is_closed column is
    dropped rather than trusted, matching build_observations()."""
    out: Dict[str, pd.DataFrame] = {}
    for tf in TIMEFRAMES:
        df = candles.get(tf)
        if df is not None and "is_closed" in df.columns and len(df):
            out[tf] = closed_only({tf: df})[tf]
    return out


def build_analysis(candles: Dict[str, pd.DataFrame], now: Optional[datetime] = None) -> AnalysisV2:
    now = now or datetime.now(timezone.utc)
    obs = build_observations(candles)
    closed = _closed_candles(candles)
    notes: List[str] = []

    if not obs.ready:
        return AnalysisV2("INSUFFICIENT_DATA", obs, None, (), (), None,
                          tuple(["Insufficient data: " + "; ".join(obs.data_issues or ("no closed M5 bars",)) + "."]),
                          (), tuple(obs.data_issues))

    m5 = closed.get("M5")
    status = "OK"
    if m5 is not None and candles.get("M5") is not None and is_feed_stale(candles["M5"], now):
        status = "STALE"
        notes.append("The M5 feed is older than the configured staleness window; read the analysis as historical.")

    # Key areas use the same closed frames the rest of the engine uses.
    raw_areas = ka.build_key_areas(m5, closed.get("H1"), closed.get("H4"), obs.current_price)
    area_states = tuple(classify_area(a, m5, obs.current_price, obs.atr_m5) for a in raw_areas)

    events = sort_events(
        structure_events(closed)
        + price_events(closed, obs)
        + [e for a in area_states for e in a.events]
    )
    context = build_context(obs, closed, events)
    confluence = build_confluence(obs, context, events, list(area_states))
    scenarios = build_scenarios(obs, context, confluence, list(area_states), events)
    narrative_lines = build_narrative(obs, context, confluence, list(area_states), events)
    if status == "STALE":
        narrative_lines = [notes[0]] + narrative_lines  # the reader sees the staleness first
    narrative = tuple(narrative_lines)
    return AnalysisV2(status, obs, context, area_states, tuple(events), confluence, narrative,
                      scenarios, tuple(notes) + tuple(obs.data_issues))
