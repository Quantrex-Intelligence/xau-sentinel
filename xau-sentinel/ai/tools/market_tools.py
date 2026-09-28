"""Read-only tool wrappers over api.snapshot.build_snapshot() — the exact
same aggregation point every REST market/setup route already uses (see
api/routes/market.py, api/routes/setup.py). No new market-analysis logic
lives here; each tool only slices out the piece it's named for."""
from datetime import datetime, timezone

from api.snapshot import build_snapshot
from ai.tools.registry import ToolSpec, register
from ai.tools.schemas import ToolResult

_EMPTY_SCHEMA = {"type": "object", "properties": {}}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_market_state(_args: dict) -> ToolResult:
    snap = build_snapshot()
    if snap.data_error or snap.price is None:
        return ToolResult(data_available=False, reason=snap.data_error or "Market data unavailable.",
                           source="mt5.market_data")
    return ToolResult(
        data_available=True, timestamp=_now(), source="mt5.market_data",
        data={
            "price": snap.price.price, "bid": snap.price.bid, "ask": snap.price.ask,
            "spread": snap.price.spread, "stale": snap.price.stale,
            "session": snap.session, "mode": snap.connection.mode,
            "regime": snap.regime.regime if snap.regime else None,
        },
    )


def get_market_structure(_args: dict) -> ToolResult:
    snap = build_snapshot()
    if snap.data_error or not snap.structure:
        return ToolResult(data_available=False, reason=snap.data_error or "Structure data unavailable.",
                           source="analysis.structure")
    return ToolResult(
        data_available=True, timestamp=_now(), source="analysis.structure",
        data={"structure": {
            tf: {"state": s.state, "last_bos": s.last_bos, "last_mss": s.last_mss, "reason": s.reason}
            for tf, s in snap.structure.items()
        }},
    )


def get_liquidity(_args: dict) -> ToolResult:
    snap = build_snapshot()
    if snap.data_error:
        return ToolResult(data_available=False, reason=snap.data_error, source="analysis.liquidity")
    return ToolResult(
        data_available=True, timestamp=_now(), source="analysis.liquidity",
        data={
            "sweeps": [
                {"label": e.label, "level_name": e.level_name, "level_price": e.level_price, "kind": e.kind}
                for e in snap.liquidity.sweeps
            ],
            "equal_levels": [
                {"label": e.label, "level_name": e.level_name, "level_price": e.level_price, "kind": e.kind}
                for e in snap.liquidity.equal_levels
            ],
            "displacement": snap.displacement,
        },
    )


def get_key_zones(_args: dict) -> ToolResult:
    snap = build_snapshot()
    if snap.data_error or not snap.zones:
        return ToolResult(data_available=False, reason=snap.data_error or "Zone data unavailable.",
                           source="analysis.zones")
    return ToolResult(data_available=True, timestamp=_now(), source="analysis.zones", data={"zones": snap.zones})


def get_current_setup(_args: dict) -> ToolResult:
    snap = build_snapshot()
    if snap.data_error or snap.setup is None:
        return ToolResult(data_available=False, reason=snap.data_error or "Setup data unavailable.",
                           source="analysis.setup")
    s = snap.setup
    return ToolResult(
        data_available=True, timestamp=_now(), source="analysis.setup",
        data={
            "state": s.state, "direction": s.direction, "checklist": s.checklist,
            "entry_zone": s.entry_zone, "stop_loss": s.stop_loss, "take_profit": s.take_profit,
            "rr": s.rr, "reason": s.reason,
        },
    )


register(ToolSpec("get_market_state", "Market State",
                   "Current XAUUSD price, spread, session, and market regime.", _EMPTY_SCHEMA, get_market_state))
register(ToolSpec("get_market_structure", "Market Structure",
                   "Per-timeframe (H4/H1/M15/M5) structure state, last BOS/MSS.", _EMPTY_SCHEMA, get_market_structure))
register(ToolSpec("get_liquidity", "Liquidity",
                   "Recent liquidity sweeps, equal highs/lows, and displacement.", _EMPTY_SCHEMA, get_liquidity))
register(ToolSpec("get_key_zones", "Key Zones",
                   "Computed key price zones (H1/H4/M5).", _EMPTY_SCHEMA, get_key_zones))
register(ToolSpec("get_current_setup", "Current Setup",
                   "The deterministic setup engine's current state, checklist, and plan.",
                   _EMPTY_SCHEMA, get_current_setup))
