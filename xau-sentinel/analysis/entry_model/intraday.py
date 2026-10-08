"""1H layer: intraday bias. Answers "What is the intraday market direction/structure?" -- never
requires a sweep, FVG, displacement, or entry.

Reuses analysis.structure.analyze_structure unchanged, the same primitive used for every other
timeframe in this codebase.
"""
from typing import Optional

import pandas as pd

from analysis.entry_model.common import bias_from_state, ev, item
from analysis.structure import analyze_structure

BIAS_STATES = ("BULLISH", "BEARISH", "NEUTRAL", "TRANSITION")


def evaluate_intraday(h1: Optional[pd.DataFrame], htf_context: str) -> dict:
    if h1 is None or len(h1) < 15:
        return {"intraday_bias": "NEUTRAL", "compatible_with_htf": None, "structure": None,
                "checklist": [item("Structure identified", "WAITING", "1H", "not enough 1H history")]}

    res = analyze_structure(h1)
    bias = bias_from_state(res.state)
    # A structure shift actively under way -- last_mss disagreeing with the settled-trend reading
    # last_bos -- reads as TRANSITION rather than a confident bias. Reuses the existing fields;
    # no new detector.
    if res.last_mss is not None and res.last_bos is not None and res.last_mss != res.last_bos:
        intraday_bias = "TRANSITION"
    elif bias == "bullish":
        intraday_bias = "BULLISH"
    elif bias == "bearish":
        intraday_bias = "BEARISH"
    else:
        intraday_bias = "NEUTRAL"

    compatible = (htf_context in ("NEUTRAL", "TRANSITION") or intraday_bias in ("NEUTRAL", "TRANSITION")
                 or intraday_bias == htf_context)

    last_bar_time = h1["time"].iloc[-1]
    checklist = [
        item("Structure identified", "PASS", "1H", f"1H structure {res.state}: {res.reason}",
            ev("H1", last_bar_time, "STRUCTURE_STATE", None, "analysis.structure", res.state)),
        item("MSS/BOS detected", "PASS" if (res.last_bos or res.last_mss) else "WAITING", "1H",
            f"last_bos={res.last_bos}, last_mss={res.last_mss}"),
        item("Intraday bias established", "PASS" if intraday_bias in ("BULLISH", "BEARISH") else
            "PARTIAL" if intraday_bias == "TRANSITION" else "WAITING", "1H", f"bias={intraday_bias}"),
        item("Bias compatible with HTF context", "PASS" if compatible else "FAIL", "1H/4H/1D",
            f"1H {intraday_bias} vs HTF {htf_context}"),
    ]
    return {"intraday_bias": intraday_bias, "compatible_with_htf": compatible,
            "structure": {"state": res.state, "last_bos": res.last_bos, "last_mss": res.last_mss,
                          "reason": res.reason},
            "checklist": checklist}
