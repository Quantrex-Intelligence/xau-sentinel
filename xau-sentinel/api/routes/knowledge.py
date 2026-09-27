"""Knowledge-base introspection routes — read-only listing plus a minimal
endpoint for adding the user's own trading notes/playbook (the "future user
trading notes" source named in the Stage 5 spec). No retrieval logic lives
here; every handler is a thin call into ai.knowledge.store."""
from fastapi import APIRouter

from ai.knowledge import store
from ai.knowledge.schemas import KnowledgeDocumentOut
from pydantic import BaseModel

router = APIRouter(prefix="/api/ai/knowledge", tags=["knowledge"])


class UserNoteIn(BaseModel):
    title: str
    content: str
    version: str = "1.0"


@router.get("/documents", response_model=list[KnowledgeDocumentOut])
def list_documents(active_only: bool = True):
    docs = store.list_documents(active_only=active_only)
    return [
        KnowledgeDocumentOut(
            id=d.id, source=d.source, category=d.category, version=d.version,
            title=d.title, is_active=d.is_active, created_at=d.created_at,
        )
        for d in docs
    ]


@router.post("/notes", response_model=KnowledgeDocumentOut)
def add_user_note(payload: UserNoteIn):
    """Adds (or re-versions, if the same title was used before) a user
    trading note — the only knowledge category with no seeded content,
    since seeding a placeholder there would misrepresent it as real user
    input (see ai/knowledge/seed_documents.py)."""
    document_id = store.add_document(
        source=f"user_notes:{payload.title}", category="user_notes",
        version=payload.version, title=payload.title, content=payload.content,
    )
    doc = next(d for d in store.list_documents(active_only=False) if d.id == document_id)
    return KnowledgeDocumentOut(
        id=doc.id, source=doc.source, category=doc.category, version=doc.version,
        title=doc.title, is_active=doc.is_active, created_at=doc.created_at,
    )
