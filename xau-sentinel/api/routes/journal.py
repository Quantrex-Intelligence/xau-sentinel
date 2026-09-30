"""Journal routes. Trade creation captures market context the same way
app.py does today: build a snapshot at the moment of creation and pass it
straight into journal.trades.create_trade's context dict — no separate
context-computation path. It also captures a FundedNext account/risk
snapshot at the same moment (see risk/fundednext_journal.py) — a one-time
INSERT, never updated, so historical trades never drift as the live
account changes later. The trade and its snapshot are committed in ONE
transaction (Stage 23D, VAL-029): a trade is never saved without its risk
snapshot."""
import logging

from fastapi import APIRouter, HTTPException, Query

import config
from journal import trades as trades_repo
from journal.database import get_connection
from risk import settings_store
from risk.fundednext import compute_status
from risk.fundednext_journal import get_snapshot as get_fundednext_snapshot
from risk.fundednext_journal import save_snapshot as save_fundednext_snapshot
from risk.models import AccountType, Phase
from risk.rules import get_rules

from api.schemas import AnalyticsOut, TradeCloseIn, TradeCreateIn, TradeOut
from api.snapshot import build_snapshot

router = APIRouter(prefix="/api/journal", tags=["journal"])

logger = logging.getLogger(__name__)


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
    # By default trade_date/trade_time are captured here from ONE instant in
    # config.SESSION_TIMEZONE (Stage 22, VAL-012) — the browser can't know
    # that zone. An explicit pair (validated together in TradeCreateIn) is
    # an intentional session-local backfill and is stored as given.
    if payload.trade_date is None:
        now = trades_repo.session_now()
        trade_date, trade_time = now.date().isoformat(), now.strftime("%H:%M:%S")
    else:
        trade_date, trade_time = payload.trade_date, payload.trade_time

    trade_data = {
        "trade_date": trade_date, "trade_time": trade_time,
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
    # Stage 23D, VAL-029: the FundedNext status (which may call MT5) is
    # computed BEFORE anything is written, and the trade + its snapshot are
    # then inserted on one connection and committed together. Any failure
    # rolls back both (the connection closes uncommitted), so there is never
    # a trade without its risk snapshot, and the client gets a clear 500
    # saying nothing was saved instead of a bare traceback.
    try:
        fn_settings = settings_store.get_settings()
        account_type = AccountType(fn_settings["account_type"])
        fn_status = compute_status(account_type, Phase(fn_settings["phase"]), fn_settings["consistency_enabled"])
        rules = get_rules(account_type)
        with get_connection() as conn:
            trade_id = trades_repo.create_trade(trade_data, context, conn=conn)
            save_fundednext_snapshot(trade_id, fn_status, rules.daily_loss_pct, rules.max_loss_pct, conn=conn)
            conn.commit()
    except Exception as exc:
        logger.exception("Trade creation failed; nothing was saved")
        raise HTTPException(
            status_code=500,
            detail=f"Trade not saved: recording the trade with its FundedNext risk snapshot failed "
                   f"({type(exc).__name__}). Nothing was written; please retry.",
        ) from exc

    return TradeOut(**trades_repo.get_trade(trade_id))


@router.patch("/trades/{trade_id}/close", response_model=TradeOut)
def close_trade(trade_id: int, payload: TradeCloseIn):
    trade = trades_repo.get_trade(trade_id)
    if trade is None:
        raise HTTPException(status_code=404, detail="Trade not found")
    # Stage 23D, VAL-024: a close is only valid on an OPEN trade. Without
    # this a re-submitted close silently overwrote result/pnl/r_multiple
    # (and nulled any field omitted the second time). close_trade()'s own
    # `status = 'OPEN'` guard also catches a concurrent double-close.
    if trade["status"] != "OPEN" or not trades_repo.close_trade(trade_id, payload.model_dump()):
        raise HTTPException(status_code=409, detail=f"Trade {trade_id} is already closed")
    return TradeOut(**trades_repo.get_trade(trade_id))


@router.get("/analytics", response_model=AnalyticsOut)
def get_analytics(session: str | None = None, setup: str | None = None,
                   direction: str | None = None, regime: str | None = None):
    filters = {k: v for k, v in {
        "session": session, "setup": setup, "direction": direction, "regime": regime,
    }.items() if v}
    df = trades_repo.list_trades(filters)
    return AnalyticsOut(**trades_repo.compute_analytics(df))
