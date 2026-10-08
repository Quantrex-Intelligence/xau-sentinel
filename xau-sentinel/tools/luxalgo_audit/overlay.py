"""Chart overlay records for the LuxAlgo ICT reference (luxalgo_ref.py).

Input: closed bars only, oldest first, with columns time, open, high, low, close.
Output: the state the chart should show at the last closed bar, using the same visibility limits as
the source script (2 FVG boxes per side, 1 order block per side, 2 liquidity clusters per side).
Read-only. Nothing here changes the product's analysis or A+ path.
"""
import pandas as pd

from tools.luxalgo_audit import luxalgo_ref as LR

FVG_PER_SIDE = 2
OB_PER_SIDE = 1
LIQ_PER_SIDE = 2
STRUCTURE_LAST = 8


def _epoch(ts) -> int:
    return int(pd.Timestamp(ts).timestamp())


def build_overlay(df: pd.DataFrame) -> dict:
    if df is None or len(df) == 0:
        return {"fvg": [], "order_blocks": [], "liquidity": [], "structure": [], "last_bar_time": None}
    o, h, l, c = (df[k].astype(float).values for k in ("open", "high", "low", "close"))
    times = [pd.Timestamp(t) for t in df["time"]]
    ev = LR.run(o, h, l, c)
    st = ev["state"]

    last_t = _epoch(times[-1])
    fvg = []
    for side, boxes in (("bullish", st["fvg_up"]), ("bearish", st["fvg_dn"])):
        for b in [x for x in boxes if x["active"]][:FVG_PER_SIDE]:
            fvg.append({"side": side, "top": round(float(b["top"]), 2), "bottom": round(float(b["bot"]), 2),
                        "start_time": _epoch(times[max(0, b["formed"] - 2)]), "end_time": last_t})

    obs = []
    for side, blocks in (("bullish", st["ob_bull"]), ("bearish", st["ob_bear"])):
        for ob in blocks[:OB_PER_SIDE]:
            obs.append({"side": side, "top": round(float(ob["top"]), 2), "bottom": round(float(ob["btm"]), 2),
                        "start_time": _epoch(times[ob["loc"]]), "end_time": last_t, "breaker": bool(ob["breaker"])})

    liq = []
    for side, boxes in (("buyside", st["liq_high"]), ("sellside", st["liq_low"])):
        for b in [x for x in boxes if not x["broken"]][:LIQ_PER_SIDE]:
            liq.append({"side": side, "top": round(float(b["top"]), 2), "bottom": round(float(b["bot"]), 2),
                        "start_time": _epoch(times[b["anchor"]]), "end_time": last_t})

    structure = []
    for e in ev["mss"]:
        structure.append({"kind": "MSS", "direction": e["dir"], "level": round(float(e["level"]), 2),
                          "from_time": _epoch(times[e["from"]]), "time": _epoch(times[e["t"]])})
    for e in ev["bos"]:
        structure.append({"kind": "BOS", "direction": e["dir"], "level": round(float(e["level"]), 2),
                          "from_time": _epoch(times[e["from"]]), "time": _epoch(times[e["t"]])})
    structure.sort(key=lambda x: x["time"])

    return {
        "fvg": fvg,
        "order_blocks": obs,
        "liquidity": liq,
        "structure": structure[-STRUCTURE_LAST:],
        "last_bar_time": _epoch(times[-1]),
    }
