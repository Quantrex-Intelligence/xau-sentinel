"""Intraday ICT Entry Model V1. Deterministic, explainable, manual decision support only.

It answers: "Given the current multi-timeframe context, how developed and well-supported is this potential
entry?" It never places, modifies or recommends an order, and it never changes the A+ rules.

Timeframe roles (existing data, closed candles only):
  1D  macro bias            analyze_structure on D1
  4H  higher-timeframe bias analyze_structure on H4
  1H  intraday context      structure, premium/discount, PDH/PDL and session levels in zones
  15M setup formation       detect_sweeps on M15, V2 sequence (sweep, MSS, displacement, retracement), FVG
  5M  entry confirmation    V2 sequence on M5 from the same sweep time, after the FVG retest
  1M  precision             a specific closed M1 MSS bar, at or after the 5M confirmation bar

Every reused primitive is an existing module. Nothing here re-derives a fact that already has a detector.

The sweep-validity window is this model's own (`config.ENTRY_MODEL_SWEEP_MAX_BARS`, on M15), never the
A+ one (`config.AI_STRATEGY_SWEEP_WINDOW_MINUTES`). Neither config reads the other.
"""
from typing import Dict, List, Optional

import pandas as pd

import config
from ai.strategy import rules
from analysis.entry_model.confidence import score
from analysis.entry_model.dataset import build_setup_record
from analysis.entry_model.ote import compute_ote
from analysis.liquidity import LiquidityEvent, detect_sweeps
from analysis.regime import classify_regime
from analysis.structure import analyze_structure, compute_atr
from analysis.v2.events import structure_transitions
from analysis.v2.fvg import FILLED, find_fvgs
from analysis.v2.key_areas import build_key_areas
from analysis.v2.sequence import CONFIRMED, build_sequences
from analysis.zones import compute_zones, current_session

DISCLAIMER = ("Manual decision support. Not a signal, not an order, and not a prediction. "
              "Confidence is a heuristic evidence score, not a probability.")

REQUIRED = ("M5", "M15", "H1", "H4", "D1")
MIN_BARS = 30
NEAR_LEVEL_ATR = 1.0
ROLE_TF = {"1d": "D1", "4h": "H4", "1h": "H1", "15m": "M15", "5m": "M5", "1m": "M1"}
M15_BAR_MINUTES = 15
M1_TRANSITION_WINDOW = 120  # closed M1 bars replayed for a bar-tied MSS; needs len(M1) >= this + 10

SIDES = {
    "LONG": {
        "sweep": "sweep_low", "bias": "bullish", "seq_bias": "bullish", "order": "BUY",
        "fvg_side": "bullish", "own_area": ("SUPPORT", "MIXED"), "opp_area": "RESISTANCE",
        "word": "bullish", "sweep_name": "sell-side",
    },
    "SHORT": {
        "sweep": "sweep_high", "bias": "bearish", "seq_bias": "bearish", "order": "SELL",
        "fvg_side": "bearish", "own_area": ("RESISTANCE", "MIXED"), "opp_area": "SUPPORT",
        "word": "bearish", "sweep_name": "buy-side",
    },
}


def _closed(df: Optional[pd.DataFrame]) -> Optional[pd.DataFrame]:
    if df is None or len(df) == 0:
        return None
    if "is_closed" in df.columns:
        df = df[df["is_closed"].astype(bool)]
    return df.reset_index(drop=True)


def _bias(state: str) -> str:
    return {"BULLISH": "bullish", "BEARISH": "bearish"}.get(state, "neutral")


def _premium_discount(h1: pd.DataFrame, price: float) -> str:
    result = analyze_structure(h1)
    highs = [p for p in result.swings if p.kind == "high"]
    lows = [p for p in result.swings if p.kind == "low"]
    if not highs or not lows:
        return "UNKNOWN"
    mid = (highs[-1].price + lows[-1].price) / 2
    return "PREMIUM" if price > mid else "DISCOUNT"


def _item(name, status, timeframe, evidence, reason, time=None, dependency=None):
    return {"name": name, "status": status, "timeframe": timeframe,
            "time": None if time is None else pd.Timestamp(time).isoformat(),
            "evidence": evidence, "reason": reason, "dependency": dependency}


