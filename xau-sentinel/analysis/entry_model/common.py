"""Shared helpers for the Top-Down Multi-Timeframe Entry Model (hierarchy.py and its per-timeframe
layers: htf.py, intraday.py, setup_15m.py, confirmation_5m.py, precision_1m.py).

Evidence is the exact same typed record Analysis Engine V2 already uses
(analysis/v2/models.py::Evidence) -- reused here, not re-invented, so every conclusion this model
produces traces to a timeframe, a timestamp, a kind, a price/value, and a source module.
"""
from typing import Dict, List, Optional

import pandas as pd

from analysis.liquidity import detect_sweeps
from analysis.structure import analyze_structure, displacement_at
from analysis.v2.fvg import FILLED, find_fvgs
from analysis.v2.key_areas import relationship
from analysis.v2.models import Evidence

STATUSES = ("PASS", "FAIL", "WAITING", "PARTIAL", "NOT_APPLICABLE", "INVALIDATED")
DIRECTIONS = ("LONG", "SHORT", "NEUTRAL", "CONFLICTED")


def ev(timeframe: str, timestamp, kind: str, value: Optional[float], source: str, note: str = "") -> Evidence:
    """Builds an Evidence record. `timestamp` may be a pandas Timestamp, a datetime, or None (rare --
    an observation about the current state rather than one specific bar); `value` may be None when
    the evidence is not itself a price level."""
    ts = pd.Timestamp.utcnow().to_pydatetime() if timestamp is None else pd.Timestamp(timestamp).to_pydatetime()
    val = float("nan") if value is None else float(value)
    return Evidence(timeframe=timeframe, timestamp=ts, kind=kind, value=val, source=source, note=note)


def ev_dict(e: Evidence) -> dict:
    value = e.value
    return {"timeframe": e.timeframe, "timestamp": pd.Timestamp(e.timestamp).isoformat(), "kind": e.kind,
            "value": None if value != value else round(value, 2),  # value != value is the NaN check
            "source": e.source, "note": e.note}


def item(name: str, status: str, timeframe: str, reason: str, evidence: Optional[Evidence] = None,
         dependency: Optional[str] = None) -> dict:
    if status not in STATUSES:
        raise ValueError(f"unknown checklist status {status!r} for {name!r}")
    return {"name": name, "status": status, "timeframe": timeframe, "reason": reason,
            "evidence": None if evidence is None else ev_dict(evidence), "dependency": dependency}


def bias_from_state(state: Optional[str]) -> str:
    """BULLISH/BEARISH structure states read as a bias; PULLBACK/RANGING/unknown read as neutral --
    the same mapping analysis/entry_model/model.py (V1) used, reused here unchanged."""
    return {"BULLISH": "bullish", "BEARISH": "bearish"}.get(state, "neutral")


def order_word(direction: str) -> str:
    """LONG/SHORT -> the BUY/SELL vocabulary ai.strategy.rules uses."""
    return {"LONG": "BUY", "SHORT": "SELL"}[direction]




