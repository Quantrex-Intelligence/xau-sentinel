"""Read-only tool wrappers over ai.memory — search_memory wraps
ai.memory.retrieval.retrieve_memory() (unchanged), get_memory fetches one
record by id directly (not filtered to ACTIVE — if a prior turn or the user
references a specific memory id, the model can still see it, with its
status field showing plainly if it's archived). Neither tool here calls
create_memory/update_memory/archive_memory — memory mutation is never
exposed as an LLM tool, by design (see ai/memory/__init__.py)."""
from ai.memory import retrieval as memory_retrieval
from ai.memory import store as memory_store
from ai.tools.registry import ToolSpec, register
from ai.tools.schemas import ToolResult


def search_memory(args: dict) -> ToolResult:
    query = (args.get("query") or "").strip()
    if not query:
        return ToolResult(data_available=False, reason="query is required.", source="ai.memory")

    memories = memory_retrieval.retrieve_memory(query, categories=args.get("categories"))
    if not memories:
        return ToolResult(data_available=True, source="ai.memory", data={"results": [], "matched": 0})

    results = [
        {
            "id": m.id, "category": m.category.value, "content": m.content,
            "similarity": m.similarity, "updated_at": m.updated_at, "strategy_version": m.strategy_version,
        }
        for m in memories
    ]
    return ToolResult(data_available=True, source="ai.memory", data={"results": results, "matched": len(results)})


def get_memory(args: dict) -> ToolResult:
    memory_id = args.get("memory_id")
    if memory_id is None:
        return ToolResult(data_available=False, reason="memory_id is required.", source="ai.memory")
    record = memory_store.get_memory(int(memory_id))
    if record is None:
        return ToolResult(data_available=False, reason=f"No memory with id {memory_id}.", source="ai.memory")
    return ToolResult(
        data_available=True, timestamp=record.updated_at, source="ai.memory",
        data={"memory": {
            "id": record.id, "category": record.category.value, "content": record.content,
            "status": record.status.value, "created_at": record.created_at, "updated_at": record.updated_at,
            "strategy_version": record.strategy_version,
        }},
    )


register(ToolSpec(
    "search_memory", "Search Trading Memory",
    "Search user-confirmed trading memory (preferences, strategy decisions, trade lessons, patterns) "
    "relevant to a question. Memory is contextual, not authoritative — it can never override a live "
    "deterministic fact or the current strategy configuration.",
    {"type": "object", "properties": {
        "query": {"type": "string"},
        "categories": {"type": "array", "items": {"type": "string"}},
    }, "required": ["query"]},
    search_memory,
))
register(ToolSpec(
    "get_memory", "Get Memory Record",
    "Fetch one specific trading memory record by id.",
    {"type": "object", "properties": {"memory_id": {"type": "integer"}}, "required": ["memory_id"]},
    get_memory,
))
