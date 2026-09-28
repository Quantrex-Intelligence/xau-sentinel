"""Trading memory routes (Stage 7) — the ONLY write entry point for a
memory record in the whole application. Every handler is a thin call into
ai.memory.store; no calculation or LLM logic lives here. POST here is what
"explicit user confirmation" means structurally: nothing in the chat/tool
loop ever calls store.create_memory/update_memory/archive_memory, so a
memory record can only ever originate from a human hitting one of these
endpoints (see ai/memory/__init__.py)."""
from fastapi import APIRouter, HTTPException

from ai.memory import store
from ai.memory.models import MemoryCategory
from ai.memory.schemas import MemoryCreateIn, MemoryRecordOut, MemoryUpdateIn

router = APIRouter(prefix="/api/ai/memory", tags=["memory"])


def _out(record) -> MemoryRecordOut:
    return MemoryRecordOut(
        id=record.id, category=record.category, content=record.content, source=record.source,
        status=record.status.value, created_at=record.created_at, updated_at=record.updated_at,
        strategy_version=record.strategy_version,
    )


@router.get("", response_model=list[MemoryRecordOut])
def list_memories(category: str | None = None, include_archived: bool = False):
    parsed_category = None
    if category is not None:
        try:
            parsed_category = MemoryCategory(category)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Unknown category '{category}'.")
    records = store.list_memories(category=parsed_category, include_archived=include_archived)
    return [_out(r) for r in records]


@router.get("/{memory_id}", response_model=MemoryRecordOut)
def get_memory(memory_id: int):
    record = store.get_memory(memory_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No memory with id {memory_id}.")
    return _out(record)


@router.post("", response_model=MemoryRecordOut)
def create_memory(payload: MemoryCreateIn):
    """The explicit "Save to memory" action — always called by a direct
    user click, never by the assistant/tool loop. `source` is not accepted
    here at all; ai.memory.store.create_memory() sets it unconditionally."""
    record = store.create_memory(
        category=payload.category, content=payload.content, strategy_version=payload.strategy_version,
    )
    return _out(record)


@router.patch("/{memory_id}", response_model=MemoryRecordOut)
def update_memory(memory_id: int, payload: MemoryUpdateIn):
    record = store.update_memory(
        memory_id, content=payload.content, category=payload.category, strategy_version=payload.strategy_version,
    )
    if record is None:
        raise HTTPException(status_code=404, detail=f"No memory with id {memory_id}.")
    return _out(record)


@router.post("/{memory_id}/archive", response_model=MemoryRecordOut)
def archive_memory(memory_id: int):
    record = store.archive_memory(memory_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"No memory with id {memory_id}.")
    return _out(record)
