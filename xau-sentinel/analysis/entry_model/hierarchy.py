"""Top-Down Multi-Timeframe Entry Model (V2): the active implementation behind
`analysis.entry_model.evaluate`, replacing V1's rigid state machine (analysis/entry_model/model.py,
kept in the repo, unimported from `__init__`, for historical reference and its own tests).

    1D + 4H -> Higher-timeframe location & context   ("Where is price, and is this important?")
    1H      -> Intraday bias                          ("What is the intraday direction?")
    15M     -> Setup formation                        ("Is a meaningful setup forming?")
    5M      -> Entry confirmation                      ("Is there lower-timeframe confirmation?")
    1M      -> Precision entry (optional)              ("Can the entry be refined more precisely?")
    -> Entry candidate -> risk/invalidation/target

Each layer is its own module (htf.py, intraday.py, setup_15m.py, confirmation_5m.py,
precision_1m.py) and reuses existing deterministic primitives -- liquidity sweeps, structure/BOS/MSS,
displacement, FVG, OTE, key areas -- rather than re-detecting any of them. This module only
orchestrates: it resolves the overall state and direction from the hierarchy, builds the confluence
and confidence views, checks invalidation, and produces an entry candidate using the existing,
unmodified `ai.strategy.rules` risk primitives -- exactly as V1 did.

Manual decision support only. Deterministic. No LLM in this path, no order placement, no SL/TP
mutation. See DISCLAIMER below.
"""
from typing import Dict, List, Optional

import pandas as pd

import config
from ai.strategy import rules
from analysis.entry_model import confidence as C
from analysis.entry_model.common import order_word
from analysis.entry_model.confirmation_5m import evaluate_confirmation
from analysis.entry_model.htf import evaluate_htf
from analysis.entry_model.intraday import evaluate_intraday
from analysis.entry_model.precision_1m import evaluate_precision
from analysis.entry_model.setup_15m import evaluate_setup
from analysis.liquidity import LiquidityEvent
from analysis.structure import analyze_structure, compute_atr
from analysis.v2.sequence import build_sequences
from analysis.zones import compute_zones

DISCLAIMER = ("Manual decision support. Not a signal, not an order, and not a prediction. "
              "Confidence is a heuristic evidence score, not a probability.")

REQUIRED = ("M5", "M15", "H1", "H4", "D1")
MIN_BARS = 30

STATES = (
    "NO_CONTEXT", "HTF_LOCATION_IDENTIFIED", "HTF_CONTEXT_ALIGNED", "INTRADAY_BIAS_ESTABLISHED",
    "SETUP_DEVELOPING", "SETUP_CONFIRMED", "ENTRY_CONFIRMATION_DEVELOPING", "ENTRY_CONFIRMED",
    "PRECISION_AVAILABLE", "ENTRY_READY", "CONFLICTED", "INVALIDATED", "EXPIRED",
)


def _closed(df):
    if df is None or len(df) == 0:
        return None
    if "is_closed" in df.columns:
        df = df[df["is_closed"].astype(bool)]
    return df.reset_index(drop=True)


def _sweep_anchor(setup: dict, m15: pd.DataFrame, direction: str) -> Optional[dict]:
    """The most recent LIQUIDITY_SWEEP item in the setup's own supporting evidence, if any, with
    its exact bar re-read from M15 -- the same sweep-extreme-as-invalidation-anchor idea V1 used,
    reused here only when a sweep actually is part of THIS setup's evidence (it is optional now)."""
    sweeps = [e for e in setup["supporting_evidence"] if e["kind"] in ("SWEEP_LOW", "SWEEP_HIGH")]
    if not sweeps:
        return None
    s = max(sweeps, key=lambda e: e["timestamp"])
    sweep_time = pd.Timestamp(s["timestamp"])
    match = m15[m15["time"] == sweep_time]
    if not len(match):
        return None
    bar = match.iloc[0]
    extreme = float(bar["low"] if direction == "LONG" else bar["high"])
    idx = int(m15.index[m15["time"] == sweep_time][0])
    age_bars = (len(m15) - 1) - idx
    return {"time": sweep_time, "extreme": extreme, "age_bars": age_bars,
            "age_minutes": age_bars * 15, "level": s["value"], "kind": s["kind"]}


