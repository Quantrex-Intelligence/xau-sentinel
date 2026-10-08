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
from analysis.v2.events import Event, collapse_area_events, dedupe_events, price_events, sort_events, structure_events
from analysis.v2.narrative import build_narrative
from analysis.v2.observations import TIMEFRAMES, Observations, build_observations
from analysis.v2.priority import active_areas, prioritize_events
from analysis.v2.relations import AreaState, classify_area
from analysis.v2.scenarios import Scenario, build_scenarios
from analysis.v2.sequence import MarketSequence, build_sequences


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
    sequences: Tuple[MarketSequence, ...] = field(default_factory=tuple)  # one per distinct sweep
    # Key areas near price (ACTIVE_AREA_ATR). `areas` keeps every area, so distant ones are counted, not lost.
    active_areas: Tuple[AreaState, ...] = field(default_factory=tuple)
    # Every event considered after dedupe and collapse, before the per-tier caps. `events` is the bounded
    # active stream drawn from it. Kept for validation, not for display.
    all_events: Tuple[Event, ...] = field(default_factory=tuple)

    @property
    def distant_area_count(self) -> int:
        return len(self.areas) - len(self.active_areas)


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

    # Key areas use the same closed frames the rest of the engine uses. Every area is kept; only
    # the areas within ACTIVE_AREA_ATR of price feed the active views.
    raw_areas = ka.build_key_areas(m5, closed.get("H1"), closed.get("H4"), obs.current_price)
    area_states = tuple(classify_area(a, m5, obs.current_price, obs.atr_m5) for a in raw_areas)
    near_areas = active_areas(area_states)

    # Candidates: structure, price and non-superseded area events. A superseded area event is
    # history (kept on its area) and is not a candidate for the active stream.
    candidates = (structure_events(closed) + price_events(closed, obs)
                  + [e for a in area_states for e in a.events if not e.superseded])
    collapsed = collapse_area_events(candidates, obs.current_price)
    all_events = tuple(dedupe_events(sort_events(collapsed)))
    events = prioritize_events(all_events, obs.current_price, obs.atr_m5)

    context = build_context(obs, closed, list(all_events))
    confluence = build_confluence(obs, context, list(all_events), list(near_areas))
    last_close = float(m5["close"].iloc[-1]) if m5 is not None and len(m5) else None
    scenarios = build_scenarios(obs, context, confluence, list(near_areas), list(events), last_close)
    narrative_lines = build_narrative(obs, context, confluence, list(near_areas), list(events))
    if status == "STALE":
        narrative_lines = [notes[0]] + narrative_lines  # the reader sees the staleness first
    narrative = tuple(narrative_lines)
    sequences = build_sequences(m5, obs.sweeps) if m5 is not None else ()
    return AnalysisV2(status, obs, context, area_states, events, confluence, narrative,
                      scenarios, tuple(notes) + tuple(obs.data_issues), sequences,
                      active_areas=near_areas, all_events=all_events)