def _result(direction, state, as_of, timeframes, checklist, **extra) -> dict:
    out = {
        "direction": direction, "state": state, "as_of": as_of, "timeframes": timeframes,
        "checklist": checklist, "disclaimer": DISCLAIMER,
        "setup_confidence": None, "key_area": None, "liquidity": None, "sequence": None,
        "fvg": None, "ote": None, "contradictions": [], "entry": {"status": "WAITING", "price": None},
        "stop": None, "targets": [], "rr": None, "invalidation": None, "next_condition": None,
        "m1_confirmation": None, "level_confluence": None, "opposing_liquidity": None, "setup_record": None,
    }
    out.update(extra)
    return out


def _m1_confirmation(m1: Optional[pd.DataFrame], direction: str, not_before: Optional[pd.Timestamp]) -> Optional[dict]:
    """A specific closed M1 MSS bar in the setup direction, at or after `not_before` (the 5M confirmation
    bar). Never the current forming bar — `m1` is already closed-only. Returns None (WAITING) when there
    is no such bar, including when there is not enough M1 history to replay a transition at all."""
    if m1 is None or not_before is None:
        return None
    window = len(m1) - 11
    if window < M1_TRANSITION_WINDOW // 4:  # not enough history for any transition replay
        return None
    window = min(window, M1_TRANSITION_WINDOW)
    seq_bias = SIDES[direction]["seq_bias"]
    candidates = [e for e in structure_transitions(m1, "M1", window)
                  if e.kind == "MSS" and e.direction == seq_bias and pd.Timestamp(e.time) >= not_before]
    if not candidates:
        return None
    ev = min(candidates, key=lambda e: pd.Timestamp(e.time))
    match = m1.index[m1["time"] == ev.time]
    bar_index = int(match[0]) if len(match) else None
    return {"time_utc": pd.Timestamp(ev.time).isoformat(), "bar_index": bar_index, "direction": ev.direction,
            "event_type": ev.kind, "price": None if ev.price is None else round(float(ev.price), 2),
            "closed_bar": True, "detail": ev.detail}


