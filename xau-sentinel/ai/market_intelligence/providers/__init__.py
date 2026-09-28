"""Provider interfaces + factories for the Market Intelligence layer — one
ABC and one config-keyed factory per category (macro, cross-asset, events,
news), mirroring ai/providers/__init__.py and ai/knowledge/embeddings.py's
exact pattern. Only a mock backend exists today; a real provider plugs into
the same ABC later with no change to ai/market_intelligence/context.py, the
tools, or the assistant."""
