"""Persistent trading memory (Stage 7) — user-confirmed preferences,
strategy decisions, trade lessons, and recurring pattern observations.

Distinct from ai/knowledge/ (project documentation/rules, never personal),
distinct from journal/ (still the sole source of truth for trade records —
memory stores lessons ABOUT trades, never a duplicate of the records
themselves), and distinct from the live CONTEXT snapshot (deterministic
engine output). Memory is the lowest-authority evidence block the assistant
sees: below the deterministic engine, the journal, tool results, and Stage
5's RAG — see ai/prompts.py's ground rule 8.

The one structural guarantee this whole package exists to enforce: nothing
in ai/assistant.py's chat loop or any ai/tools/ handler ever calls
store.create_memory/update_memory/archive_memory. The only write path is
api/routes/memory.py, called by an explicit user action — never the LLM.
"""
