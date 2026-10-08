"""Liquidity comparison done correctly: V2's equal-level detector is a snapshot over the latest 6 swings,
so it is evaluated AS OF every bar (prefix), and its events are collected over history. Read-only."""
import json
import os
import pickle
import sys

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

raw = pickle.load(open(RAW, "rb"))


def closed(df):
    return df.iloc[:-1].reset_index(drop=True)


def v2_asof_events(df, start):
    """Every equal-level event V2 reports when evaluated at each bar, keyed by the bar it is reported on."""
    seen = {}
    for k in range(start, len(df)):
        for e in detect_equal_levels(df.iloc[:k + 1].reset_index(drop=True)):
            key = (pd.Timestamp(e.time), "high" if e.kind == "equal_high" else "low")
            seen.setdefault(key, (k, float(e.level_price)))
    return seen


out = {}
for label, base, n in (("M5", "M5", 2000), ("H1", "H1", 1500)):
    df = closed(raw[base]).tail(n).reset_index(drop=True)
    idx = {pd.Timestamp(t): i for i, t in enumerate(df["time"])}
    ev = LR.run(df.open.values, df.high.values, df.low.values, df.close.values)
    lux = []
    for e in ev["liq_high"] + ev["liq_low"]:
        if e["pivot_bar"] < 200:
            continue
        side = "high" if e in ev["liq_high"] else "low"
        lux.append((e["pivot_bar"], side, e["anchor_px"], e["count"]))
    v2 = v2_asof_events(df, 200)
    v2_list = [(idx[t], side, px) for (t, side), (k, px) in v2.items() if t in idx]
    matched = [
        (p, side) for (p, side, apx, c) in lux
        if any(abs(p - q) <= 3 and side == s2 and abs(apx - px) <= 0.5 for (q, s2, px) in v2_list)
    ]
    out[label] = {
        "bars": len(df), "luxalgo_clusters": len(lux),
        "luxalgo_count_distribution": {str(c): sum(1 for *_, cc in lux if cc == c) for c in sorted({cc for *_, cc in lux})},
        "v2_equal_level_events_over_history": len(v2_list), "matched": len(matched),
        "luxalgo_only": len(lux) - len(matched), "v2_only": len(v2_list) - len(matched),
        "v2_event_gap_bars_median": None,
    }
    print(label, out[label], flush=True)
json.dump(out, open(os.path.join(OUT, "liquidity_asof.json"), "w"), indent=1)
print("saved")
