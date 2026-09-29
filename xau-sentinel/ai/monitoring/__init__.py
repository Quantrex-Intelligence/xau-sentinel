"""Real-Time Monitoring & In-App Alert Engine (Stage 13) — watches the
existing deterministic engines (setup state, A+ evaluator, FundedNext
risk, Market Intelligence quality) for state transitions and turns them
into typed, deduplicated, acknowledgeable alerts. Every alert condition is
a plain comparison of already-computed deterministic values; the LLM is
never involved in deciding whether an alert condition exists (see
ai/monitoring/engine.py).
"""