def gather_directional_evidence(df: pd.DataFrame, zones: dict, atr_series, price: float,
                                key_areas, timeframe: str) -> Dict[str, List[dict]]:
    """Independent (not chained) directional evidence on any closed-candle `df`: liquidity sweep,
    MSS/BOS, displacement, FVG, and reaction from a key area. Used identically by the 15M setup
    layer and the 5M confirmation layer (and could be reused by 1M) -- one implementation, not one
    copy per timeframe. Returns {"bullish": [...], "bearish": [...]}, each entry
    {"kind", "evidence", and, for FVG, "fvg"}."""
    bullish: List[dict] = []
    bearish: List[dict] = []
    if df is None or len(df) < 30:
        return {"bullish": bullish, "bearish": bearish}

    # Only the single MOST RECENT sweep (of either kind) is "the" current liquidity event -- the
    # last several sweeps very often include one of each kind, which is the normal state of a
    # ranging market, not a directional conflict.
    sweeps = detect_sweeps(df, zones)
    if sweeps:
        s = max(sweeps, key=lambda x: pd.Timestamp(x.time))
        bucket = bullish if s.kind == "sweep_low" else bearish if s.kind == "sweep_high" else None
        if bucket is not None:
            bucket.append({"kind": "LIQUIDITY_SWEEP",
                           "evidence": ev(timeframe, s.time, s.kind.upper(), s.level_price,
                                         "analysis.liquidity", s.label)})

    # last_mss (a reversal against the prior trend) is the more current fact when both are set --
    # last_bos and last_mss often point opposite ways at once (that is what makes TRANSITION a
    # separate bias reading in intraday.py), so OR-ing them into both buckets would manufacture a
    # conflict out of one structure reading instead of reflecting two independent facts.
    struct = analyze_structure(df)
    last_bar_t = df["time"].iloc[-1]
    current_mss_bos = struct.last_mss or struct.last_bos
    if current_mss_bos == "bullish":
        bullish.append({"kind": "MSS_BOS", "evidence": ev(timeframe, last_bar_t, "MSS_BOS_BULLISH",
                        price, "analysis.structure", struct.reason)})
    elif current_mss_bos == "bearish":
        bearish.append({"kind": "MSS_BOS", "evidence": ev(timeframe, last_bar_t, "MSS_BOS_BEARISH",
                        price, "analysis.structure", struct.reason)})

    atr = float(atr_series.iloc[-1]) if atr_series is not None and len(atr_series) else None
    disp = displacement_at(df, len(df) - 1, atr=atr_series) if atr_series is not None and len(atr_series) else None
    if disp == "bullish":
        bullish.append({"kind": "DISPLACEMENT", "evidence": ev(timeframe, last_bar_t,
                        "DISPLACEMENT_BULLISH", price, "analysis.structure",
                        "outsized candle beyond the configured ATR multiple")})
    elif disp == "bearish":
        bearish.append({"kind": "DISPLACEMENT", "evidence": ev(timeframe, last_bar_t,
                        "DISPLACEMENT_BEARISH", price, "analysis.structure",
                        "outsized candle beyond the configured ATR multiple")})

    # Only the single most recently formed non-filled gap counts as the current FVG. A ranging
    # market can easily hold a small bullish gap and a small bearish gap within the same lookback
    # window at once; that is market texture, not two independent trade setups forming together.
    open_gaps = [g for g in find_fvgs(df) if g.status != FILLED]
    if open_gaps:
        g = max(open_gaps, key=lambda x: pd.Timestamp(x.formed_at))
        bucket = bullish if g.direction == "bullish" else bearish
        bucket.append({"kind": "FVG", "fvg": g,
                       "evidence": ev(timeframe, g.formed_at, "FVG", g.mid, "analysis.v2.fvg",
                                     f"{g.low:.2f}-{g.high:.2f} ({g.status.lower()})")})

    # Only the SINGLE nearest key area counts as a current reaction. A support below and a
    # resistance above can both legitimately be "nearby" at once (the normal state of a range) --
    # that is a location fact, not a directional vote on both sides at once.
    if atr is not None and atr > 0 and key_areas:
        rels = [(a, relationship(a, price, atr)) for a in key_areas]
        nearby = [(a, r) for a, r in rels if r.relation in ("INSIDE", "APPROACHING")]
        if nearby:
            a, rel = min(nearby, key=lambda ar: abs(ar[1].distance_atr))
            bucket = bullish if a.side == "SUPPORT" else bearish if a.side == "RESISTANCE" else None
            if bucket is not None:
                bucket.append({"kind": "KEY_AREA_REACTION",
                               "evidence": ev(timeframe, last_bar_t, f"{a.side}_REACTION", a.mid,
                                             "analysis.v2.key_areas",
                                             f"price {rel.relation.lower()} {a.side.lower()} {a.low:.2f}-{a.high:.2f}")})

    return {"bullish": bullish, "bearish": bearish}
