"""Telegram Alert Delivery (Stage 14) — a downstream notification sink for
ai.monitoring's already-decided alerts. Never re-runs the deterministic
engines, the A+ evaluator, Market Intelligence, or an LLM to decide what
to send or whether to send it; monitoring_alerts is the sole source of
truth. ai/monitoring/ never imports anything from this package.
"""
