"""Journal routes. Trade creation captures market context the same way
app.py does today: build a snapshot at the moment of creation and pass it
straight into journal.trades.create_trade's context dict — no separate
context-computation path. It also captures a FundedNext account/risk
snapshot at the same moment (see risk/fundednext_journal.py) — a one-time
INSERT, never updated, so historical trades never drift as the live
account changes later."""
from fastapi import APIRouter, HTTPException, Query

import config
from journal import trades as trades_repo
from risk import settings_store
from risk.fundednext import compute_status
from risk.fundednext_journal import get_snapshot as get_fundednext_snapshot
from risk.fundednext_journal import save_snapshot as save_fundednext_snapshot
from risk.models import AccountType, Phase
from risk.rules import get_rules

from api.schemas import AnalyticsOut, TradeCloseIn, TradeCreateIn, TradeOut
from api.snapshot import build_snapshot

router = APIRouter(prefix="/api/journal", tags=["journal"])


@router.get("/trades", response_model=list[TradeOut])
def list_trades(session: str | None = None, setup: str | None = None,
                 direction: str | None = None, regime: str | None = None):
    filters = {k: v for k, v in {
        "session": session, "setup": setup, "direction": direction, "regime": regime,
    }.items() if v}
    df = trades_repo.list_trades(filters)
    return [TradeOut(**row) for row in df.to_dict(orient="records")]


@router.get("/trades/{trade_id}", response_model=TradeOut)
def get_trade(trade_id: int):
    trade = trades_repo.get_trade(trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")
    # Attached only on the single-trade detail view, per spec — the list/
    # table view stays uncluttered.
    trade["fundednext_context"] = get_fundednext_snapshot(trade_id)
    return TradeOut(**trade)


@router.post("/trades", response_model=TradeOut)
def create_trade(payload: TradeCreateIn):
    snapshot = build_snapshot()
    structure = snapshot.structure

    trade_data = {
        "trade_date": payload.trade_date, "trade_time": payload.trade_time,
        "symbol": config.TRADING_SYMBOL, "direction": payload.direction,
        "session": snapshot.session, "entry": payload.entry, "stop_loss": payload.stop_loss,
        "take_profit": payload.take_profit, "planned_rr": payload.planned_rr,
        "setup": payload.setup, "market_regime": snapshot.regime.regime if snapshot.regime else None,
        "notes": payload.notes, "screenshot_path": None,
    }
    context = {
        "h4_bias": structure["H4"].state if "H4" in structure else None,
        "h1_bias": structure["H1"].state if "H1" in structure else None,
        "m15_bias": structure["M15"].state if "M15" in structure else None,
        "m5_bias": structure["M5"].state if "M5" in structure else None,
        "regime": snapshot.regime.regime if snapshot.regime else None,
        "liquidity": snapshot.liquidity.sweeps[-1].label if snapshot.liquidity.sweeps else None,
        "mss": ((structure["M5"].last_mss or "").title() or None) if "M5" in structure else None,
        "displacement": (snapshot.displacement or "").title() or None,
        "session": snapshot.session,
    }
    trade_id = trades_repo.create_trade(trade_data, context)

    fn_settings = settings_store.get_settings()
    account_type = AccountType(fn_settings["account_type"])
    fn_status = compute_status(account_type, Phase(fn_settings["phase"]), fn_settings["consistency_enabled"])
    rules = get_rules(account_type)
    save_fundednext_snapshot(trade_id, fn_status, rules.daily_loss_pct, rules.max_loss_pct)

    return TradeOut(**trades_repo.get_trade(trade_id))


@router.patch("/trades/{trade_id}/close", response_model=TradeOut)
def close_trade(trade_id: int, payload: TradeCloseIn):
    if trades_repo.get_trade(trade_id) is None:
        raise HTTPException(status_code=404, detail="Trade not found")
    trades_repo.close_trade(trade_id, payload.model_dump())
    return TradeOut(**trades_repo.get_trade(trade_id))


@router.get("/analytics", response_model=AnalyticsOut)
def get_analytics(session: str | None = None, setup: str | None = None,
                   direction: str | None = None, regime: str | None = None):
    filters = {k: v for k, v in {
        "session": session, "setup": setup, "direction": direction, "regime": regime,
    }.items() if v}
    df = trades_repo.list_trades(filters)
    return AnalyticsOut(**trades_repo.compute_analytics(df))
