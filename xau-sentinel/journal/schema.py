"""Single source of truth for every table in the database (DEP-002).

One shared MetaData, imported by both journal/database.py's engine wiring
and alembic/env.py's autogenerate target — every store module builds its
queries against the Table objects defined here rather than raw SQL
strings. This intentionally replaces the CREATE TABLE IF NOT EXISTS blocks
that used to live next to each store module's functions: that pattern
never migrated an existing table (the exact trap DEP-002 exists to close),
so schema now lives in one place and changes only ever go through an
Alembic migration.

Timestamp columns fall into two groups, per the DEP-002 plan:
- columns that only ever relied on SQLite's bare `datetime('now')` default
  get `server_default=func.now()` here;
- columns the application already wrote explicitly (usually as an aware
  UTC datetime) keep no server default -- callers pass a `datetime` object
  directly now, not an `.isoformat()` string.

JSON-was-TEXT columns (`details`, `payload`, `embedding`, `snapshot`) stay
as Text with Python-side json.dumps/loads, deliberately not moved to
native JSON/JSONB in this migration -- see the DEP-002 plan.
"""
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    Date,
    Float,
    ForeignKey,
    Identity,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    TIMESTAMP,
    UniqueConstraint,
    func,
)

metadata = MetaData()

# --- Stage 1: journal core ---------------------------------------------

trades = Table(
    "trades",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("trade_date", Text, nullable=False),
    Column("trade_time", Text, nullable=False),
    Column("symbol", Text, nullable=False),
    Column("direction", Text, nullable=False),
    Column("session", Text),
    Column("entry", Float, nullable=False),
    Column("stop_loss", Float, nullable=False),
    Column("take_profit", Float),
    Column("planned_rr", Float),
    Column("setup", Text),
    Column("market_regime", Text),
    Column("notes", Text),
    Column("screenshot_path", Text),
    Column("exit_price", Float),
    Column("result", Text),
    Column("pnl", Float),
    Column("r_multiple", Float),
    Column("duration_minutes", Float),
    Column("exit_reason", Text),
    Column("rule_followed", Text),
    Column("mistake", Text),
    Column("exit_notes", Text),
    Column("status", Text, nullable=False, server_default="OPEN"),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=func.now()),
)

journal_context = Table(
    "journal_context",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("trade_id", Integer, ForeignKey("trades.id", ondelete="CASCADE"), nullable=False),
    Column("h4_bias", Text),
    Column("h1_bias", Text),
    Column("m15_bias", Text),
    Column("m5_bias", Text),
    Column("regime", Text),
    Column("liquidity", Text),
    Column("mss", Text),
    Column("displacement", Text),
    Column("session", Text),
    Column("captured_at", TIMESTAMP(timezone=True), nullable=False, server_default=func.now()),
)

market_events = Table(
    "market_events",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("event_time", TIMESTAMP(timezone=True), nullable=False),
    Column("event_type", Text, nullable=False),
    Column("description", Text, nullable=False),
    Column("timeframe", Text),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=func.now()),
)

alerts = Table(
    "alerts",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("alert_time", TIMESTAMP(timezone=True), nullable=False),
    Column("level", Text, nullable=False),
    Column("direction", Text),
    Column("message", Text, nullable=False),
    Column("details", Text),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=func.now()),
)

# --- Stage 2: FundedNext risk context -----------------------------------

