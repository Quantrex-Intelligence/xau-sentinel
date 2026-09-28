"""Read-only tool layer for the AI assistant's tool-calling loop (Stage 6).

`registry` is the single source of truth for "what tools exist" — the
provider-facing tool definitions (registry.to_provider_format()), the
executor's dispatch table, and the GET /api/ai/tools introspection route all
read from the same TOOL_SPECS dict. Importing the category modules below
populates it as a side effect (each one calls registry.register() for its
own tools at import time).

Every tool wraps an EXISTING deterministic engine call (api.snapshot,
risk.fundednext, journal.trades, ai.knowledge.retrieval, mt5.account) — no
new analysis or calculation logic lives here, only read-only slicing and
formatting. No tool here writes, places, closes, or modifies anything.
"""
from ai.tools import registry
from ai.tools.executor import execute
from ai.tools import market_tools, risk_tools, journal_tools, knowledge_tools  # noqa: F401  (populates registry.TOOL_SPECS)

__all__ = ["registry", "execute"]
