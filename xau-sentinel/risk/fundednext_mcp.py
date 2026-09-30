"""FundedNext MCP client — a second, independent, read-only account-data
source (account/balance/status, trading history, risk/rule/compliance data,
payout info) fetched from FundedNext's own official MCP server. This module
never imports from, calls, or is called by risk/fundednext.py: that module
stays 100% MT5-derived, exactly as before this integration. MT5 remains the
only source for prices/candles/spread/open positions.

FUNDEDNEXT_MCP_TOKEN unset (the default) means every function below returns
data_available=False with no connection attempt at all — the same
graceful-degradation contract as AI_API_KEY / MARKET_INTEL_FRED_API_KEY.

Two real, live-verified quirks of this server (captured via a real
introspection session against https://mcp.fundednext.com, never guessed)
drive the shape of this module:
- A tool's text response mixes real JSON with a trailing
  "[INTERNAL — FOR AI, NOT CUSTOMER]" instructional block that must be
  stripped before parsing and must never reach an API consumer.
- Only get_accounts' response shape was live-verified this session; the
  other tools' shapes are documented but not all live-called, so `raw`
  below is the verbatim MCP JSON rather than a hand-modeled dataclass —
  never guessing a schema beyond what was actually observed or documented.
"""
import json
from dataclasses import dataclass
from typing import Any, Optional

import httpx

import config
from ai.market_intelligence.providers import cache

try:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
except ImportError:
    ClientSession = None
    streamable_http_client = None

_INTERNAL_MARKER = "[INTERNAL"


@dataclass
class McpResult:
    data_available: bool
    reason: Optional[str] = None
    raw: Optional[Any] = None


def _not_configured() -> McpResult:
    return McpResult(data_available=False, reason="FundedNext MCP is not configured (FUNDEDNEXT_MCP_TOKEN is unset).")


def _strip_internal_block(text: str) -> str:
    idx = text.find(_INTERNAL_MARKER)
    return text[:idx].strip() if idx != -1 else text.strip()


async def _call_tool_uncached(name: str, arguments: dict) -> Any:
    if ClientSession is None or streamable_http_client is None:
        raise ImportError(
            "The 'mcp' package is not installed. Run `pip install -r api/requirements.txt` to enable "
            "the FundedNext MCP integration."
        )

    http_client = httpx.AsyncClient(
        headers={"Authorization": f"Bearer {config.FUNDEDNEXT_MCP_TOKEN}"},
        timeout=config.FUNDEDNEXT_MCP_TIMEOUT_SECONDS,
    )
    async with http_client:
        async with streamable_http_client(config.FUNDEDNEXT_MCP_URL, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)

    text_parts = [block.text for block in (result.content or []) if getattr(block, "type", None) == "text"]
    if not text_parts:
        raise ValueError("FundedNext MCP tool call returned no text content.")
    return json.loads(_strip_internal_block("\n".join(text_parts)))


async def _call_tool(name: str, arguments: Optional[dict] = None) -> McpResult:
    if not config.FUNDEDNEXT_MCP_TOKEN:
        return _not_configured()

    arguments = arguments or {}
    cache_key = f"fundednext_mcp:{name}:{sorted(arguments.items())}"

    async def _fetch():
        return await _call_tool_uncached(name, arguments)

    try:
        raw = await cache.get_or_fetch_async(cache_key, config.FUNDEDNEXT_MCP_CACHE_TTL_SECONDS, _fetch)
    except Exception as exc:  # noqa: BLE001 - connection/auth/JSON failure all degrade to "unavailable"
        return McpResult(data_available=False, reason=str(exc))
    return McpResult(data_available=True, raw=raw)


async def resolve_account(login: str) -> McpResult:
    return await _call_tool("resolve_account", {"login": login})


async def get_accounts(status: Optional[str] = None, tab: str = "forex") -> McpResult:
    args = {"tab": tab}
    if status is not None:
        args["type"] = status
    return await _call_tool("get_accounts", args)


async def get_account_overview(account_id: str) -> McpResult:
    return await _call_tool("get_account_overview", {"account_id": account_id})


async def get_trading_history(account_id: str) -> McpResult:
    return await _call_tool("get_trading_history", {"account_id": account_id})


async def get_risk_card(account_id: str) -> McpResult:
    return await _call_tool("get_risk_card", {"account_id": account_id})


async def get_rule_breach_history(account_id: str) -> McpResult:
    # This tool's real input_schema (confirmed live) takes `id`, not
    # `account_id` like every other per-account tool here -- verified via
    # the live schema capture, not guessed.
    return await _call_tool("get_rule_breach_history", {"id": int(account_id)})


async def get_payout_wallet_card_history() -> McpResult:
    return await _call_tool("get_payout_wallet_card_history")
