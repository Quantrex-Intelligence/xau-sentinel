"""AI Alert & Trade Explanation Layer (Stage 15) — explains an already-
existing monitoring alert or historical trade using structured, relevance-
gated evidence. Never decides whether an alert should exist, never
modifies an A+ rating/deterministic fact/risk status, never issues a
trading instruction. Reuses Stage 10's ContextualEvidence and several of
its renderers directly rather than duplicating them — see
ai/explanations/context.py.
"""
