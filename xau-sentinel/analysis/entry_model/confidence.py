"""Setup Confidence for the Entry Model. HEURISTIC and UNCALIBRATED.

This is an explicit evidence framework, not a probability. Every point is attached to a named item, so
the number can always be traced back to its evidence. Items that describe the same thing share a group
with a cap, so correlated evidence is not counted twice. Contradictions subtract a fixed amount each.

The weights are research settings chosen for this version. They have not been fitted to outcomes.
Calibrated probabilities need historical outcomes linked to these conditions, which do not exist yet.
"""
from dataclasses import dataclass
from typing import List

CONFIDENCE_TYPE = "HEURISTIC"
CONTRADICTION_PENALTY = 5
CONTRADICTION_MAX = 20

# name -> (group, points). Group caps below.
WEIGHTS = {
    "htf_1d_bias": ("htf", 10),
    "htf_4h_bias": ("htf", 10),
    "h1_context_aligned": ("htf", 5),
    "liquidity_sweep": ("liquidity", 15),
    "mss": ("structure", 10),
    "displacement": ("structure", 10),
    "fvg_available": ("fvg", 8),
    "fvg_retracement": ("fvg", 7),
    "key_area_overlaps_fvg": ("key_area", 10),
    "level_confluence": ("key_area", 5),
    "ote_overlap": ("ote", 5),
    "ote_partial": ("ote", 2),
    "confirm_5m": ("confirm", 5),
    "confirm_1m": ("confirm", 5),

    # --- Top-Down Multi-Timeframe Entry Model (hierarchy.py). Additive: the names and groups
    # above (V1, model.py) are untouched, so V1's own tests and behavior never change. ---
    "v2_htf_context": ("v2_htf", 10),
    "v2_htf_location": ("v2_htf", 8),
    "v2_intraday_bias": ("v2_intraday", 8),
    "v2_intraday_compatible": ("v2_intraday", 7),
    "v2_location_quality_high": ("v2_location", 8),
    "v2_location_quality_moderate": ("v2_location", 4),
    "v2_key_area_reaction": ("v2_location", 6),
    "v2_liquidity_sweep_15m": ("v2_liquidity", 10),
    "v2_liquidity_sweep_5m": ("v2_liquidity", 6),
    "v2_structure_15m": ("v2_structure", 8),
    "v2_structure_5m": ("v2_structure", 6),
    "v2_structure_1m": ("v2_structure", 4),
    "v2_displacement_15m": ("v2_momentum", 8),
    "v2_displacement_5m": ("v2_momentum", 5),
    "v2_fvg_15m": ("v2_fvg", 6),
    "v2_fvg_15m_retest": ("v2_fvg", 6),
    "v2_fvg_5m": ("v2_fvg", 4),
    "v2_ote_full": ("v2_ote", 5),
    "v2_ote_partial": ("v2_ote", 2),
    "v2_confirmation_5m": ("v2_ltf", 8),
    "v2_precision_1m": ("v2_ltf", 4),
}
GROUP_CAP = {"htf": 25, "liquidity": 15, "structure": 20, "fvg": 15, "key_area": 15, "ote": 5, "confirm": 10,
            "v2_htf": 15, "v2_intraday": 12, "v2_location": 12, "v2_liquidity": 12, "v2_structure": 15,
            "v2_momentum": 10, "v2_fvg": 12, "v2_ote": 5, "v2_ltf": 10}


@dataclass(frozen=True)
class Evidence:
    name: str
    group: str
    points: int
    kind: str  # POSITIVE | NEGATIVE
    reason: str

    def to_dict(self) -> dict:
        return {"name": self.name, "group": self.group, "points": self.points, "kind": self.kind,
                "reason": self.reason}


def label_for(score: int) -> str:
    if score < 40:
        return "EARLY"
    if score < 60:
        return "DEVELOPING"
    if score < 80:
        return "WELL_SUPPORTED"
    return "STRONG_EVIDENCE"


def score(passed: List[str], reasons: dict, contradictions: List[str]) -> dict:
    """`passed` names the positive items that are true. `reasons` maps each name to its evidence text.
    Returns the total, the label, every contribution after group caps, and the contradictions counted."""
    grouped: dict = {}
    contributions: List[Evidence] = []
    for name in passed:
        if name not in WEIGHTS:
            raise KeyError(f"unknown confidence item {name!r}")
        group, points = WEIGHTS[name]
        grouped.setdefault(group, []).append((name, points))
    for group, items in grouped.items():
        remaining = GROUP_CAP[group]
        for name, points in items:
            used = min(points, remaining)
            remaining -= used
            if used > 0:
                contributions.append(Evidence(name, group, used, "POSITIVE", reasons.get(name, "")))
    penalty = min(CONTRADICTION_PENALTY * len(contradictions), CONTRADICTION_MAX)
    negatives = [Evidence(f"contradiction:{i}", "contradiction", -CONTRADICTION_PENALTY, "NEGATIVE", text)
                 for i, text in enumerate(contradictions)]
    total = sum(e.points for e in contributions) - penalty
    total = max(0, min(100, total))
    return {
        "score": total,
        "type": CONFIDENCE_TYPE,
        "label": label_for(total),
        "positive": [e.to_dict() for e in contributions],
        "negative": [e.to_dict() for e in negatives],
        "caps": GROUP_CAP,
        "note": "Heuristic evidence score. Not a probability and not calibrated against outcomes.",
    }
