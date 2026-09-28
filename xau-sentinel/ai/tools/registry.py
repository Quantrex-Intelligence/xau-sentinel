"""The tool registry — one dict every other piece reads from: the
provider-facing tool definitions (to_provider_format(), sent to the LLM),
the executor's dispatch table (executor.py), and the GET /api/ai/tools
introspection route. Category modules (market_tools.py, risk_tools.py,
journal_tools.py, knowledge_tools.py) populate this at import time via
register() — see ai/tools/__init__.py.
"""
from dataclasses import dataclass
from typing import Callable, Dict, List

from ai.tools.schemas import ToolResult


@dataclass
class ToolSpec:
    name: str
    label: str  # human-readable, for the "Tools used" UI panel
    description: str
    input_schema: dict  # JSON schema — also Anthropic's `input_schema` tool shape
    handler: Callable[[dict], ToolResult]


TOOL_SPECS: Dict[str, ToolSpec] = {}


def register(spec: ToolSpec) -> None:
    TOOL_SPECS[spec.name] = spec


def get_spec(name: str) -> ToolSpec | None:
    return TOOL_SPECS.get(name)


def to_provider_format() -> List[dict]:
    """Anthropic Messages API tool shape: [{name, description, input_schema}, ...].
    The only real external provider this app integrates, so the registry
    targets that shape directly rather than adding an abstraction for a
    second backend that doesn't exist yet."""
    return [
        {"name": s.name, "description": s.description, "input_schema": s.input_schema}
        for s in TOOL_SPECS.values()
    ]
