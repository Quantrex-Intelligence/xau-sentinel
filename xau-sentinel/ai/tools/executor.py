"""Executes one tool call by name: validates the tool exists and its
required arguments are present, runs the handler, and catches any exception
into a structured `data_available: False` result. A tool can degrade; it
can never crash the chat turn or let a raw exception reach the model or the
API layer (see ai/assistant.py's round-trip loop, which calls this once per
requested tool call)."""
from typing import Any, Dict

from ai.tools import registry


def execute(name: str, arguments: Dict[str, Any] | None) -> dict:
    arguments = arguments or {}
    spec = registry.get_spec(name)
    if spec is None:
        return {"data_available": False, "reason": f"Unknown tool '{name}'.", "timestamp": None, "source": None}

    missing = [f for f in spec.input_schema.get("required", []) if f not in arguments]
    if missing:
        return {
            "data_available": False,
            "reason": f"Missing required argument(s) for '{name}': {', '.join(missing)}.",
            "timestamp": None, "source": None,
        }

    try:
        result = spec.handler(arguments)
    except Exception as exc:  # noqa: BLE001 - a tool failure degrades, never crashes the turn
        return {"data_available": False, "reason": str(exc), "timestamp": None, "source": None}

    return result.to_dict()
