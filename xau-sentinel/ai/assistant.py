"""Orchestrates one chat turn: pick a provider -> build deterministic
context -> assemble messages -> run the tool-calling loop -> apply the
safety net -> persist the turn -> return a typed response.

The LLM never becomes a source of truth here: context_used and sources are
built straight from ai/context.py's own AssembledContext, never parsed back
out of the model's prose (per Stage 3 spec section 10). Conversation history
lives in its own table (ai_messages), added via CREATE TABLE IF NOT EXISTS —
the frozen Stage 1 schema in journal/database.py is never touched, the same
pattern risk/fundednext_journal.py already established.

Stage 6 adds a bounded tool-calling loop: each round offers the provider the
full tool registry; if it calls one or more tools, they're executed via
ai/tools/executor.py and the results are fed back for another round, up to
config.AI_TOOL_MAX_ROUNDS. A provider that never requests a tool (including
every pre-Stage-6 test double, since ProviderResponse.tool_calls defaults to
empty) exits the loop after exactly one call — identical to the pre-Stage-6
single-shot behavior.
"""
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from sqlalchemy import select, insert

import config
from journal.database import get_connection
from journal.schema import ai_messages
from ai import context as context_builder
from ai import prompts
from ai.knowledge import retrieval as knowledge_retrieval
from ai.knowledge.schemas import KnowledgeSourceOut
from ai.memory import retrieval as memory_retrieval
from ai.memory.schemas import MemoryUsedOut
from ai.providers import get_provider
from ai.schemas import AnswerCategory, ChatResponseOut, ContextSourceOut
from ai.tools import execute as execute_tool
from ai.tools.registry import get_spec as get_tool_spec, to_provider_format as tool_specs_for_provider
from ai.tools.schemas import ToolUsageOut

# Caps how much prior conversation gets replayed to the provider each turn —
# keeps token usage bounded without needing to summarize old turns for V1.
MAX_HISTORY_MESSAGES = 20


def _load_history(conversation_id: str) -> List[dict]:
    with get_connection() as conn:
        rows = conn.execute(
            select(ai_messages.c.role, ai_messages.c.content)
            .where(ai_messages.c.conversation_id == conversation_id)
            .order_by(ai_messages.c.id.asc())
        ).fetchall()
    history = [{"role": r.role, "content": r.content} for r in rows]
    return history[-MAX_HISTORY_MESSAGES:]


def _save_turn(conversation_id: str, user_message: str, assistant_message: str) -> None:
    with get_connection() as conn:
        conn.execute(
            insert(ai_messages).values(conversation_id=conversation_id, role="user", content=user_message)
        )
        conn.execute(
            insert(ai_messages).values(conversation_id=conversation_id, role="assistant", content=assistant_message)
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
    # Same shape as knowledge retrieval, a separate layer (Stage 7): only
    # ever reads user-confirmed memory, never writes it — see ai/memory/.
    memories = memory_retrieval.retrieve_memory(message)
    system_prompt = prompts.build_system_prompt(assembled, knowledge_chunks, memories)
    history = _load_history(conversation_id)
    messages = prompts.build_messages(history, message)

    response, tools_used = _run_tool_loop(provider, system_prompt, messages)

    answer_text = prompts.strip_markdown_for_display(response.text)
    overall_category = AnswerCategory.INTERPRETATION
    if prompts.contains_actionable_directive(answer_text):
        answer_text = prompts.SAFETY_OVERRIDE_MESSAGE
        overall_category = AnswerCategory.UNKNOWN
    elif prompts.contains_predictive_probability_claim(answer_text):
        answer_text = prompts.SIMILARITY_SAFETY_OVERRIDE_MESSAGE
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

    memory_used = [
        MemoryUsedOut(
            id=m.id, category=m.category, similarity=m.similarity, updated_at=m.updated_at,
            excerpt=(m.content[:200] + "…") if len(m.content) > 200 else m.content,
        )
        for m in memories
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
        tools_used=tools_used,
        memory_used=memory_used,
    )


def _run_tool_loop(provider, system_prompt: str, messages: List[dict]):
    """Runs the bounded LLM <-> tool round trip for one turn. A provider
    that never returns tool_calls (every pre-Stage-6 provider/test double)
    exits after exactly one call, with `messages` unchanged from what it
    would have been pre-Stage-6 — the backward-compatibility guarantee this
    loop is built around.

    Mutates `messages` in place by appending the transient tool-use/
    tool-result turns for this call only; none of that is persisted to the
    ai_messages history table (see _save_turn — only the final answer is)."""
    tool_specs = tool_specs_for_provider()
    tools_used: List[ToolUsageOut] = []
    response = None

    for _round in range(config.AI_TOOL_MAX_ROUNDS):
        response = provider.chat(system_prompt, messages, tools=tool_specs)
        if not response.tool_calls:
            return response, tools_used

        messages.append({
            "role": "assistant",
            "content": response.raw_content if response.raw_content is not None else response.text,
            "tool_calls": response.tool_calls,
        })
        for call in response.tool_calls:
            result = execute_tool(call.name, call.arguments)
            spec = get_tool_spec(call.name)
            tools_used.append(ToolUsageOut(
                name=call.name,
                label=spec.label if spec else call.name,
                data_available=bool(result.get("data_available", False)),
                timestamp=result.get("timestamp"),
            ))
            messages.append({
                "role": "tool_result",
                "tool_call_id": call.id,
                "name": call.name,
                "content": result,
            })
    else:
        # Round cap reached and the last response still requested a tool —
        # force one final, tool-free call so the turn always ends in text.
        response = provider.chat(system_prompt, messages, tools=None)

    return response, tools_used
