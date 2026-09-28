"""Read-only tool wrapper over ai.knowledge.retrieval.retrieve() (Stage 5) —
unchanged; this only exposes it as a tool the model can call explicitly
mid-conversation, alongside (never replacing) the always-on per-turn
retrieval that ai/assistant.py already runs on the user's raw message."""
from datetime import datetime, timezone

from ai.knowledge import retrieval as knowledge_retrieval
from ai.tools.registry import ToolSpec, register
from ai.tools.schemas import ToolResult


def search_strategy(args: dict) -> ToolResult:
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult(data_available=False, reason="query is required.", source="ai.knowledge")

    chunks = knowledge_retrieval.retrieve(query)
    now = datetime.now(timezone.utc).isoformat()
    if not chunks:
        return ToolResult(data_available=True, timestamp=now, source="ai.knowledge",
                           data={"results": [], "matched": 0})

    results = [
        {
            "source": c.source, "category": c.category, "version": c.version, "title": c.title,
            "similarity": c.similarity,
            "excerpt": (c.text[:300] + "…") if len(c.text) > 300 else c.text,
        }
        for c in chunks
    ]
    return ToolResult(data_available=True, timestamp=now, source="ai.knowledge",
                       data={"results": results, "matched": len(results)})


register(ToolSpec("search_strategy", "Strategy Knowledge Search",
                   "Search the seeded strategy/rules/methodology knowledge base.",
                   {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                   search_strategy))
