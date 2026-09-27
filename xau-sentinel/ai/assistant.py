"""Orchestrates one chat turn: pick a provider -> build deterministic
context -> assemble messages -> call the provider -> apply the safety net ->
persist the turn -> return a typed response.

The LLM never becomes a source of truth here: context_used and sources are
built straight from ai/context.py's own AssembledContext, never parsed back
out of the model's prose (per Stage 3 spec section 10). Conversation history
lives in its own table (ai_messages), added via CREATE TABLE IF NOT EXISTS —
the frozen Stage 1 schema in journal/database.py is never touched, the same
pattern risk/fundednext_journal.py already established.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from journal.database import get_connection
from ai import context as context_builder
from ai import prompts
from ai.knowledge import retrieval as knowledge_retrieval
from ai.knowledge.schemas import KnowledgeSourceOut
from ai.providers import get_provider
from ai.schemas import AnswerCategory, ChatResponseOut, ContextSourceOut

TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ai_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

# Caps how much prior conversation gets replayed to the provider each turn —
# keeps token usage bounded without needing to summarize old turns for V1.
MAX_HISTORY_MESSAGES = 20


def init_table() -> None:
    with get_connection() as conn:
        conn.executescript(TABLE_SCHEMA)
        conn.commit()


def _load_history(conversation_id: str) -> List[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT role, content FROM ai_messages WHERE conversation_id = ? ORDER BY id ASC",
            (conversation_id,),
        ).fetchall()
    history = [{"role": r["role"], "content": r["content"]} for r in rows]
    return history[-MAX_HISTORY_MESSAGES:]


def _save_turn(conversation_id: str, user_message: str, assistant_message: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "INSERT INTO ai_messages (conversation_id, role, content) VALUES (?, 'user', ?)",
            (conversation_id, user_message),
        )
        conn.execute(
            "INSERT INTO ai_messages (conversation_id, role, content) VALUES (?, 'assistant', ?)",
            (conversation_id, assistant_message),
        )
        conn.commit()


def chat(message: str, conversation_id: Optional[str] = None,
         context_scope: Optional[List[str]] = None, trade_id: Optional[int] = None) -> ChatResponseOut:
    conversation_id = conversation_id or uuid.uuid4().hex

    # Resolve the provider FIRST: a missing/misconfigured provider should
    # fail fast, before spending a market-data fetch or a DB round trip on
    # context nobody's going to use.
    provider = get_provider()

    assembled = context_builder.build_context(context_scope, trade_id)
    # Independent of context_scope/trade_id: the user's raw message is the
    # retrieval query (semantic similarity over it *is* the intent signal —
    # no separate intent-classification step, per the Stage 5 design). Never
    # touches live market/account/journal data — only the seeded reference
    # documents (see ai/knowledge/).
    knowledge_chunks = knowledge_retrieval.retrieve(message)
    system_prompt = prompts.build_system_prompt(assembled, knowledge_chunks)
    history = _load_history(conversation_id)
    messages = prompts.build_messages(history, message)

    response = provider.chat(system_prompt, messages)

    answer_text = response.text
    overall_category = AnswerCategory.INTERPRETATION
    if prompts.contains_actionable_directive(answer_text):
        answer_text = prompts.SAFETY_OVERRIDE_MESSAGE
        overall_category = AnswerCategory.UNKNOWN
    elif not assembled.used_labels:
        # Nothing was available to ground the answer in — it can only be
        # framed as INTERPRETATION-of-nothing, which is really UNKNOWN.
        overall_category = AnswerCategory.UNKNOWN

    _save_turn(conversation_id, message, answer_text)

    sources = [
        ContextSourceOut(
            label=s.label,
            category=AnswerCategory.FACT if s.available else AnswerCategory.UNKNOWN,
            available=s.available,
            detail=s.detail,
        )
        for s in assembled.sections
    ]

    knowledge_used = [
        KnowledgeSourceOut(
            source=c.source, category=c.category, version=c.version, title=c.title,
            similarity=c.similarity, excerpt=(c.text[:200] + "…") if len(c.text) > 200 else c.text,
        )
        for c in knowledge_chunks
    ]

    return ChatResponseOut(
        answer=answer_text,
        conversation_id=conversation_id,
        context_used=assembled.used_labels,
        sources=sources,
        category=overall_category,
        provider=response.provider,
        model=response.model,
        created_at=datetime.now(timezone.utc).isoformat(),
        knowledge_used=knowledge_used,
    )
