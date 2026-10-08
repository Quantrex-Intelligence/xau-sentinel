"""Offline comparison: LuxAlgo reference (luxalgo_ref.py) vs Analysis Engine V2 primitives, on the same raw
closed XAUUSD bars. Read-only. Writes audit_results.json to XAU_AUDIT_OUT (default: TEMP).
"""
import json
import os
import pickle
import sys
from collections import Counter

import numpy as np
import pandas as pd


HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT = os.environ.get("XAU_AUDIT_OUT", os.environ.get("TEMP", HERE))
RAW = os.path.join(os.environ.get("TEMP", HERE), "raw_big.pkl")
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
os.chdir(REPO)

import luxalgo_ref as LR  # noqa: E402
from analysis.liquidity import detect_equal_levels  # noqa: E402
from analysis.structure import compute_atr, displacement_at  # noqa: E402
from analysis.v2.events import structure_transitions  # noqa: E402
from analysis.v2.fvg import find_fvgs  # noqa: E402

raw = pickle.load(open(RAW, "rb"))


def closed(df):
    return df.iloc[:-1].reset_index(drop=True)  # the last row is the forming bar


M5, H1 = closed(raw["M5"]), closed(raw["H1"])
WIN = {
    "m5_disp_fvg_ob": M5.tail(20000).reset_index(drop=True),
    "m5_struct_liq": M5.tail(2000).reset_index(drop=True),
    "h1_disp_fvg_ob": H1.tail(6000).reset_index(drop=True),
    "h1_struct_liq": H1.tail(1500).reset_index(drop=True),
}
RESULTS = {}


def ohlc(df, i):
    r = df.iloc[i]
    return {"i": int(i), "time": str(r["time"]), "o": round(float(r.open), 2), "h": round(float(r.high), 2),
            "l": round(float(r.low), 2), "c": round(float(r.close), 2)}


def context(df, i, k=2):
    return [ohlc(df, j) for j in range(max(0, i - k), min(len(df), i + k + 1))]


def lux(df):
    return LR.run(df.open.values, df.high.values, df.low.values, df.close.values)


def tindex(df):
    return {pd.Timestamp(t): i for i, t in enumerate(df["time"])}


def summarise(name, lux_set, v2_set, df, extra=None):
    exact = lux_set & v2_set
    lo, vo = lux_set - v2_set, v2_set - lux_set
    rec = {"luxalgo": len(lux_set), "v2": len(v2_set), "exact": len(exact), "luxalgo_only": len(lo),
           "v2_only": len(vo)}
    rec["samples"] = {
        "exact": [{"key": str(k), "context": context(df, k[0])} for k in sorted(exact, key=str)[:3]],
        "luxalgo_only": [{"key": str(k), "context": context(df, k[0])} for k in sorted(lo, key=str)[:3]],
        "v2_only": [{"key": str(k), "context": context(df, k[0])} for k in sorted(vo, key=str)[:3]],
    }
    if extra:
        rec.update(extra)
    RESULTS[name] = rec
    print(f"{name}: lux={rec['luxalgo']} v2={rec['v2']} exact={rec['exact']} lux_only={rec['luxalgo_only']} "
          f"v2_only={rec['v2_only']}", flush=True)
    return rec


# ---------------------------------------------------------------- 1. displacement
for label in ("m5_disp_fvg_ob", "h1_disp_fvg_ob"):
    df = WIN[label]
    ev = lux(df)
    L = {(t, "bullish") for t in ev["displacement_up"]} | {(t, "bearish") for t in ev["displacement_dn"]}
    atr = compute_atr(df)
    V = set()
    for i in range(len(df)):
        side = displacement_at(df, i, atr=atr)
        if side:
            V.add((i, side))
    body = (df.close - df.open).abs().values
    mean5 = pd.Series(body).rolling(5).mean().values
    rng_up = (df.high - df.close.where(df.close > df.open, df.open)).values
    # categorise V2-only and LuxAlgo-only candles by which LuxAlgo test they fail
    def lux_tests(i):
        up = df.close.values[i] > df.open.values[i]
        wick_ok = (df.high.values[i] - max(df.open.values[i], df.close.values[i]) < body[i] * LR.PERC_BODY and
                   min(df.open.values[i], df.close.values[i]) - df.low.values[i] < body[i] * LR.PERC_BODY)
        return {"body_gt_mean5": bool(body[i] > mean5[i]) if not np.isnan(mean5[i]) else False,
                "wick_rule": bool(wick_ok), "direction": bool(up)}
    v2_only = {(i, s) for (i, s) in (V - L)}
    cats = Counter()
    for (i, s) in v2_only:
        tests = lux_tests(i)
        if not tests["wick_rule"]:
            cats["V2-only: fails LuxAlgo wick rule (wick >= 0.36*body)"] += 1
        elif not tests["body_gt_mean5"]:
            cats["V2-only: fails LuxAlgo body > SMA5"] += 1
        else:
            cats["V2-only: passes LuxAlgo body and wick tests (direction/other)"] += 1
    summarise(f"displacement [{label}]", L, V, df, {"v2_only_categories": dict(cats)})