def _invalidation_check(direction: str, htf: dict, intraday: dict, setup: dict, m15: pd.DataFrame,
                        sweep_anchor: Optional[dict], price: float, atr15: Optional[float]) -> Optional[str]:
    """Returns the invalidation reason, or None. Every rule reuses an existing structural fact
    (sweep-sequence invalidation, an opposing MSS superseding the established bias, or price
    closing decisively through the identified HTF area) -- nothing new is detected here."""
    if direction not in ("LONG", "SHORT"):
        return None

    # 15M setup invalidated: a sweep anchors it and its own V2 sequence says so -- the exact
    # mechanism V1 used (analysis.v2.sequence.build_sequences), reused unchanged.
    if sweep_anchor is not None:
        sweep_kind = "sweep_low" if direction == "LONG" else "sweep_high"
        sweep = LiquidityEvent(sweep_anchor["time"], "setup sweep", "setup level", sweep_anchor["level"], sweep_kind)
        seq = build_sequences(m15, [sweep])
        if seq and seq[0].invalidated:
            return f"15M setup invalidated: {seq[0].invalidation_reason}"

    # 1H structure invalidated: the established bias has been superseded by an opposing MSS.
    h1_struct = intraday.get("structure")
    want_bias = "bullish" if direction == "LONG" else "bearish"
    if h1_struct and h1_struct.get("last_mss") not in (None, want_bias):
        return f"1H directional structure invalidated: last_mss={h1_struct['last_mss']}"

    # HTF zone invalidated: price has closed decisively through the identified area, the wrong way.
    area = htf.get("nearest_area")
    if area is not None and atr15 is not None and atr15 > 0:
        wrong_side = (direction == "LONG" and area["side"] == "SUPPORT" and price < area["low"] - 0.15 * atr15) or \
                    (direction == "SHORT" and area["side"] == "RESISTANCE" and price > area["high"] + 0.15 * atr15)
        if wrong_side:
            return f"HTF key area invalidated: price closed through {area['low']:.2f}-{area['high']:.2f}"

    return None


def _entry_candidate(direction: str, price: float, zones: dict, sweep_anchor: Optional[dict],
                     m15: pd.DataFrame) -> dict:
    if sweep_anchor is not None:
        invalidation_price = sweep_anchor["extreme"]
        invalidation_basis = "beyond the setup's own liquidity sweep extreme"
    else:
        # No sweep anchors this setup: the nearest opposing-side confirmed M15 swing is the
        # structural invalidation point instead (reuses analyze_structure's own swings).
        swings = analyze_structure(m15).swings
        candidates = [p for p in swings if p.kind == ("low" if direction == "LONG" else "high")]
        invalidation_price = candidates[-1].price if candidates else None
        invalidation_basis = "beyond the nearest confirmed M15 swing"

    order = order_word(direction)
    entry = round(price, 2)
    stop = None if invalidation_price is None else rules.compute_stop_loss(order, invalidation_price)
    target = rules.select_target(order, zones, entry) if stop is not None else None
    rr = None
    if stop is not None:
        rr_raw, _risk, _reward = rules.compute_risk_reward(order, entry, stop, target)
        rr = rules.display_rr(rr_raw)
    return {
        "direction": direction, "entry": entry,
        "stop": None if stop is None else {"price": round(stop, 2), "basis": invalidation_basis},
        "target": None if target is None else {"price": round(target, 2), "basis": "nearest opposing qualifying level"},
        "rr": rr,
        "invalidation": {"price": None if invalidation_price is None else round(invalidation_price, 2),
                         "basis": invalidation_basis},
    }


