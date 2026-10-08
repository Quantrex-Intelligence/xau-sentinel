"""HTF layer (1D + 4H): location and context. Answers "Where is price, and is this an important
location?" -- never requires a trade setup.

Reuses analysis.v2.key_areas.build_key_areas/relationship for every location primitive (supply,
demand, tested S/R, PDH/PDL, session levels, swing levels, consolidation, psychological levels,
equal highs/lows) -- nothing here re-derives a key area. D1 structure/swings are the one piece
build_key_areas does not cover (it takes M5/H1/H4 only); added here via find_swing_points and
analyze_structure, the same primitives every other timeframe in this codebase already uses.
"""
from typing import List, Optional

import pandas as pd

from analysis.entry_model.common import bias_from_state, ev, ev_dict, item
from analysis.structure import analyze_structure, compute_atr, find_swing_points
from analysis.v2.key_areas import build_key_areas, relationship

LOCATION_STATES = ("AT_ZONE", "APPROACHING_ZONE", "BETWEEN_ZONES", "AWAY_FROM_ZONE", "UNKNOWN")
CONTEXT_STATES = ("BULLISH", "BEARISH", "NEUTRAL", "TRANSITION")
MAJOR_SWINGS_PER_SIDE = 2


def _d1_major_levels(d1: Optional[pd.DataFrame]) -> List[dict]:
    """D1 swing highs/lows as major POIs -- reuses find_swing_points, the same primitive H1/H4
    swings already use inside build_key_areas."""
    if d1 is None or len(d1) < 15:
        return []
    swings = find_swing_points(d1)
    out = []
    picks = ([p for p in swings if p.kind == "high"][-MAJOR_SWINGS_PER_SIDE:] +
             [p for p in swings if p.kind == "low"][-MAJOR_SWINGS_PER_SIDE:])
    for p in picks:
        e = ev("D1", p.time, f"D1_SWING_{p.kind.upper()}", p.price, "analysis.structure",
              f"confirmed D1 swing {p.kind}")
        out.append({"label": f"D1 swing {p.kind}", "price": round(p.price, 2), "evidence": ev_dict(e)})
    return out


def _location(areas, price: float, atr: float) -> dict:
    if not areas or atr is None or atr != atr or atr <= 0:
        return {"status": "UNKNOWN", "nearest_area": None, "relation": None}
    rels = [(a, relationship(a, price, atr)) for a in areas]
    nearest_area, nearest_rel = min(rels, key=lambda ar: abs(ar[1].distance_atr))
    if nearest_rel.relation == "INSIDE":
        status = "AT_ZONE"
    elif nearest_rel.relation == "APPROACHING":
        status = "APPROACHING_ZONE"
    else:
        # Bracketed by a support area below AND a resistance area above (regardless of distance)
        # reads as BETWEEN_ZONES; otherwise price is simply AWAY_FROM every known area.
        below = any(a.high <= price for a, _ in rels)
        above = any(a.low >= price for a, _ in rels)
        status = "BETWEEN_ZONES" if (below and above) else "AWAY_FROM_ZONE"
    area_dict = {"low": nearest_area.low, "high": nearest_area.high, "side": nearest_area.side,
                "strength": nearest_area.strength_status, "strength_reason": nearest_area.strength_reason,
                "distance_atr": round(nearest_rel.distance_atr, 2)}
    return {"status": status, "nearest_area": area_dict, "relation": nearest_rel.relation}


def evaluate_htf(d1: Optional[pd.DataFrame], h4: Optional[pd.DataFrame], h1: Optional[pd.DataFrame],
                 m5: Optional[pd.DataFrame], price: float) -> dict:
    """`m5`/`h1`/`h4` are build_key_areas' own required inputs; `d1` adds major D1 POIs on top."""
    d1_res = analyze_structure(d1) if d1 is not None and len(d1) >= 15 else None
    h4_res = analyze_structure(h4) if h4 is not None and len(h4) >= 15 else None
    d1_bias = bias_from_state(d1_res.state) if d1_res else "neutral"
    h4_bias = bias_from_state(h4_res.state) if h4_res else "neutral"

    if d1_bias == h4_bias and d1_bias != "neutral":
        context = "BULLISH" if d1_bias == "bullish" else "BEARISH"
    elif {d1_bias, h4_bias} == {"bullish", "bearish"}:
        context = "TRANSITION"  # 1D and 4H actively disagree: a real conflict, not "no data yet"
    else:
        context = "NEUTRAL"

    atr_series = compute_atr(m5) if m5 is not None and len(m5) > 20 else None
    atr = float(atr_series.iloc[-1]) if atr_series is not None and len(atr_series) else None
    areas = build_key_areas(m5, h1, h4, price) if m5 is not None and len(m5) else []
    major_d1 = _d1_major_levels(d1)
    location = _location(areas, price, atr)

    sd_kinds = {c.evidence.kind for a in areas for c in a.components}
    checklist = [
        item("Key level identified", "PASS" if (areas or major_d1) else "WAITING", "1D/4H",
            f"{len(areas)} merged key area(s), {len(major_d1)} D1 swing level(s)"),
        item("S/R identified", "PASS" if any(a.side in ("SUPPORT", "RESISTANCE") for a in areas) else "WAITING",
            "H1/H4", "from the tested-zone and swing components of build_key_areas"),
        item("Supply/Demand identified", "PASS" if ("SUPPLY_ZONE" in sd_kinds or "DEMAND_ZONE" in sd_kinds) else "WAITING",
            "H1", "H1 displacement-origin supply/demand zone"),
        item("POI identified", "PASS" if (areas or major_d1) else "WAITING", "1D/4H/H1",
            "merged key area and/or D1 swing POI"),
        item("Relevant liquidity identified", "PASS" if any("EQUAL" in k for k in sd_kinds) else "WAITING",
            "M5", "equal highs/lows among the key-area components"),
        item("Price interacting with meaningful area",
            "PASS" if location["status"] in ("AT_ZONE", "APPROACHING_ZONE") else
            "NOT_APPLICABLE" if location["status"] == "UNKNOWN" else "WAITING",
            "1D/4H", f"location={location['status']}"),
    ]

    return {
        "htf_location": location["status"], "htf_context": context,
        "d1_bias": d1_bias, "h4_bias": h4_bias,
        "d1_structure": None if d1_res is None else d1_res.state,
        "h4_structure": None if h4_res is None else h4_res.state,
        "nearest_area": location["nearest_area"], "relation": location["relation"],
        "key_areas": [{"low": a.low, "high": a.high, "side": a.side, "strength": a.strength_status}
                      for a in areas],
        "major_d1_levels": major_d1,
        "checklist": checklist,
    }