# ---------------------------------------------------------------- 2. FVG creation
for label in ("m5_disp_fvg_ob", "h1_disp_fvg_ob"):
    df = WIN[label]
    ev = lux(df)
    L = {(e["t"], "bullish" if e["dir"] == "bullish" else "bearish") for e in ev["fvg"]}
    disp_up, disp_dn = set(ev["displacement_up"]), set(ev["displacement_dn"])
    gaps = find_fvgs(df, lookback=len(df))
    idx = tindex(df)
    V = {(idx[g.formed_at], g.direction) for g in gaps if g.formed_at in idx}
    cats = Counter()
    for (t, d) in V - L:
        mid = (t - 1) in (disp_up if d == "bullish" else disp_dn)
        if not mid:
            cats["V2-only: middle candle is not a LuxAlgo displacement"] += 1
        else:
            cats["V2-only: middle IS a displacement but LuxAlgo merged it into a consecutive run"] += 1
    summarise(f"FVG creation [{label}]", L, V, df, {"v2_only_categories": dict(cats),
                                                   "luxalgo_only_note": "LuxAlgo gap requires a displacement middle candle, so it should be a subset of V2"})

# ---------------------------------------------------------------- 3. FVG mitigation (matched gaps)
df = WIN["m5_disp_fvg_ob"]
ev = lux(df)
idx = tindex(df)
gaps = find_fvgs(df, lookback=len(df))
lux_break = {}
lux_partial = {}
for e in ev["fvg_break"]:
    lux_break.setdefault((e["formed"], e["dir"]), e["t"])
for e in ev["fvg_partial"]:
    lux_partial.setdefault((e["formed"], e["dir"]), e["t"])
dropped = {(e["formed"], e["dir"]) for e in ev["fvg_dropped"]}
mit = Counter()
examples = {}
for g in gaps:
    if g.formed_at not in idx:
        continue
    t = idx[g.formed_at]
    key = (t, "bullish" if g.direction == "bullish" else "bearish")
    if key not in {(e["t"], "bullish" if e["dir"] == "bullish" else "bearish") for e in ev["fvg"]}:
        continue
    v2_fill = idx.get(g.filled_at) if g.filled_at is not None else None
    lb = lux_break.get(key)
    if key in dropped and lb is None:
        cat = "LuxAlgo: box dropped (only 2 visible per side) before any break"
    elif lb is None and v2_fill is None:
        cat = "both: still open"
    elif lb is None:
        cat = "V2 filled (close), LuxAlgo never broke (wick) while tracked"
    elif v2_fill is None:
        cat = "LuxAlgo wick broke, V2 not filled (V2 only closes count)"
    elif lb == v2_fill:
        cat = "same bar"
    elif lb < v2_fill:
        cat = "LuxAlgo wick break earlier than V2 close fill"
    else:
        cat = "LuxAlgo break later than V2 fill"
    mit[cat] += 1
    examples.setdefault(cat, {"gap_formed": ohlc(df, t), "lux_break_bar": lb, "v2_fill_bar": v2_fill,
                              "context": context(df, lb if lb is not None else (v2_fill or t))})
RESULTS["FVG mitigation (matched gaps, M5 window)"] = {"categories": dict(mit), "examples": examples}
print("FVG mitigation:", dict(mit), flush=True)

# ---------------------------------------------------------------- 4. MSS and BOS
for label in ("m5_struct_liq", "h1_struct_liq"):
    df = WIN[label]
    tf = "M5" if label.startswith("m5") else "H1"
    ev = lux(df)
    idx = tindex(df)
    start = 200
    L_mss = {(e["t"], "bullish" if e["dir"] == "bullish" else "bearish") for e in ev["mss"] if e["t"] >= start}
    L_bos = {(e["t"], "bullish" if e["dir"] == "bullish" else "bearish") for e in ev["bos"] if e["t"] >= start}
    trans = structure_transitions(df, tf, window=len(df) - start)
    V_mss, V_bos = set(), set()
    for e in trans:
        i = idx.get(pd.Timestamp(e.time))
        if i is None:
            continue
        if e.kind == "MSS":
            V_mss.add((i, e.direction))
        elif e.kind == "BOS":
            V_bos.add((i, e.direction))
    near = lambda A, B, tol=2: sum(1 for a in A if any(abs(a[0] - b[0]) <= tol and a[1] == b[1] for b in B))
    summarise(f"MSS [{label}]", L_mss, V_mss, df, {"within_2_bars": near(L_mss, V_mss)})
    summarise(f"BOS [{label}]", L_bos, V_bos, df, {"within_2_bars": near(L_bos, V_bos)})