def _confidence_items(htf, intraday, setup, confirmation, precision) -> tuple:
    passed: List[str] = []
    reasons: Dict[str, str] = {}

    def mark(name, cond, reason):
        if cond:
            passed.append(name)
            reasons[name] = reason

    mark("v2_htf_context", htf["htf_context"] in ("BULLISH", "BEARISH"), f"HTF context {htf['htf_context']}")
    mark("v2_htf_location", htf["htf_location"] in ("AT_ZONE", "APPROACHING_ZONE"), f"location {htf['htf_location']}")
    mark("v2_intraday_bias", intraday["intraday_bias"] in ("BULLISH", "BEARISH"), f"1H bias {intraday['intraday_bias']}")
    mark("v2_intraday_compatible", bool(intraday.get("compatible_with_htf")), "1H compatible with HTF")
    area = htf.get("nearest_area")
    mark("v2_location_quality_high", area is not None and area.get("strength") == "HIGH", "HIGH-strength key area")
    mark("v2_location_quality_moderate", area is not None and area.get("strength") == "MODERATE", "MODERATE-strength key area")
    cats15 = set(setup.get("evidence_categories", []))
    mark("v2_key_area_reaction", "KEY_AREA_REACTION" in cats15, "price reacting from a key area")
    mark("v2_liquidity_sweep_15m", "LIQUIDITY_SWEEP" in cats15, "15M liquidity sweep")
    mark("v2_structure_15m", "MSS_BOS" in cats15, "15M MSS/BOS")
    mark("v2_displacement_15m", "DISPLACEMENT" in cats15, "15M displacement")
    mark("v2_fvg_15m", "FVG" in cats15, "15M FVG")
    fvg = setup.get("fvg")
    mark("v2_fvg_15m_retest", fvg is not None and fvg.get("status") == "RETESTED", "15M FVG retested")
    ote = setup.get("ote")
    mark("v2_ote_full", ote is not None and ote.get("overlap") == "FULL", "FVG inside the OTE band")
    mark("v2_ote_partial", ote is not None and ote.get("overlap") == "PARTIAL", "FVG partly inside the OTE band")
    cats5 = set(confirmation.get("evidence_categories", []))
    mark("v2_liquidity_sweep_5m", "LIQUIDITY_SWEEP" in cats5, "5M liquidity sweep")
    mark("v2_structure_5m", "MSS_BOS" in cats5, "5M MSS/BOS")
    mark("v2_displacement_5m", "DISPLACEMENT" in cats5, "5M displacement")
    mark("v2_fvg_5m", "FVG" in cats5, "5M FVG")
    mark("v2_confirmation_5m", confirmation.get("confirmation_status") == "CONFIRMED", "5M confirmation reached")
    mark("v2_structure_1m", precision.get("precision_status") == "AVAILABLE", "1M structure trigger")
    mark("v2_precision_1m", precision.get("precision_status") == "AVAILABLE", "1M precision available")

    contradictions: List[str] = [e["note"] for e in setup.get("contradicting_evidence", [])]
    contradictions += [e["note"] for e in confirmation.get("contradicting_evidence", [])]
    return passed, reasons, contradictions


