"""FundedNext risk monitor routes — read-only decision support. Every
handler calls risk.fundednext.compute_status() (or the settings store) and
returns it as-is; no calculation happens in this file."""
from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from risk import settings_store
from risk.fundednext import compute_status
from risk.models import AccountType, Phase
from risk.rules import RULES

from api.schemas import (
    FundedNextRuleSetOut, FundedNextSettingsIn, FundedNextSettingsOut, FundedNextStatusOut,
    FundedNextViolationOut,
)

router = APIRouter(prefix="/api/fundednext", tags=["fundednext"])


def _status_out() -> FundedNextStatusOut:
    settings = settings_store.get_settings()
    status = compute_status(
        AccountType(settings["account_type"]), Phase(settings["phase"]),
        consistency_enabled=settings["consistency_enabled"],
    )
    data = asdict(status)
    data["account_type"] = status.account_type.value
    data["phase"] = status.phase.value
    data["safety_level"] = status.safety_level.value
    data["violations"] = [FundedNextViolationOut(rule=v.rule, level=v.level.value, message=v.message)
                           for v in status.violations]
    return FundedNextStatusOut(**data)


@router.get("/status", response_model=FundedNextStatusOut)
def get_status():
    return _status_out()


@router.get("/risk", response_model=FundedNextStatusOut)
def get_risk():
    """Alias of /status — same underlying computation, kept as a separate
    route since the spec calls for both names."""
    return _status_out()


@router.get("/violations", response_model=list[FundedNextViolationOut])
def get_violations():
    return _status_out().violations


@router.get("/rules", response_model=list[FundedNextRuleSetOut])
def get_rules_list():
    return [
        FundedNextRuleSetOut(
            account_type=r.account_type.value, label=r.label,
            daily_loss_pct=r.daily_loss_pct, max_loss_pct=r.max_loss_pct,
            profit_target_phase1_pct=r.profit_target_phase1_pct,
            profit_target_phase2_pct=r.profit_target_phase2_pct,
            min_trading_days=r.min_trading_days, consistency_pct=r.consistency_pct,
            drawdown_type=r.drawdown_type,
        )
        for r in RULES.values()
    ]


@router.get("/settings", response_model=FundedNextSettingsOut)
def get_settings():
    return FundedNextSettingsOut(**settings_store.get_settings())


@router.put("/settings", response_model=FundedNextSettingsOut)
def update_settings(payload: FundedNextSettingsIn):
    try:
        updated = settings_store.save_settings(
            account_type=payload.account_type, phase=payload.phase,
            consistency_enabled=payload.consistency_enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return FundedNextSettingsOut(**updated)
