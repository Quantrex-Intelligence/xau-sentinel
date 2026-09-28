"""Deterministic, explicitly weighted feature similarity — no ML, no
statistically-tuned weights (see config.py's AI_SIMILARITY_WEIGHT_* comments).

A feature missing on either side of the comparison is excluded from BOTH
the numerator and the denominator (renormalized weighting), never scored as
a mismatch and never fabricated — a candidate missing one optional field is
still compared fairly on everything else it does have.
"""
from typing import List, Optional, Tuple

import config
from ai.similarity.models import SetupFeatures

# (feature name, weight config attr) — categorical features compared by
# case-insensitive exact match.
_CATEGORICAL_FEATURES = [
    ("h1_structure", "AI_SIMILARITY_WEIGHT_H1_STRUCTURE"),
    ("m5_structure", "AI_SIMILARITY_WEIGHT_M5_STRUCTURE"),
    ("m15_structure", "AI_SIMILARITY_WEIGHT_M15_STRUCTURE"),
    ("h4_structure", "AI_SIMILARITY_WEIGHT_H4_STRUCTURE"),
    ("liquidity_kind", "AI_SIMILARITY_WEIGHT_LIQUIDITY"),
    ("mss_direction", "AI_SIMILARITY_WEIGHT_MSS"),
    ("displacement", "AI_SIMILARITY_WEIGHT_DISPLACEMENT"),
    ("regime", "AI_SIMILARITY_WEIGHT_REGIME"),
    ("session", "AI_SIMILARITY_WEIGHT_SESSION"),
]


def _categorical_match(a: Optional[str], b: Optional[str]) -> Optional[bool]:
    if a is None or b is None:
        return None  # not comparable — excluded from scoring entirely
    return a.strip().lower() == b.strip().lower()


def _rr_similarity(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    tolerance = config.AI_SIMILARITY_RR_TOLERANCE
    if tolerance <= 0:
        return 1.0 if a == b else 0.0
    return max(0.0, 1.0 - abs(a - b) / tolerance)


def score(query: SetupFeatures, candidate: SetupFeatures) -> Tuple[float, List[str], List[str]]:
    """Returns (similarity in [0, 1], matched_features, different_features).
    A feature contributes to neither list when it's missing on either side —
    "not compared" is distinct from "different"."""
    weighted_sum = 0.0
    weight_total = 0.0
    matched: List[str] = []
    different: List[str] = []

    for name, weight_attr in _CATEGORICAL_FEATURES:
        weight = getattr(config, weight_attr)
        is_match = _categorical_match(getattr(query, name), getattr(candidate, name))
        if is_match is None:
            continue
        weight_total += weight
        if is_match:
            weighted_sum += weight
            matched.append(name)
        else:
            different.append(name)

    rr_similarity = _rr_similarity(query.planned_rr, candidate.planned_rr)
    if rr_similarity is not None:
        weight = config.AI_SIMILARITY_WEIGHT_RR
        weight_total += weight
        weighted_sum += weight * rr_similarity
        (matched if rr_similarity >= 0.8 else different).append("planned_rr")

    if weight_total == 0:
        return 0.0, matched, different
    return round(weighted_sum / weight_total, 4), matched, different