# ---------------------------------------------------------------- 5. liquidity clustering
for label in ("m5_struct_liq", "h1_struct_liq"):
    df = WIN[label]
    ev = lux(df)
    idx = tindex(df)
    start = 200
    L = set()
    for e in ev["liq_high"] + ev["liq_low"]:
        if e["pivot_bar"] >= start:
            side = "high" if e in ev["liq_high"] else "low"
            L.add((e["pivot_bar"], side, round(e["anchor_px"], 2), e["count"]))
    eq = detect_equal_levels(df)
    V = set()
    for e in eq:
        i = idx.get(pd.Timestamp(e.time))
        if i is None or i < start:
            continue
        V.add((i, "high" if e.kind == "equal_high" else "low", round(float(e.level_price), 2), 2))
    matched = 0
    for (p, side, px, _) in L:
        if any(abs(p - q) <= 3 and side == s2 and abs(px - pr) <= 0.5 for (q, s2, pr, _) in V):
            matched += 1
    counts3 = Counter(c for (*_, c) in L)
    RESULTS[f"liquidity clusters [{label}]"] = {
        "luxalgo_clusters_created": len(L), "luxalgo_count_distribution": dict(counts3),
        "v2_equal_level_events": len(V), "matched_within_3_bars_and_0.5_price": matched,
        "luxalgo_only": len(L) - matched, "v2_only": len(V) - matched,
        "examples_luxalgo": [{"pivot_bar": p, "side": side, "anchor_px": px, "count": c,
                              "context": context(df, p)} for (p, side, px, c) in sorted(L)[:2]],
    }
    print(f"liquidity [{label}]: lux={len(L)} v2={len(V)} matched={matched}", flush=True)

# ---------------------------------------------------------------- 6. order blocks vs V2 origin zones (H1)
df = WIN["h1_disp_fvg_ob"]
ev = lux(df)
L_bull = {e["loc"] for e in ev["ob_bull"]}
L_bear = {e["loc"] for e in ev["ob_bear"]}
atr = compute_atr(df)
V_bull, V_bear = set(), set()
for i in range(len(df)):
    side = displacement_at(df, i, atr=atr)
    if side is None:
        continue
    for j in range(i - 1, max(-1, i - 6), -1):
        opposite = (df.close.iloc[j] < df.open.iloc[j]) if side == "bullish" else (df.close.iloc[j] > df.open.iloc[j])
        if opposite:
            (V_bull if side == "bullish" else V_bear).add(j)
            break
RESULTS["order blocks vs V2 origin zones (H1 window)"] = {
    "luxalgo_bullish_ob": len(L_bull), "v2_demand_origin": len(V_bull), "bullish_exact_candle": len(L_bull & V_bull),
    "luxalgo_bearish_ob": len(L_bear), "v2_supply_origin": len(V_bear), "bearish_exact_candle": len(L_bear & V_bear),
    "luxalgo_breakers": len(ev["ob_breaker"]),
    "examples_luxalgo_bull": [{"loc": e["loc"], "top": round(e["top"], 2), "btm": round(e["btm"], 2),
                               "context": context(df, e["loc"])} for e in ev["ob_bull"][:2]],
}
print("OB:", {k: v for k, v in RESULTS["order blocks vs V2 origin zones (H1 window)"].items() if not k.startswith("examples")}, flush=True)

# ---------------------------------------------------------------- 7. pivot / repaint behaviour
ev5 = lux(WIN["m5_struct_liq"])
ext = len(ev5["zigzag_extension"])
piv = sum(1 for _ in ev5["zigzag_extension"]) + len(ev5["liq_high"]) + len(ev5["liq_low"])
RESULTS["pivot behaviour (M5 struct window)"] = {
    "pivot_confirmation_bars": 1, "luxalgo_pivot_left_bars": LR.MS_LEN,
    "v2_fractal_confirmation_bars": 3,
    "zigzag_extensions_observed": ext,
    "note": "LuxAlgo confirms a pivot 1 bar after it forms and can later extend the newest zigzag point. V2 confirms swings 3 bars after and never revises them.",
}

out = os.path.join(OUT, "audit_results.json")
json.dump(RESULTS, open(out, "w"), indent=1, default=str)
print("saved", out)
