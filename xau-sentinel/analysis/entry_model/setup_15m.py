"""15M layer: setup formation. Answers "Is a meaningful setup forming in the right context?"

Every condition below is independent evidence, not one mandatory chain. A setup can be built from
sweep+MSS+displacement+FVG, or from MSS+displacement+retracement+FVG, or any other combination that
actually occurred in the data -- nothing here forces a fixed order.

Nothing here re-derives a detector that already exists: liquidity sweeps (analysis.liquidity),
structure/BOS/MSS and displacement (analysis.structure), FVG (analysis.v2.fvg), OTE
(analysis.entry_model.ote), key areas (analysis.v2.key_areas), session/swing levels (analysis.zones).
"""
from typing import Optional

import pandas as pd

from analysis.entry_model.common import ev_dict, gather_directional_evidence, item
from analysis.entry_model.ote import compute_ote
from analysis.structure import analyze_structure, compute_atr
from analysis.v2.key_areas import build_key_areas
from analysis.zones import compute_zones

SETUP_STATES = ("WAITING", "SETUP_DEVELOPING", "SETUP_CONFIRMED", "CONFLICTED")
CONFIRM_MIN_CATEGORIES = 2  # distinct evidence categories required for SETUP_CONFIRMED, not just one


def _ote_for_direction(m15, direction: str, fvg) -> Optional[dict]:
    """OTE of the most recent completed swing-to-swing leg in the setup direction. No sweep is
    required to define the impulse here -- unlike V1, the leg is simply the latest confirmed swing
    pair, reusing analyze_structure's own swings."""
    swings = analyze_structure(m15).swings
    highs = [p for p in swings if p.kind == "high"]
    lows = [p for p in swings if p.kind == "low"]
    if not highs or not lows:
        return None
    last_high, last_low = highs[-1], lows[-1]
    if direction == "LONG" and last_high.index > last_low.index:
        impulse_low, impulse_high = last_low.price, last_high.price
    elif direction == "SHORT" and last_low.index > last_high.index:
        impulse_low, impulse_high = last_low.price, last_high.price
    else:
        return None
    if impulse_high <= impulse_low:
        return None
    zl, zh = (fvg.low, fvg.high) if fvg is not None else (None, None)
    return compute_ote(direction, impulse_low, impulse_high, zl, zh).to_dict()


