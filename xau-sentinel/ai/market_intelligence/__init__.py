"""Market Intelligence Layer (Stage 9) — macro, gold fundamentals,
cross-asset, economic events, and news, as a separate evidence source from
Sentinel's own technical/risk engines, Stage 5's RAG, Stage 7's memory, and
Stage 8's historical similarity.

Stateless: no new database table (this stage ships the interface plus a
mock backend, not persistence). Reachable only through explicit tools (see
ai/tools/market_intelligence_tools.py) — never auto-injected into every
chat turn, and never authoritative over the deterministic engine, the A+
evaluation, or FundedNext risk facts (see ai/prompts.py ground rule 10).
"""