def evaluate(frames: Dict[str, pd.DataFrame], now: pd.Timestamp) -> dict:
    """`frames` maps M1, M5, M15, H1, H4, D1 to candles. Forming candles are dropped here, so only closed
    bars can influence the result. The sweep-validity window is a bar count on M15
    (`config.ENTRY_MODEL_SWEEP_MAX_BARS`), not a wall-clock comparison, so it is reproducible from
    historical data. `now` is no longer used for that; it is recorded only as the dataset record's
    generation timestamp."""
    f = {tf: _closed(frames.get(tf)) for tf in ("M1", "M5", "M15", "H1", "H4", "D1")}
    as_of = None if f["M5"] is None or len(f["M5"]) == 0 else pd.Timestamp(f["M5"]["time"].iloc[-1]).isoformat()
    if any(f[tf] is None or len(f[tf]) < MIN_BARS for tf in REQUIRED):
        return _result(None, "INSUFFICIENT_DATA", as_of, {}, [])

    price = float(f["M5"]["close"].iloc[-1])
    d1 = analyze_structure(f["D1"])
    h4 = analyze_structure(f["H4"])
    h1 = analyze_structure(f["H1"])
    bias_1d, bias_4h, bias_1h = _bias(d1.state), _bias(h4.state), _bias(h1.state)
    pd_zone = _premium_discount(f["H1"], price)
    timeframes = {
        "1d": {"role": "macro bias", "structure": d1.state, "bias": bias_1d},
        "4h": {"role": "higher-timeframe bias", "structure": h4.state, "bias": bias_4h},
        "1h": {"role": "intraday context", "structure": h1.state, "bias": bias_1h, "premium_discount": pd_zone},
    }

    direction = "LONG" if bias_1d == "bullish" and bias_4h == "bullish" else \
        "SHORT" if bias_1d == "bearish" and bias_4h == "bearish" else None
    # A defined bias is a fact (PASS). A neutral one is not yet a bias, so the item waits. Neither is
    # direction-specific here: the direction is decided below, from both timeframes agreeing.
    checklist = [
        _item("1D bias", "PASS" if bias_1d != "neutral" else "WAITING", "1D", d1.state,
              f"1D structure {d1.state}, reads {bias_1d}"),
        _item("4H bias", "PASS" if bias_4h != "neutral" else "WAITING", "4H", h4.state,
              f"4H structure {h4.state}, reads {bias_4h}"),
    ]
    if direction is None:
        checklist.append(_item("Direction alignment", "WAITING", "1D/4H",
                               f"1D {bias_1d}, 4H {bias_4h}", "1D and 4H must agree before a setup is considered"))
        return _result(None, "NO_SETUP", as_of, timeframes, checklist,
                       next_condition={"text": "1D and 4H structure agree", "timeframe": "1D/4H"})

    spec = SIDES[direction]
    # Market conditions, computed once a direction exists and shared by every return path from here on
    # (EXPIRED, INVALIDATED and the final result), since they describe the setup's context, not its outcome.
    regime = classify_regime(f["H1"], f["M15"]).__dict__
    session = current_session(pd.Timestamp(f["M5"]["time"].iloc[-1]))

    def _record(res: dict) -> dict:
        res["setup_record"] = build_setup_record(res, now=now, regime=regime, session=session,
                                                  opposing_liquidity=res.get("opposing_liquidity"))
        return res

    checklist.append(_item("1H context", "PASS" if bias_1h == spec["bias"] else
                           "FAIL" if bias_1h != "neutral" else "PARTIAL", "1H",
                           h1.state, f"1H structure {h1.state}"))
    checklist.append(_item("Premium/discount (1H)",
                           "PASS" if (direction == "LONG" and pd_zone == "DISCOUNT") or
                           (direction == "SHORT" and pd_zone == "PREMIUM") else
                           "PARTIAL" if pd_zone == "UNKNOWN" else "FAIL", "1H", pd_zone,
                           f"price is in the 1H {pd_zone.lower()} half" if pd_zone != "UNKNOWN" else
                           "not enough confirmed 1H swings"))

    zones = compute_zones(f["M5"], f["H1"], f["H4"])
    sweeps = [s for s in detect_sweeps(f["M15"], zones) if s.kind == spec["sweep"]]
    if not sweeps:
        checklist.append(_item("Liquidity sweep", "WAITING", "15M", None,
                               f"no {spec['sweep_name']} sweep of a meaningful level yet"))
        return _result(direction, "HTF_ALIGNED", as_of, timeframes, checklist,
                       next_condition={"text": f"{spec['sweep_name']} liquidity sweep", "timeframe": "15M"})

    sweep: LiquidityEvent = max(sweeps, key=lambda s: pd.Timestamp(s.time))
    sweep_time = pd.Timestamp(sweep.time)
    m15 = f["M15"]
    sweep_idx = int(m15.index[m15["time"] == sweep_time][0])
    sweep_age_bars = (len(m15) - 1) - sweep_idx
    sweep_age_minutes = sweep_age_bars * M15_BAR_MINUTES
    sweep_bar = m15.iloc[sweep_idx]
    sweep_extreme = float(sweep_bar["low"] if direction == "LONG" else sweep_bar["high"])
    checklist.append(_item("Liquidity sweep", "PASS", "15M", sweep.level_name,
                           f"{sweep.label} at {sweep.level_price:.2f}", time=sweep_time))

    # This model's own sweep-validity window, on M15 bars — independent of the A+ window
    # (config.AI_STRATEGY_SWEEP_WINDOW_MINUTES), which this module never reads. A starting value for
    # research, not a claim that it is optimal; see docs/entry-model-v1-plan.md.
    if sweep_age_bars > config.ENTRY_MODEL_SWEEP_MAX_BARS:
        return _record(_result(direction, "EXPIRED", as_of, timeframes, checklist,
                       invalidation={"text": f"sweep is {sweep_age_bars} M15 bars old "
                                             f"(~{sweep_age_minutes}min), beyond the "
                                             f"{config.ENTRY_MODEL_SWEEP_MAX_BARS}-bar window",
                                    "level": sweep_extreme},
                       liquidity={"sweep": {"label": sweep.label, "level_name": sweep.level_name,
                                            "level_price": round(float(sweep.level_price), 2),
                                            "time": sweep_time.isoformat(), "extreme": round(sweep_extreme, 2),
                                            "age_bars": sweep_age_bars, "age_minutes": sweep_age_minutes}}))

    seq = build_sequences(m15, [sweep])[0]
    steps = {st.name: st for st in seq.steps}

    def _sweep_sequence_dict() -> dict:
        # Explicit, in the output rather than only implied by timestamps: whether the sweep candle is
        # itself the MSS or displacement bar (a valid, and in the raw data the common, ordering).
        mss_t = steps["STRUCTURE_SHIFT"].bar_time
        disp_t = steps["DISPLACEMENT"].bar_time
        return {"ordering": seq.ordering, "chronology_ok": seq.chronology_ok, "stage": seq.stage,
                "sweep_is_mss_bar": mss_t is not None and pd.Timestamp(mss_t) == sweep_time,
                "sweep_is_displacement_bar": disp_t is not None and pd.Timestamp(disp_t) == sweep_time,
                "steps": [{"name": st.name, "status": st.status,
                           "time": None if st.bar_time is None else pd.Timestamp(st.bar_time).isoformat(),
                           "detail": st.detail} for st in seq.steps]}

    if seq.invalidated:
        return _record(_result(direction, "INVALIDATED", as_of, timeframes, checklist,
                       invalidation={"text": seq.invalidation_reason, "level": sweep_extreme},
                       liquidity={"sweep": {"label": sweep.label, "level_name": sweep.level_name,
                                            "level_price": round(float(sweep.level_price), 2),
                                            "time": sweep_time.isoformat(), "extreme": round(sweep_extreme, 2),
                                            "age_bars": sweep_age_bars, "age_minutes": sweep_age_minutes}},
                       sequence=_sweep_sequence_dict()))

    mss_ok = steps["STRUCTURE_SHIFT"].status == CONFIRMED
    disp_ok = steps["DISPLACEMENT"].status == CONFIRMED
    checklist.append(_item("MSS", "PASS" if mss_ok else "WAITING", "15M",
                           f"level {steps['STRUCTURE_SHIFT'].level}" if mss_ok else None,
                           steps["STRUCTURE_SHIFT"].detail, time=steps["STRUCTURE_SHIFT"].bar_time,
                           dependency="Liquidity sweep"))
    checklist.append(_item("Displacement", "PASS" if disp_ok else "WAITING", "15M", None,
                           steps["DISPLACEMENT"].detail, time=steps["DISPLACEMENT"].bar_time,
                           dependency="MSS"))

    # An FVG counts only once both the MSS and the displacement are confirmed (either order), and only if it
    # formed at or after the later of the two bars. A gap from before the structure shift is not the setup.
    if mss_ok and disp_ok and steps["STRUCTURE_SHIFT"].bar_time is not None and steps["DISPLACEMENT"].bar_time is not None:
        anchor_time = max(pd.Timestamp(steps["STRUCTURE_SHIFT"].bar_time), pd.Timestamp(steps["DISPLACEMENT"].bar_time))
    else:
        anchor_time = None
    gaps = [] if anchor_time is None else [
        g for g in find_fvgs(m15, lookback=len(m15))
        if g.direction == spec["fvg_side"] and pd.Timestamp(g.formed_at) >= anchor_time and g.status != FILLED]
    fvg = max(gaps, key=lambda g: pd.Timestamp(g.formed_at)) if gaps else None
    fvg_info = None
    retrace_ok = False
    if fvg is not None:
        in_fvg = fvg.low <= price <= fvg.high
        retrace_ok = in_fvg or fvg.status == "RETESTED"
        fvg_info = {"direction": fvg.direction, "low": round(fvg.low, 2), "high": round(fvg.high, 2),
                    "status": fvg.status, "formed_at": pd.Timestamp(fvg.formed_at).isoformat(),
                    "retested_at": None if fvg.retested_at is None else pd.Timestamp(fvg.retested_at).isoformat()}
    checklist.append(_item("FVG", "PASS" if fvg else "WAITING", "15M",
                           None if fvg is None else f"{fvg.low:.2f}-{fvg.high:.2f} ({fvg.status.lower()})",
                           "fair value gap formed by the displacement in the setup direction" if fvg else
                           "no open fair value gap from the displacement yet",
                           time=None if fvg is None else fvg.formed_at, dependency="Displacement"))
    checklist.append(_item("FVG retracement", "PASS" if retrace_ok else "WAITING" if fvg else "NOT_APPLICABLE",
                           "15M", f"price {price:.2f}" if fvg else None,
                           "price has returned into the FVG" if retrace_ok else
                           "waiting for price to return into the FVG" if fvg else "no FVG to retrace into",
                           dependency="FVG"))

    retest_time = None
    if fvg is not None:
        retest_time = pd.Timestamp(fvg.retested_at or fvg.formed_at)
    confirm5 = False
    mss5_time = None
    m5_seq = build_sequences(f["M5"], [sweep])
    if m5_seq and retest_time is not None:
        s5 = {st.name: st for st in m5_seq[0].steps}
        mss5 = s5["STRUCTURE_SHIFT"]
        confirm5 = mss5.status == CONFIRMED and mss5.bar_time is not None and pd.Timestamp(mss5.bar_time) >= retest_time
        if confirm5:
            mss5_time = pd.Timestamp(mss5.bar_time)
    checklist.append(_item("5M confirmation", "PASS" if confirm5 else "WAITING", "5M", None,
                           "5M structure shift after the FVG retest" if confirm5 else
                           "waiting for a 5M structure shift after the retest",
                           time=mss5_time, dependency="FVG retracement"))

    # A specific closed M1 MSS bar, at or after the 5M confirmation bar — never the current forming
    # candle, and never inferred from a general "M1 is bullish/bearish" state. See
    # analysis/v2/events.py::structure_transitions, which is already used for bar-tied M5/M15/H1/H4
    # transitions elsewhere in V2.
    m1_confirmation = _m1_confirmation(f["M1"], direction, mss5_time) if confirm5 else None
    confirm1 = m1_confirmation is not None
    checklist.append(_item(
        "1M confirmation", "PASS" if confirm1 else "WAITING", "1M",
        None if m1_confirmation is None else f"M1 MSS at {m1_confirmation['time_utc']}",
        "specific closed M1 MSS bar at or after the 5M confirmation bar" if confirm1 else
        "no M1 history to replay" if f["M1"] is None or len(f["M1"]) - 11 < M1_TRANSITION_WINDOW // 4 else
        "waiting for a closed M1 MSS bar in the setup direction",
        time=None if m1_confirmation is None else m1_confirmation["time_utc"], dependency="5M confirmation"))

    # Key areas and levels near the FVG.
    price_frame = f["M5"]
    areas = build_key_areas(price_frame, f["H1"], f["H4"], price)
    atr15 = float(compute_atr(m15).iloc[-1]) if len(m15) > 20 else None
    key_area = None
    overlap_area = None
    if fvg is not None:
        for a in areas:
            if a.side in spec["own_area"] and a.low <= fvg.high and a.high >= fvg.low:
                overlap_area = a
                break
    if overlap_area is not None:
        key_area = {"side": overlap_area.side, "low": round(overlap_area.low, 2), "high": round(overlap_area.high, 2),
                    "strength": overlap_area.strength_status, "overlaps_fvg": True}
    checklist.append(_item("Supply/demand, S/R", "PASS" if overlap_area else "WAITING", "1H/4H",
                           None if overlap_area is None else f"{overlap_area.side} {overlap_area.low:.2f}-{overlap_area.high:.2f}",
                           "a key area on the setup side overlaps the FVG" if overlap_area else
                           "no key area on the setup side overlaps the FVG", dependency="FVG"))

    level_near = None
    if fvg is not None and atr15:
        mid = fvg.mid
        for name, price_level in zones.items():
            if name in ("VWAP",):
                continue
            if abs(price_level - mid) <= NEAR_LEVEL_ATR * atr15:
                level_near = (name, price_level)
                break
    level_confluence = None if level_near is None else {"name": level_near[0], "price": round(float(level_near[1]), 2)}
    checklist.append(_item("Level confluence", "PASS" if level_near else "WAITING", "15M/1H", None if level_near is None
                           else f"{level_near[0]} {level_near[1]:.2f}",
                           "a session, previous-day or swing level sits within 1 ATR of the FVG" if level_near else
                           "no named level within 1 ATR of the FVG", dependency="FVG"))

    # OTE: retracement of the impulse from the sweep extreme to the displacement extreme.
    ote = None
    if disp_ok and steps["DISPLACEMENT"].bar_time is not None:
        disp_t = pd.Timestamp(steps["DISPLACEMENT"].bar_time)
        seg = m15[(m15["time"] >= sweep_time) & (m15["time"] <= disp_t)]
        if len(seg):
            if direction == "LONG":
                impulse_low, impulse_high = sweep_extreme, float(seg["high"].max())
            else:
                impulse_low, impulse_high = float(seg["low"].min()), sweep_extreme
            if impulse_high > impulse_low:
                zl, zh = (fvg.low, fvg.high) if fvg is not None else (None, None)
                ote = compute_ote(direction, impulse_low, impulse_high, zl, zh)
    ote_status = "NOT_APPLICABLE" if ote is None else ("PASS" if ote.overlap == "FULL" else
                                                        "PARTIAL" if ote.overlap == "PARTIAL" else "WAITING")
    checklist.append(_item("OTE", ote_status, "15M", None if ote is None else ote.overlap,
                           "retracement band (0.62-0.79) of the impulse; confluence only",
                           dependency="Displacement"))

    # Contradictions, listed explicitly and never hidden in the score.
    contradictions: List[str] = []
    if bias_1h not in (spec["bias"], "neutral"):
        contradictions.append(f"1H structure is {h1.state.lower()} while 1D and 4H are {spec['word']}")
    if pd_zone not in ("UNKNOWN",) and ((direction == "LONG" and pd_zone == "PREMIUM") or
                                        (direction == "SHORT" and pd_zone == "DISCOUNT")):
        contradictions.append(f"{direction.lower()} setup sits in the 1H {'premium' if pd_zone == 'PREMIUM' else 'discount'}")
    opposing_liquidity = None
    if atr15:
        for a in areas:
            if a.side == spec["opp_area"]:
                gap = (a.low - price) if direction == "LONG" else (price - a.high)
                if 0 <= gap <= atr15:
                    contradictions.append(f"{spec['opp_area'].lower()} {a.low:.2f}-{a.high:.2f} "
                                          f"{gap / atr15:.2f} ATR away on the target side")
                    opposing_liquidity = {"side": a.side, "low": round(a.low, 2), "high": round(a.high, 2),
                                          "distance_atr": round(gap / atr15, 2)}
                    break
    if fvg is not None and ((direction == "LONG" and price < fvg.low) or (direction == "SHORT" and price > fvg.high)):
        contradictions.append("price has already traded through the FVG")

    # State machine: the most advanced condition that is actually true.
    if confirm5 and retrace_ok and confirm1:
        state = "ENTRY_READY"
    elif confirm5 and retrace_ok:
        state = "ENTRY_CONFIRMATION"
    elif fvg is not None:
        state = "RETRACEMENT_WAITING"
    elif disp_ok:
        state = "DISPLACEMENT_CONFIRMED"
    elif mss_ok:
        state = "MSS_CONFIRMED"
    else:
        state = "LIQUIDITY_SWEPT"

    # Entry, stop, target and R:R are a plan for manual review, not an order.
    entry = None
    stop = None
    targets = []
    rr = None
    if state in ("ENTRY_CONFIRMATION", "ENTRY_READY"):
        entry = round(price, 2)
        stop = rules.compute_stop_loss(spec["order"], sweep_extreme)
        target = rules.select_target(spec["order"], zones, entry)
        rr_raw, risk, _reward = rules.compute_risk_reward(spec["order"], entry, stop, target)
        rr = rules.display_rr(rr_raw)
        if target is not None:
            targets.append({"price": round(target, 2), "basis": "nearest opposing qualifying level"})
    invalidation = {"text": f"close {'below' if direction == 'LONG' else 'above'} {sweep_extreme:.2f} "
                            f"({'sweep low' if direction == 'LONG' else 'sweep high'})",
                    "level": round(sweep_extreme, 2)}

    # Confidence: named evidence only.
    passed = ["htf_1d_bias", "htf_4h_bias", "liquidity_sweep"]
    reasons = {"htf_1d_bias": f"1D {bias_1d}", "htf_4h_bias": f"4H {bias_4h}",
               "liquidity_sweep": sweep.label}
    if bias_1h == spec["bias"]:
        passed.append("h1_context_aligned")
        reasons["h1_context_aligned"] = f"1H {bias_1h}"
    if mss_ok:
        passed.append("mss")
        reasons["mss"] = "MSS confirmed on 15M after the sweep"
    if disp_ok:
        passed.append("displacement")
        reasons["displacement"] = "displacement confirmed on 15M after the sweep"
    if fvg is not None:
        passed.append("fvg_available")
        reasons["fvg_available"] = f"FVG {fvg.low:.2f}-{fvg.high:.2f}"
    if retrace_ok:
        passed.append("fvg_retracement")
        reasons["fvg_retracement"] = "price returned into the FVG"
    if overlap_area is not None:
        passed.append("key_area_overlaps_fvg")
        reasons["key_area_overlaps_fvg"] = f"{overlap_area.side} overlaps FVG"
    if level_near is not None:
        passed.append("level_confluence")
        reasons["level_confluence"] = f"{level_near[0]} within 1 ATR of FVG"
    if ote is not None and ote.overlap == "FULL":
        passed.append("ote_overlap")
        reasons["ote_overlap"] = "FVG inside the OTE band"
    elif ote is not None and ote.overlap == "PARTIAL":
        passed.append("ote_partial")
        reasons["ote_partial"] = "FVG partly inside the OTE band"
    if confirm5:
        passed.append("confirm_5m")
        reasons["confirm_5m"] = "5M structure shift after the retest"
    if confirm1:
        passed.append("confirm_1m")
        reasons["confirm_1m"] = f"M1 MSS at {m1_confirmation['time_utc']}"
    confidence = score(passed, reasons, contradictions)

    # The next condition follows the entry chain in order, so it always names the step that is actually missing.
    chain = ("Liquidity sweep", "MSS", "Displacement", "FVG", "FVG retracement", "5M confirmation", "1M confirmation")
    by_name = {c["name"]: c for c in checklist}
    next_cond = next((by_name[n] for n in chain if n in by_name and by_name[n]["status"] not in ("PASS", "NOT_APPLICABLE")), None)
    timeframes["15m"] = {"role": "setup formation", "sweep": sweep.label, "sequence_stage": seq.stage}
    timeframes["5m"] = {"role": "entry confirmation", "confirmed": confirm5,
                        "confirmed_at": None if mss5_time is None else mss5_time.isoformat()}
    timeframes["1m"] = {"role": "precision entry", "confirmed": confirm1}

    return _record(_result(
        direction, state, as_of, timeframes, checklist,
        setup_confidence=confidence,
        key_area=key_area,
        liquidity={"sweep": {"label": sweep.label, "level_name": sweep.level_name,
                             "level_price": round(float(sweep.level_price), 2),
                             "time": sweep_time.isoformat(), "extreme": round(sweep_extreme, 2),
                             "age_bars": sweep_age_bars, "age_minutes": sweep_age_minutes}},
        sequence=_sweep_sequence_dict(),
        fvg=fvg_info,
        ote=None if ote is None else ote.to_dict(),
        contradictions=contradictions,
        m1_confirmation=m1_confirmation,
        level_confluence=level_confluence,
        opposing_liquidity=opposing_liquidity,
        entry={"status": "PLANNED" if entry is not None else "WAITING", "price": entry,
               "basis": "current 5M close, for manual review" if entry is not None else None},
        stop=None if stop is None else {"price": round(stop, 2), "basis": "beyond the sweep extreme with the configured buffer"},
        targets=targets,
        rr=rr,
        invalidation=invalidation,
        next_condition=None if next_cond is None else {"text": next_cond["reason"], "name": next_cond["name"],
                                                       "timeframe": next_cond["timeframe"]},
    ))
