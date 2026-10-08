"""Layer 3 of Analysis Engine V2: discrete events from closed candles.

BOS and MSS keep their existing meaning, because they come from the same
`analyze_structure()` used everywhere else. What is new is the event
representation: a state is turned into an event on the bar where it first
appears, by replaying the state over the closed prefix of each bar. The state
logic is never copied or changed here.

Every event is tied to one closed bar (`time`, the bar's UTC open time), so
recency is always explicit and an old state cannot be reported as new.
"""
from dataclasses import dataclass, replace
from typing import List, Optional, Sequence, Tuple

import pandas as pd

import config
from analysis.structure import analyze_structure, compute_atr, displacement_at
from analysis.v2.observations import Observations

EVENT_WINDOW_M5 = 30  # closed M5 bars scanned for transitions
EVENT_WINDOW_H1 = 12  # closed H1 bars scanned for BOS/MSS transitions
RANGE_EXPANSION_MULT = 1.8  # bar range over the prior 20-bar mean range
COMPRESSION_MULT = 0.5  # 5-bar mean range below this fraction of prior ATR
MOMENTUM_LOSS_RATIO = 0.5  # recent mean body below this fraction of the earlier mean body


@dataclass(frozen=True)
class Event:
    kind: str  # SWEEP | BOS | MSS | PULLBACK | DISPLACEMENT | VOLATILITY_EXPANSION | ...
    timeframe: str
    time: pd.Timestamp  # UTC open time of the closed bar where the event first appears
    direction: Optional[str]  # "bullish" | "bearish" | None
    price: Optional[float]
    detail: str
    # Every level this event was recorded at. One entry for a plain event; several when the same
    # bar, kind and direction were recorded at nearby areas and collapsed into one (see collapse_area_events).
    levels: Tuple[float, ...] = ()
    # True when a later event on the same area with the opposite direction replaced this one as the
    # current state. The record is kept on the area for evidence, but it is left out of the active stream.
    superseded: bool = False


def _bar_time(df: pd.DataFrame, i: int) -> pd.Timestamp:
    return pd.Timestamp(df["time"].iloc[i])


def structure_transitions(df: pd.DataFrame, tf: str, window: int) -> List[Event]:
    """BOS and MSS events: the bar where `last_bos` or `last_mss` first becomes a
    direction, found by replaying analyze_structure over each closed prefix."""
    events: List[Event] = []
    if df is None or len(df) < window + 10:
        return events
    start = len(df) - window
    previous = analyze_structure(df.iloc[:start])
    for i in range(start, len(df)):
        current = analyze_structure(df.iloc[: i + 1])
        price = float(df["close"].iloc[i])
        if current.last_bos and current.last_bos != previous.last_bos:
            events.append(Event("BOS", tf, _bar_time(df, i), current.last_bos, price,
                                f"{tf} close beyond the latest confirmed swing"))
        if current.last_mss and current.last_mss != previous.last_mss:
            events.append(Event("MSS", tf, _bar_time(df, i), current.last_mss, price,
                                f"{tf} close against the latest confirmed swing"))
        previous = current
    return events


def pullback_event(df: pd.DataFrame, tf: str) -> Optional[Event]:
    """PULLBACK when the last close sits between the configured retracement
    bounds of the most recent confirmed leg. Uses the same retracement limits as
    the existing setup logic, and reports the bar it occurs on."""
    from analysis.structure import find_swing_points
    if df is None or len(df) < 30:
        return None
    swings = find_swing_points(df)  # the first swing of each kind has no label but is still a pivot
    highs = [p for p in swings if p.kind == "high"]
    lows = [p for p in swings if p.kind == "low"]
    if not highs or not lows:
        return None
    last_high, last_low = highs[-1], lows[-1]
    close = float(df["close"].iloc[-1])
    leg = last_high.price - last_low.price
    if leg <= 0:
        return None
    if last_high.index > last_low.index:  # up-leg most recent; retracement goes down
        retrace = (last_high.price - close) / leg
        direction = "bearish"
    else:  # down-leg most recent; retracement goes up
        retrace = (close - last_low.price) / leg
        direction = "bullish"
    if config.RETRACEMENT_MIN_PCT <= retrace <= config.RETRACEMENT_MAX_PCT:
        return Event("PULLBACK", tf, _bar_time(df, len(df) - 1), direction, close,
                     f"{tf} pullback of {retrace:.0%} of the latest leg")
    return None


