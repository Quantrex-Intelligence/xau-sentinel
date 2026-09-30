"""FundedNext MCP routes — a second, independent, read-only account-data
source, separate from the existing MT5-derived /api/fundednext/* routes
(api/routes/fundednext.py, untouched by this file). Every handler is a thin
wrapper over risk/fundednext_mcp.py; data_available=False is a normal,
documented 200 response (never an HTTP error), matching how
/api/market-intelligence already behaves when a provider is unavailable."""
from dataclasses import asdict

from fastapi import APIRouter

import config
from risk import fundednext_mcp

from api.schemas import FundedNextMcpConfigOut, FundedNextMcpResultOut

router = APIRouter(prefix="/api/fundednext/mcp", tags=["fundednext-mcp"])


def _out(result: fundednext_mcp.McpResult) -> FundedNextMcpResultOut:
    return FundedNextMcpResultOut(**asdict(result))


@router.get("/config", response_model=FundedNextMcpConfigOut)
def get_config():
    return FundedNextMcpConfigOut(configured=bool(config.FUNDEDNEXT_MCP_TOKEN))


@router.get("/accounts", response_model=FundedNextMcpResultOut)
async def get_accounts(status: str | None = None, tab: str = "forex"):
    return _out(await fundednext_mcp.get_accounts(status=status, tab=tab))


@router.get("/resolve/{login}", response_model=FundedNextMcpResultOut)
async def resolve_account(login: str):
    return _out(await fundednext_mcp.resolve_account(login))


@router.get("/accounts/{account_id}/overview", response_model=FundedNextMcpResultOut)
async def get_account_overview(account_id: str):
    return _out(await fundednext_mcp.get_account_overview(account_id))


@router.get("/accounts/{account_id}/trading-history", response_model=FundedNextMcpResultOut)
async def get_trading_history(account_id: str):
    return _out(await fundednext_mcp.get_trading_history(account_id))


@router.get("/accounts/{account_id}/risk-card", response_model=FundedNextMcpResultOut)
async def get_risk_card(account_id: str):
    return _out(await fundednext_mcp.get_risk_card(account_id))


@router.get("/accounts/{account_id}/breach-history", response_model=FundedNextMcpResultOut)
async def get_rule_breach_history(account_id: str):
    return _out(await fundednext_mcp.get_rule_breach_history(account_id))


@router.get("/payout-history", response_model=FundedNextMcpResultOut)
async def get_payout_wallet_card_history():
    return _out(await fundednext_mcp.get_payout_wallet_card_history())
