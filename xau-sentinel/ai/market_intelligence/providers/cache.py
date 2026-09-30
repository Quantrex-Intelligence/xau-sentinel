"""A plain in-memory TTL cache — the whole reason Stage 11's real providers
never hit an external source more often than their configured TTL, no
matter how often the UI polls /api/market-intelligence or the A+ panel's
evidence builder runs. Deliberately not Redis/a file store/any external
infrastructure — an in-process dict is exactly what "lightweight in-memory
... caching" calls for, and this app is a single local process.

Process-lifetime only: restarting the API server clears it, which is fine —
the next request just re-fetches and re-populates.
"""
import time
from typing import Any, Awaitable, Callable, Dict, Tuple

_CACHE: Dict[str, Tuple[float, Any]] = {}


def get_or_fetch(key: str, ttl_seconds: float, fetch_fn: Callable[[], Any]) -> Any:
    """Returns the cached value for `key` if it hasn't expired; otherwise
    calls `fetch_fn()`, caches the result, and returns it. `fetch_fn` is
    only ever called on a genuine miss/expiry — a caller can raise inside
    it (e.g. a real HTTP error) and nothing gets cached, so the next call
    retries rather than caching a failure."""
    now = time.monotonic()
    cached = _CACHE.get(key)
    if cached is not None and cached[0] > now:
        return cached[1]

    value = fetch_fn()
    _CACHE[key] = (now + ttl_seconds, value)
    return value


async def get_or_fetch_async(key: str, ttl_seconds: float, fetch_fn: Callable[[], Awaitable[Any]]) -> Any:
    """Async counterpart of get_or_fetch, for an async source (FundedNext
    MCP — see risk/fundednext_mcp.py). Shares the same _CACHE store; callers
    namespace their own keys (e.g. "fundednext_mcp:...") to avoid colliding
    with the sync providers' keys."""
    now = time.monotonic()
    cached = _CACHE.get(key)
    if cached is not None and cached[0] > now:
        return cached[1]

    value = await fetch_fn()
    _CACHE[key] = (now + ttl_seconds, value)
    return value


def clear() -> None:
    """Test-only escape hatch — production code never needs to call this."""
    _CACHE.clear()