def displacement_events(m5: pd.DataFrame, window: int = EVENT_WINDOW_M5) -> List[Event]:
    events: List[Event] = []
    if m5 is None or len(m5) < config.ATR_PERIOD + window:
        return events
    atr = compute_atr(m5)
    for i in range(len(m5) - window, len(m5)):
        side = displacement_at(m5, i, atr=atr)
        if side:
            events.append(Event("DISPLACEMENT", "M5", _bar_time(m5, i), side, float(m5["close"].iloc[i]),
                                f"M5 body beyond {config.DISPLACEMENT_ATR_MULT} ATR of the prior bar's ATR"))
    return events


def volatility_events(m5: pd.DataFrame, window: int = EVENT_WINDOW_M5) -> List[Event]:
    """Transitions of the ATR ratio (now vs `ATR_CHANGE_LOOKBACK` bars ago) across
    the expansion or contraction thresholds."""
    from analysis.v2.observations import ATR_CHANGE_LOOKBACK
    events: List[Event] = []
    if m5 is None or len(m5) < config.ATR_PERIOD + ATR_CHANGE_LOOKBACK + window:
        return events
    atr = compute_atr(m5)

    def ratio(i: int) -> Optional[float]:
        base = atr.iloc[i - ATR_CHANGE_LOOKBACK]
        return float(atr.iloc[i] / base) if base and base > 0 else None

    for i in range(len(m5) - window, len(m5)):
        now, before = ratio(i), ratio(i - 1)
        if now is None or before is None:
            continue
        if now >= config.HIGH_VOL_ATR_MULT > before:
            events.append(Event("VOLATILITY_EXPANSION", "M5", _bar_time(m5, i), None,
                                float(m5["close"].iloc[i]), f"ATR ratio {now:.2f} crossed up"))
        if now <= config.LOW_VOL_ATR_MULT < before:
            events.append(Event("VOLATILITY_CONTRACTION", "M5", _bar_time(m5, i), None,
                                float(m5["close"].iloc[i]), f"ATR ratio {now:.2f} crossed down"))
    return events


def range_events(m5: pd.DataFrame, window: int = EVENT_WINDOW_M5) -> List[Event]:
    """COMPRESSION: the 5-bar mean range falls well below ATR (first bar it does).
    RANGE_EXPANSION: a single bar's range is far above the prior 20-bar mean."""
    events: List[Event] = []
    if m5 is None or len(m5) < config.ATR_PERIOD + 25:
        return events
    ranges = (m5["high"] - m5["low"]).astype(float)
    atr = compute_atr(m5)
    for i in range(len(m5) - window, len(m5)):
        prior_mean = ranges.iloc[i - 20: i].mean()
        if prior_mean > 0 and ranges.iloc[i] >= RANGE_EXPANSION_MULT * prior_mean:
            body = float(m5["close"].iloc[i] - m5["open"].iloc[i])
            side = "bullish" if body > 0 else "bearish" if body < 0 else None
            events.append(Event("RANGE_EXPANSION", "M5", _bar_time(m5, i), side,
                                float(m5["close"].iloc[i]),
                                f"bar range {ranges.iloc[i] / prior_mean:.1f}x the prior 20-bar mean"))
        five = ranges.iloc[i - 4: i + 1].mean()
        prior_atr = atr.iloc[i - 1]
        was_compressed = ranges.iloc[i - 5: i].mean() <= COMPRESSION_MULT * prior_atr if i >= 5 else False
        if prior_atr > 0 and five <= COMPRESSION_MULT * prior_atr and not was_compressed:
            events.append(Event("COMPRESSION", "M5", _bar_time(m5, i), None,
                                float(m5["close"].iloc[i]), "5-bar mean range below half of prior ATR"))
    return events


def momentum_loss_event(m5: pd.DataFrame) -> Optional[Event]:
    """On the last closed bar: the last three bodies average well below the three
    before them, and those earlier bodies moved one way. The event names the
    direction that is losing momentum, not a forecast."""
    if m5 is None or len(m5) < 8:
        return None
    body = (m5["close"] - m5["open"]).astype(float)
    recent = body.iloc[-3:]
    earlier = body.iloc[-6:-3]
    earlier_mean = earlier.abs().mean()
    if earlier_mean <= 0:
        return None
    if recent.abs().mean() > MOMENTUM_LOSS_RATIO * earlier_mean:
        return None
    earlier_all_up = bool((earlier > 0).all())
    earlier_all_down = bool((earlier < 0).all())
    if not (earlier_all_up or earlier_all_down):
        return None  # the earlier bodies did not move one way, so there was no momentum to lose
    direction = "bullish" if earlier_all_up else "bearish"
    return Event("MOMENTUM_LOSS", "M5", _bar_time(m5, len(m5) - 1), direction,
                 float(m5["close"].iloc[-1]),
                 f"last 3 bar bodies average {recent.abs().mean() / earlier_mean:.0%} of the prior 3")


