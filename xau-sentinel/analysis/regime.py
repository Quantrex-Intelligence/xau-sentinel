"""Simple market regime classification.

Price structure (H1) is the primary input; ATR only supports the
volatility-flavored labels. Kept deliberately simple — no scoring model.
"""
from dataclasses import dataclass

import pandas as pd

import config
from analysis.structure import analyze_structure, compute_atr


@dataclass
class RegimeResult:
    regime: str
    reason: str


def classify_regime(h1_df: pd.DataFrame, m15_df: pd.DataFrame) -> RegimeResult:
    h1 = analyze_structure(h1_df)
    m15 = analyze_structure(m15_df)

    atr = compute_atr(m15_df) if m15_df is not None else pd.Series(dtype=float)
    recent_atr = float(atr.iloc[-1]) if len(atr) else 0.0
    if len(atr) >= config.ATR_PERIOD * 2:
        baseline_atr = float(atr.iloc[-(config.ATR_PERIOD * 2):-config.ATR_PERIOD].mean())
    else:
        baseline_atr = recent_atr

    high_vol = baseline_atr > 0 and recent_atr > baseline_atr * config.HIGH_VOL_ATR_MULT
    low_vol = baseline_atr > 0 and recent_atr < baseline_atr * config.LOW_VOL_ATR_MULT

    if h1.state == "PULLBACK":
        return RegimeResult(
            "PULLBACK",
            f"H1 structure: {h1.reason} M15 currently {m15.state.lower()}, price pulling back toward support/resistance.",
        )

    if h1.state == "BULLISH" and h1.last_bos == "bullish":
        return RegimeResult("BREAKOUT", f"H1 bullish break of structure confirmed. {h1.reason}")
    if h1.state == "BEARISH" and h1.last_bos == "bearish":
        return RegimeResult("BREAKOUT", f"H1 bearish break of structure confirmed. {h1.reason}")

    if h1.state == "BULLISH":
        base = RegimeResult("TRENDING UP", h1.reason)
    elif h1.state == "BEARISH":
        base = RegimeResult("TRENDING DOWN", h1.reason)
    else:
        base = RegimeResult("RANGING", h1.reason)

    if high_vol:
        return RegimeResult("HIGH VOLATILITY", f"{base.regime.title()} structure with expanding ATR. {base.reason}")
    if low_vol:
        return RegimeResult("LOW VOLATILITY", f"{base.regime.title()} structure with contracting ATR. {base.reason}")

    return base