fundednext_context = Table(
    "fundednext_context",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("trade_id", Integer, ForeignKey("trades.id", ondelete="CASCADE"), nullable=False),
    Column("data_available", Boolean, nullable=False),
    Column("account_type", Text),
    Column("phase", Text),
    Column("mode", Text),
    Column("balance", Float),
    Column("equity", Float),
    Column("today_pnl", Float),
    Column("daily_loss_remaining", Float),
    Column("daily_loss_used_pct", Float),
    Column("max_drawdown_remaining", Float),
    Column("max_drawdown_used_pct", Float),
    Column("daily_loss_pct_rule", Float),
    Column("max_loss_pct_rule", Float),
    Column("safety_level", Text),
    Column("reason", Text),
    Column("captured_at", TIMESTAMP(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("trade_id", name="idx_fundednext_context_trade_id"),
)

# --- Stage 3: AI assistant conversation history -------------------------

ai_messages = Table(
    "ai_messages",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("conversation_id", Text, nullable=False),
    Column("role", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=func.now()),
)

# --- Stage 5: knowledge / RAG --------------------------------------------

knowledge_documents = Table(
    "knowledge_documents",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("source", Text, nullable=False),
    Column("category", Text, nullable=False),
    Column("version", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("is_active", Boolean, nullable=False, server_default="true"),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=func.now()),
)

knowledge_chunks = Table(
    "knowledge_chunks",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("document_id", Integer, ForeignKey("knowledge_documents.id", ondelete="CASCADE"), nullable=False),
    Column("chunk_index", Integer, nullable=False),
    Column("text", Text, nullable=False),
    Column("embedding", Text, nullable=False),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False, server_default=func.now()),
)

# --- Stage 7: trading memory ---------------------------------------------

memory_records = Table(
    "memory_records",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("category", Text, nullable=False),
    Column("content", Text, nullable=False),
    Column("embedding", Text, nullable=False),
    Column("source", Text, nullable=False),
    Column("strategy_version", Text),
    Column("status", Text, nullable=False, server_default="ACTIVE"),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False),
    Column("updated_at", TIMESTAMP(timezone=True), nullable=False),
)

# --- Stage 13: monitoring alerts + persisted baseline ---------------------

monitoring_alerts = Table(
    "monitoring_alerts",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("alert_type", Text, nullable=False),
    Column("severity", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("message", Text, nullable=False),
    Column("symbol", Text, nullable=False, server_default="XAUUSD"),
    Column("payload", Text, nullable=False),
    Column("dedup_key", Text, nullable=False, unique=True),
    Column("acknowledged", Boolean, nullable=False, server_default="false"),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False),
)

monitoring_baseline = Table(
    "monitoring_baseline",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=False),
    Column("snapshot", Text, nullable=False),
    Column("saved_at", TIMESTAMP(timezone=True), nullable=False),
    CheckConstraint("id = 1", name="monitoring_baseline_singleton"),
)

# --- Stage 14: notification delivery state --------------------------------

alert_deliveries = Table(
    "alert_deliveries",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("alert_id", Integer, nullable=False),
    Column("channel", Text, nullable=False),
    Column("status", Text, nullable=False, server_default="PENDING"),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column("last_attempt_at", TIMESTAMP(timezone=True)),
    Column("sent_at", TIMESTAMP(timezone=True)),
    Column("error", Text),
    Column("retryable", Boolean, nullable=False, server_default="true"),
    Column("created_at", TIMESTAMP(timezone=True), nullable=False),
    UniqueConstraint("alert_id", "channel", name="idx_alert_deliveries_alert_channel"),
)

notification_test_sends = Table(
    "notification_test_sends",
    metadata,
    Column("provider", Text, primary_key=True),
    Column("last_success_at", TIMESTAMP(timezone=True), nullable=False),
)

# --- Stage 15: explanations cache -----------------------------------------

explanations = Table(
    "explanations",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("subject_type", Text, nullable=False),
    Column("subject_id", Integer, nullable=False),
    Column("explanation_type", Text, nullable=False),
    Column("payload", Text, nullable=False),
    Column("llm_provider", Text),
    Column("llm_model", Text),
    Column("llm_error", Text),
    Column("generated_at", TIMESTAMP(timezone=True), nullable=False),
    UniqueConstraint("subject_type", "subject_id", name="idx_explanations_subject"),
)

# --- Stage 16: trade review interpretation cache --------------------------

trade_reviews = Table(
    "trade_reviews",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("trade_id", Integer, nullable=False, unique=True),
    Column("interpretation", Text),
    Column("llm_provider", Text),
    Column("llm_model", Text),
    Column("llm_error", Text),
    Column("generated_at", TIMESTAMP(timezone=True), nullable=False),
)

# --- Stage 18: digest delivery dedup ---------------------------------------

digest_deliveries = Table(
    "digest_deliveries",
    metadata,
    Column("id", Integer, Identity(), primary_key=True),
    Column("digest_type", Text, nullable=False),
    Column("period_start", Date, nullable=False),
    Column("period_end", Date, nullable=False),
    Column("channel", Text, nullable=False),
    Column("sent_at", TIMESTAMP(timezone=True), nullable=False),
    UniqueConstraint("digest_type", "period_start", "period_end", "channel", name="idx_digest_deliveries_identity"),
)