def sweep_events(obs: Observations) -> List[Event]:
    """Liquidity sweeps already detected by analysis.liquidity. A low sweep that
    closed back above the level is a bullish reaction, and a high sweep that
    closed back below is bearish."""
    events: List[Event] = []
    for s in obs.sweeps:
        side = "bullish" if s.kind == "sweep_low" else "bearish"
        reclaim = "closed back above it" if side == "bullish" else "closed back below it"
        events.append(Event("SWEEP", "M5", pd.Timestamp(s.time), side, float(s.level_price),
                            f"{s.label}; M5 {reclaim}"))
    return events


def structure_events(candles_closed: dict) -> List[Event]:
    """BOS/MSS transitions on M5, M15, H1 and H4, plus pullbacks on H1."""
    events: List[Event] = []
    events += structure_transitions(candles_closed.get("M5"), "M5", EVENT_WINDOW_M5)
    events += structure_transitions(candles_closed.get("M15"), "M15", EVENT_WINDOW_H1)
    events += structure_transitions(candles_closed.get("H1"), "H1", EVENT_WINDOW_H1)
    events += structure_transitions(candles_closed.get("H4"), "H4", EVENT_WINDOW_H1)
    pb = pullback_event(candles_closed.get("H1"), "H1")
    if pb:
        events.append(pb)
    return events


def fvg_events(m5: Optional[pd.DataFrame]) -> List[Event]:
    """Fair value gaps as events at their formation bar. The retest/fill status is in the detail.
    FILLED gaps are no longer active, so they are not emitted as events; OPEN and RETESTED ones are."""
    from analysis.v2.fvg import FILLED, find_fvgs
    out: List[Event] = []
    for g in find_fvgs(m5):
        if g.status == FILLED:
            continue
        size = f", {g.size_atr:.2f} ATR wide" if g.size_atr is not None else ""
        out.append(Event("FVG", "M5", g.formed_at, g.direction, g.mid,
                         f"{g.direction} fair value gap {g.low:.2f}-{g.high:.2f}{size}; {g.status.lower()}"))
    return out


def price_events(candles_closed: dict, obs: Observations) -> List[Event]:
    m5 = candles_closed.get("M5")
    events: List[Event] = []
    events += fvg_events(m5)
    events += sweep_events(obs)
    events += displacement_events(m5)
    events += volatility_events(m5)
    events += range_events(m5)
    mom = momentum_loss_event(m5)
    if mom:
        events.append(mom)
    return events


def sort_events(events: List[Event]) -> List[Event]:
    return sorted(events, key=lambda e: (e.time, e.timeframe, e.kind, e.detail))


def event_identity(e: Event) -> tuple:
    """What makes two events the same event: type, timeframe, bar time, direction and
    level (to the cent). Two records with all of these equal describe one event."""
    price = None if e.price is None else round(float(e.price), 2)
    return (e.kind, e.timeframe, pd.Timestamp(e.time), e.direction, price)


AREA_EVENT_KINDS = ("BREAKOUT", "RETEST", "FAILED_BREAKOUT", "REJECTION")


def collapse_area_events(events: Sequence[Event], price: Optional[float]) -> List[Event]:
    """One event per bar, kind and direction for area events. The same bar can break or reject
    several nearby areas, and those areas differ only by a point or two, so they describe one
    market move. The representative is the record nearest the current price (ties keep the first
    record), and every level is kept in `levels` and listed in the detail. Other events pass through
    unchanged, in their original order."""
    groups: dict = {}
    order: List[tuple] = []
    passthrough: List[Event] = []
    for e in events:
        if e.kind not in AREA_EVENT_KINDS:
            passthrough.append(e)
            continue
        key = (e.kind, e.timeframe, pd.Timestamp(e.time), e.direction)
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(e)

    out: List[Event] = list(passthrough)
    for key in order:
        members = groups[key]
        rep = min(members, key=lambda m: abs(float(m.price) - price) if price is not None and m.price is not None
                  else 0.0)
        levels = tuple(sorted({round(float(m.price), 2) for m in members if m.price is not None}))
        others = [f"{lvl:.2f}" for lvl in levels if rep.price is None or round(float(rep.price), 2) != lvl]
        detail = rep.detail + (f"; also at {', '.join(others)}" if others else "")
        out.append(replace(rep, detail=detail, levels=levels))
    return sorted(out, key=lambda e: (e.time, e.kind, e.direction or ""))


def dedupe_events(events: List[Event]) -> List[Event]:
    """Keep the first record of each event identity. Different times, directions or
    levels are different events and are kept."""
    seen = set()
    out: List[Event] = []
    for e in events:
        key = event_identity(e)
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out