def evaluate_setup(m15: Optional[pd.DataFrame], m5: Optional[pd.DataFrame], h1: Optional[pd.DataFrame],
                   h4: Optional[pd.DataFrame], htf_context: str, intraday_bias: str,
                   compatible_with_htf: Optional[bool], price: float) -> dict:
    """`htf_context`/`intraday_bias`/`compatible_with_htf` are the 1D+4H and 1H layers' own already-
    computed readings (htf.py/intraday.py), passed in so this layer's direction gate can see the
    full hierarchy, not just 1H -- see the "direction/state gating" fix: a 15M setup must not
    resolve a direction while 1D/4H have not agreed on a bias, or while 1H's bias is unresolved or
    incompatible with that bias, even if 15M's own evidence is one-sided."""
    htf_ready = (htf_context in ("BULLISH", "BEARISH") and intraday_bias in ("BULLISH", "BEARISH")
                and bool(compatible_with_htf))

    if m15 is None or len(m15) < 30:
        return {"setup_direction": "NEUTRAL", "setup_status": "WAITING", "evidence_categories": [],
                "supporting_evidence": [], "contradicting_evidence": [], "fvg": None, "ote": None,
                "checklist": [item("Meaningful location", "WAITING", "15M", "not enough 15M history")]}

    zones = compute_zones(m5, h1, h4) if m5 is not None and len(m5) else {}
    atr_series = compute_atr(m15) if len(m15) > 20 else None
    areas = build_key_areas(m5, h1, h4, price) if m5 is not None and len(m5) else []

    # Evidence is always gathered (so the checklist stays informative about what 15M is actually
    # showing), even when the HTF/1H gate below blocks a direction from being assigned.
    sides = gather_directional_evidence(m15, zones, atr_series, price, areas, "M15")
    bull_cats = {e["kind"] for e in sides["bullish"]}
    bear_cats = {e["kind"] for e in sides["bearish"]}
    n_bull_cats, n_bear_cats = len(bull_cats), len(bear_cats)

    if not htf_ready:
        # 1D/4H has not agreed on a bias, or 1H is unresolved or incompatible with it: no setup
        # direction can be established yet, regardless of how one-sided the 15M evidence is. This
        # is the fix for the direction/state gating finding -- a lower timeframe must not resolve a
        # direction the higher timeframes have not actually supported.
        direction = "NEUTRAL"
    elif n_bull_cats == 0 and n_bear_cats == 0:
        direction = "NEUTRAL"
    elif n_bull_cats > n_bear_cats and intraday_bias != "BEARISH":
        # Direction: a single opposing data point (one stray FVG against an otherwise bullish
        # sweep and key-area read, say) is not treated as a veto -- real price action almost
        # always has some evidence on both sides at once. The majority of independent evidence
        # CATEGORIES decides; a genuine TIE (including 0-0) is reported as NEUTRAL/CONFLICTED
        # rather than forced, and a clear majority that contradicts the already-established 1H
        # bias is a conflict too -- a lower timeframe must not simply override a higher one.
        direction = "LONG"
    elif n_bear_cats > n_bull_cats and intraday_bias != "BULLISH":
        direction = "SHORT"
    else:
        direction = "CONFLICTED"

    cats = bull_cats if direction == "LONG" else bear_cats if direction == "SHORT" else set()
    evidence_list = sides["bullish"] if direction == "LONG" else sides["bearish"] if direction == "SHORT" else []
    contra_list = (sides["bearish"] if direction == "LONG" else sides["bullish"] if direction == "SHORT" else
                  sides["bullish"] + sides["bearish"])

    fvg = next((e["fvg"] for e in evidence_list if e["kind"] == "FVG"), None)
    ote = _ote_for_direction(m15, direction, fvg) if direction in ("LONG", "SHORT") else None

    if direction in ("LONG", "SHORT") and len(cats) >= CONFIRM_MIN_CATEGORIES:
        status = "SETUP_CONFIRMED"
    elif direction in ("LONG", "SHORT"):
        status = "SETUP_DEVELOPING"
    elif direction == "CONFLICTED":
        status = "CONFLICTED"
    else:
        status = "WAITING"

    checklist = [
        item("Meaningful location", "PASS" if areas else "WAITING", "H1/H4", f"{len(areas)} key area(s)"),
        item("Liquidity interaction", "PASS" if "LIQUIDITY_SWEEP" in cats else "WAITING", "15M",
            "liquidity sweep in the setup direction"),
        item("MSS/BOS", "PASS" if "MSS_BOS" in cats else "WAITING", "15M",
            "structure shift or break of structure in the setup direction"),
        item("Displacement", "PASS" if "DISPLACEMENT" in cats else "WAITING", "15M",
            "outsized candle in the setup direction"),
        item("FVG", "PASS" if "FVG" in cats else "WAITING", "15M", "fair value gap in the setup direction"),
        item("OTE", "PASS" if ote and ote.get("overlap") == "FULL" else
            "PARTIAL" if ote and ote.get("overlap") == "PARTIAL" else
            "NOT_APPLICABLE" if ote is None else "WAITING", "15M",
            "retracement band of the latest swing-to-swing leg; confluence only"),
        item("Reaction/rejection", "PASS" if "KEY_AREA_REACTION" in cats else "WAITING", "H1/H4",
            "price reacting from a key area"),
        item("Retest", "PASS" if (fvg is not None and fvg.status == "RETESTED") else
            "WAITING" if fvg is not None else "NOT_APPLICABLE", "15M", "FVG retested"),
        item("Setup direction", "PASS" if direction in ("LONG", "SHORT") else
            "FAIL" if direction == "CONFLICTED" else "WAITING", "15M",
            f"direction={direction}" if htf_ready else
            f"direction={direction} (blocked: 1D/4H and 1H must agree on a bias first)",
            dependency=None if htf_ready else "1H bias compatible with HTF context"),
    ]

    return {
        "setup_direction": direction, "setup_status": status, "evidence_categories": sorted(cats),
        "supporting_evidence": [ev_dict(e["evidence"]) for e in evidence_list],
        "contradicting_evidence": [ev_dict(e["evidence"]) for e in contra_list],
        "fvg": None if fvg is None else {"direction": fvg.direction, "low": round(fvg.low, 2),
                                         "high": round(fvg.high, 2), "status": fvg.status,
                                         "formed_at": pd.Timestamp(fvg.formed_at).isoformat()},
        "ote": ote,
        "checklist": checklist,
    }
