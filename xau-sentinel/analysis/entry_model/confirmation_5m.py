"""5M layer: entry confirmation. Answers "Is there enough lower-timeframe confirmation to consider
an entry?"

Deliberately NOT the V1 rule ("a fresh 5M MSS at the exact moment price retraces into the FVG").
The M5-resolution audit (docs/entry-model-v1-m5-confirmation-audit.md) found that rigid simultaneity
requirement produced 0/11 confirmations even at full M5 resolution over 24 hours per case -- not
because 5M confirmation itself is useless, but because requiring the exact bar-level coincidence of
retracement and a *fresh* M5 structure shift is unusually restrictive (the audit's "Mixed" finding).
Here, 5M confirmation is the same kind of independent, multi-category evidence check the 15M layer
uses (reusing analysis.entry_model.common.gather_directional_evidence, not a second copy of it),
read for whether the current 5M structure reinforces the 15M setup -- not for one exact bar.
"""
from typing import Optional

import pandas as pd

from analysis.entry_model.common import ev_dict, gather_directional_evidence, item
from analysis.structure import compute_atr
from analysis.v2.key_areas import build_key_areas
from analysis.zones import compute_zones

CONFIRMATION_STATES = ("WAITING", "DEVELOPING", "CONFIRMED", "CONFLICTED")
CONFIRM_MIN_CATEGORIES = 2


def evaluate_confirmation(m5: Optional[pd.DataFrame], h1: Optional[pd.DataFrame],
                          h4: Optional[pd.DataFrame], setup_direction: str, price: float) -> dict:
    if setup_direction not in ("LONG", "SHORT"):
        return {"confirmation_status": "NOT_APPLICABLE", "evidence_categories": [],
                "supporting_evidence": [], "contradicting_evidence": [],
                "checklist": [item("Structure confirmation", "NOT_APPLICABLE", "5M",
                                   "no 15M setup direction to confirm yet", dependency="15M setup")]}
    if m5 is None or len(m5) < 30:
        return {"confirmation_status": "WAITING", "evidence_categories": [], "supporting_evidence": [],
                "contradicting_evidence": [],
                "checklist": [item("Structure confirmation", "WAITING", "5M", "not enough 5M history")]}

    zones = compute_zones(m5, h1, h4) if h1 is not None else {}
    atr_series = compute_atr(m5) if len(m5) > 20 else None
    areas = build_key_areas(m5, h1, h4, price) if h1 is not None else []

    sides = gather_directional_evidence(m5, zones, atr_series, price, areas, "M5")
    own_side = sides["bullish"] if setup_direction == "LONG" else sides["bearish"]
    opposite_side = sides["bearish"] if setup_direction == "LONG" else sides["bullish"]
    cats = {e["kind"] for e in own_side}
    opposite_cats = {e["kind"] for e in opposite_side}

    # A single opposing data point does not veto confirmation (see setup_15m.py's identical
    # reasoning) -- only a STRICT MAJORITY of categories against the 15M setup direction is a
    # real conflict.
    if len(opposite_cats) > len(cats):
        status = "CONFLICTED"
    elif len(cats) >= CONFIRM_MIN_CATEGORIES:
        status = "CONFIRMED"
    elif own_side:
        status = "DEVELOPING"
    else:
        status = "WAITING"

    checklist = [
        item("Structure confirmation", "PASS" if "MSS_BOS" in cats else "WAITING", "5M",
            "5M MSS/BOS aligned with the 15M setup direction"),
        item("MSS/BOS", "PASS" if "MSS_BOS" in cats else "WAITING", "5M", "structure shift or break"),
        item("Displacement", "PASS" if "DISPLACEMENT" in cats else "WAITING", "5M",
            "outsized candle aligned with the setup direction"),
        item("FVG/retest", "PASS" if "FVG" in cats else "WAITING", "5M",
            "fair value gap aligned with the setup direction"),
        item("Liquidity interaction", "PASS" if "LIQUIDITY_SWEEP" in cats else "WAITING", "5M",
            "liquidity sweep aligned with the setup direction"),
        item("Lower-timeframe alignment",
            "FAIL" if len(opposite_cats) > len(cats) else "PASS" if own_side else "WAITING", "5M",
            f"{len(cats)} aligned categor{'y' if len(cats) == 1 else 'ies'}, "
            f"{len(opposite_cats)} opposing"),
    ]

    return {
        "confirmation_status": status, "evidence_categories": sorted(cats),
        "supporting_evidence": [ev_dict(e["evidence"]) for e in own_side],
        "contradicting_evidence": [ev_dict(e["evidence"]) for e in opposite_side],
        "checklist": checklist,
    }
