"""Thin HTTP helper shared by every real Market Intelligence provider
(ai/market_intelligence/providers/real.py). httpx is already a project
dependency (api/requirements.txt) — no new one added for this.

Deliberately just two plain functions, not a persistent client/session:
each real provider call is independent and infrequent (backed by
ai/market_intelligence/providers/cache.py), so there's no meaningful
connection-reuse benefit to a shared client, and plain functions are what
every test in this project monkeypatches directly (the same pattern
ai/providers/get_provider() and every other swappable call in this codebase
already uses) — see tests/test_market_intelligence_real_providers.py.

Never raises a provider-specific exception here: httpx's own exceptions
(timeout, connection error, HTTP status error) propagate to the caller,
which is always a real.py method that catches them and degrades to
data_available=False — the same "no exceptions for no data" contract every
other provider in this project already follows.
"""
from typing import Any, Dict, Optional

import httpx

import config

_USER_AGENT = "XAU-Sentinel/1.0 (personal read-only trading terminal; +https://github.com/Quantrex-Intelligence/propfirm-dashboard)"


def get_json(url: str, params: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> Any:
    resp = httpx.get(
        url, params=params, headers={"User-Agent": _USER_AGENT},
        timeout=timeout if timeout is not None else config.MARKET_INTEL_HTTP_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.json()


def get_text(url: str, params: Optional[Dict[str, Any]] = None, timeout: Optional[float] = None) -> str:
    resp = httpx.get(
        url, params=params, headers={"User-Agent": _USER_AGENT},
        timeout=timeout if timeout is not None else config.MARKET_INTEL_HTTP_TIMEOUT_SECONDS,
    )
    resp.raise_for_status()
    return resp.text
