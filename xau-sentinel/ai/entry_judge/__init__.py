"""LLM Setup Judge V1 for Entry Model V2 — shadow mode (see docstrings in this package's modules).

Named distinctly from ai/verification.py's unrelated `AI_JUDGE_ENABLED`/`judge_answer` (a chat-
answer fact-checker, nothing to do with trade setups) to avoid any collision or confusion.

Nothing in this package is imported by analysis/entry_model/*, ai/strategy/*, the alerts/monitoring
pipeline, or research/entry_model_v2_oos/* — it only ever reads an already-fully-decided
hierarchy.evaluate() result and api/analysis_v2.py V2 payload, and writes to its own table
(journal/schema.py::entry_model_judgments). It can never affect direction, state, entry_candidate,
or any OOS research result.
"""
