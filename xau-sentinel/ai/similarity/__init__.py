"""Historical Setup Similarity (Stage 8) — a deterministic, descriptive
comparison of the current (or a past) setup against the journal's own
historical trades. Explicitly NOT RAG (see ai/knowledge/) and NOT an ML/
probability model: a documented, configurable weighted-feature match (see
ai/similarity/scoring.py) over data captured at trade entry (see
ai/similarity/features.py's no-look-ahead boundary).

Stateless: no new database table. Every function here reads existing
journal/api state and returns typed results; nothing writes anything.
"""
