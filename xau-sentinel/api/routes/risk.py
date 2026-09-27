from fastapi import APIRouter

import config
from journal import trades as trades_repo

from api.schemas import RiskOut

router = APIRouter(prefix="/api/risk", tags=["risk"])


@router.get("", response_model=RiskOut)
def get_risk():
    return RiskOut(
        balance=config.ACCOUNT_BALANCE,
        risk_per_trade_pct=config.RISK_PER_TRADE_PCT,
        today_r=trades_repo.today_r_total(),
    )
