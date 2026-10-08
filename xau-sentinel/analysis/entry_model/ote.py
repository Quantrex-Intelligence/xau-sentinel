"""OTE as a retracement observation for the Entry Model. Confluence only, never mandatory.

The band is the retracement of the impulse from the sweep extreme to the displacement extreme:
  LONG  (impulse up):   high - 0.79*(high-low) .. high - 0.62*(high-low)
  SHORT (impulse down): low  + 0.62*(high-low) .. low  + 0.79*(high-low)
The 0.62 and 0.79 fractions are the common ICT convention. They are not validated as an edge.
"""
from dataclasses import dataclass
from typing import Optional

OTE_NEAR = 0.62
OTE_FAR = 0.79


@dataclass(frozen=True)
class Ote:
    direction: str  # LONG | SHORT
    band_low: float
    band_high: float
    impulse_low: float
    impulse_high: float
    overlap: str  # FULL | PARTIAL | NONE | NOT_APPLICABLE

    def to_dict(self) -> dict:
        return {
            "direction": self.direction, "band": [round(self.band_low, 2), round(self.band_high, 2)],
            "impulse": [round(self.impulse_low, 2), round(self.impulse_high, 2)], "overlap": self.overlap,
            "reference": "sweep extreme to displacement extreme", "timeframe": "M15",
            "convention": "0.62-0.79 ICT retracement, not validated",
        }


def compute_ote(direction: str, impulse_low: float, impulse_high: float,
                zone_low: Optional[float] = None, zone_high: Optional[float] = None) -> Ote:
    """`impulse_low` is the sweep extreme for LONG (the low) and `impulse_high` for SHORT (the high).
    The impulse range is always impulse_low .. impulse_high. `zone` is the FVG or key area to test
    the band against, if any."""
    if impulse_high <= impulse_low:
        raise ValueError("impulse_high must be above impulse_low")
    span = impulse_high - impulse_low
    if direction == "LONG":
        band_low = impulse_high - OTE_FAR * span
        band_high = impulse_high - OTE_NEAR * span
    elif direction == "SHORT":
        band_low = impulse_low + OTE_NEAR * span
        band_high = impulse_low + OTE_FAR * span
    else:
        raise ValueError(f"unknown direction {direction!r}")
    overlap = "NOT_APPLICABLE"
    if zone_low is not None and zone_high is not None:
        lo, hi = min(zone_low, zone_high), max(zone_low, zone_high)
        if lo >= band_low and hi <= band_high:
            overlap = "FULL"
        elif hi < band_low or lo > band_high:
            overlap = "NONE"
        else:
            overlap = "PARTIAL"
    return Ote(direction, band_low, band_high, impulse_low, impulse_high, overlap)