def evaluate(frames: Dict[str, pd.DataFrame], now: pd.Timestamp) -> dict:
    """`frames` maps M1, M5, M15, H1, H4, D1 to candles. Forming candles are dropped here. `now` is
    accepted for interface compatibility with the route and with V1; this layer does not use a
    wall-clock sweep-expiry window (there may be no sweep at all now that it is optional evidence)."""
    f = {tf: _closed(frames.get(tf)) for tf in ("M1", "M5", "M15", "H1", "H4", "D1")}
    as_of = None if f["M5"] is None or len(f["M5"]) == 0 else pd.Timestamp(f["M5"]["time"].iloc[-1]).isoformat()

    if any(f[tf] is None or len(f[tf]) < MIN_BARS for tf in REQUIRED):
        return {"direction": None, "state": "NO_CONTEXT", "as_of": as_of, "disclaimer": DISCLAIMER,
                "higher_timeframe": None, "intraday": None, "setup_15m": None, "confirmation_5m": None,
                "precision_1m": None, "entry_candidate": None, "confidence": None,
                "supporting_evidence": [], "contradicting_evidence": [], "invalidation": None,
                "next_condition": {"text": "enough M5/M15/H1/H4/D1 history", "timeframe": "all"}}

    price = float(f["M5"]["close"].iloc[-1])
    htf = evaluate_htf(f["D1"], f["H4"], f["H1"], f["M5"], price)
    intraday = evaluate_intraday(f["H1"], htf["htf_context"])
    setup = evaluate_setup(f["M15"], f["M5"], f["H1"], f["H4"], htf["htf_context"],
                           intraday["intraday_bias"], intraday["compatible_with_htf"], price)
    # `direction` from here on is the WORKING direction: used internally to drive confirmation,
    # invalidation, expiry and the entry candidate, exactly as before the gating fix. It is never
    # returned directly -- see `exposed_direction` below, which is what the hierarchy has actually
    # earned the right to claim.
    direction = setup["setup_direction"]

    confirmation = evaluate_confirmation(f["M5"], f["H1"], f["H4"], direction, price)

    precision = {"precision_status": "NOT_APPLICABLE", "trigger": None, "checklist": []}
    # 1M is never consulted ahead of 5M confirmation reaching at least DEVELOPING -- a strong 1M
    # pattern alone must never create or upgrade a candidate (the explicit anti-override rule).
    if confirmation["confirmation_status"] in ("DEVELOPING", "CONFIRMED") and direction in ("LONG", "SHORT"):
        not_before = pd.Timestamp(setup["fvg"]["formed_at"]) if setup.get("fvg") else pd.Timestamp(f["M15"]["time"].iloc[0])
        precision = evaluate_precision(f["M1"], direction, not_before)

    atr15_series = compute_atr(f["M15"])
    atr15 = float(atr15_series.iloc[-1]) if len(atr15_series) > 20 else None

    sweep_anchor = _sweep_anchor(setup, f["M15"], direction) if direction in ("LONG", "SHORT") else None
    invalidation_reason = _invalidation_check(direction, htf, intraday, setup, f["M15"], sweep_anchor, price, atr15)

    expired = False
    if sweep_anchor is not None and sweep_anchor["age_bars"] > config.ENTRY_MODEL_SWEEP_MAX_BARS:
        expired = True

    conflicted = setup["setup_status"] == "CONFLICTED" or confirmation["confirmation_status"] == "CONFLICTED"

    entry_candidate = None
    state = "NO_CONTEXT"
    if htf["htf_location"] != "UNKNOWN" or htf["htf_context"] != "NEUTRAL":
        state = "HTF_LOCATION_IDENTIFIED"
    if htf["htf_context"] in ("BULLISH", "BEARISH"):
        state = "HTF_CONTEXT_ALIGNED"
    if state == "HTF_CONTEXT_ALIGNED" and intraday["intraday_bias"] in ("BULLISH", "BEARISH") and intraday["compatible_with_htf"]:
        state = "INTRADAY_BIAS_ESTABLISHED"
    if state == "INTRADAY_BIAS_ESTABLISHED" and setup["setup_status"] == "SETUP_DEVELOPING":
        state = "SETUP_DEVELOPING"
    if state == "INTRADAY_BIAS_ESTABLISHED" and setup["setup_status"] == "SETUP_CONFIRMED":
        state = "SETUP_CONFIRMED"
    if state == "SETUP_CONFIRMED" and confirmation["confirmation_status"] == "DEVELOPING":
        state = "ENTRY_CONFIRMATION_DEVELOPING"
    if state == "SETUP_CONFIRMED" and confirmation["confirmation_status"] == "CONFIRMED":
        state = "ENTRY_CONFIRMED"
        zones = compute_zones(f["M5"], f["H1"], f["H4"])
        entry_candidate = _entry_candidate(direction, price, zones, sweep_anchor, f["M15"])
        if precision["precision_status"] == "AVAILABLE":
            state = "PRECISION_AVAILABLE"
        if entry_candidate.get("stop") is not None and entry_candidate.get("target") is not None:
            state = "ENTRY_READY"

    if conflicted:
        state = "CONFLICTED"
    if invalidation_reason is not None:
        state = "INVALIDATED"
    elif expired:
        state = "EXPIRED"
        entry_candidate = None

    passed, reasons, contradictions = _confidence_items(htf, intraday, setup, confirmation, precision)
    confidence_result = C.score(passed, reasons, contradictions)

    supporting = list(setup.get("supporting_evidence", [])) + list(confirmation.get("supporting_evidence", []))
    contradicting = list(setup.get("contradicting_evidence", [])) + list(confirmation.get("contradicting_evidence", []))

    # What's missing to advance, in plain terms -- states that sit "between" two ladder rungs
    # (ENTRY_CONFIRMATION_DEVELOPING, PRECISION_AVAILABLE) map to the same next milestone as the
    # rung they are developing beyond, so a snapshot mid-progress still names a concrete next step.
    NEXT_CONDITION_BY_STATE = {
        "NO_CONTEXT": ("enough M5/M15/H1/H4/D1 history", "all"),
        "HTF_LOCATION_IDENTIFIED": ("1D and 4H bias to agree", "1D/4H"),
        "HTF_CONTEXT_ALIGNED": ("1H bias compatible with the HTF context", "1H"),
        "INTRADAY_BIAS_ESTABLISHED": ("15M setup evidence", "15M"),
        "SETUP_DEVELOPING": ("a second independent 15M evidence category", "15M"),
        "SETUP_CONFIRMED": ("5M confirmation", "5M"),
        "ENTRY_CONFIRMATION_DEVELOPING": ("5M confirmation", "5M"),
        "ENTRY_CONFIRMED": ("a deterministic stop and target", "entry"),
        "PRECISION_AVAILABLE": ("a deterministic stop and target", "entry"),
    }
    next_condition = None
    if state in NEXT_CONDITION_BY_STATE:
        text, tf = NEXT_CONDITION_BY_STATE[state]
        next_condition = {"text": text, "timeframe": tf}

    # The EXPOSED direction -- the fix for the direction/state gating finding. `direction` (the
    # working value above) can be LONG/SHORT as soon as 15M resolves one, but the hierarchy has not
    # earned the right to claim an actionable direction until 5M confirmation has actually reached
    # CONFIRMED (never merely DEVELOPING): 1D/4H unresolved, 1H unresolved/incompatible, or 15M
    # unresolved all already keep the working `direction` at NEUTRAL (via evaluate_setup's own HTF
    # gate); this is the remaining gate for "5M not confirmed -> no entry direction/candidate". The
    # CONFLICTED sentinel is preserved exactly as before, taking priority over this gate -- a
    # genuine conflict is still reported even if 5M never got the chance to confirm anything. 1M
    # precision is never consulted here at all, so it can never create or override this value.
    if conflicted:
        exposed_direction = "CONFLICTED"
    elif confirmation["confirmation_status"] == "CONFIRMED" and direction in ("LONG", "SHORT"):
        exposed_direction = direction
    else:
        exposed_direction = None

    return {
        "direction": exposed_direction, "state": state, "as_of": as_of,
        "disclaimer": DISCLAIMER,
        "higher_timeframe": htf, "intraday": intraday, "setup_15m": setup,
        "confirmation_5m": confirmation, "precision_1m": precision,
        "entry_candidate": entry_candidate, "confidence": confidence_result,
        "supporting_evidence": supporting, "contradicting_evidence": contradicting,
        "invalidation": None if invalidation_reason is None else {"text": invalidation_reason},
        "next_condition": next_condition,
    }
