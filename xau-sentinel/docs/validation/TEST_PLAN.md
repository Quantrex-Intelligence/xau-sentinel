# XAU Sentinel — Validation & Testing Phase — Test Plan

Feature development is frozen for this phase. Goal: exercise the existing system (Stages 1-18) as a
real read-only trading decision-support tool, find genuine defects, and produce a prioritized issue log.
No new features, pages, providers, or strategy rules are added here.

## Environment for this pass

- `MODE=mock`, `AI_PROVIDER=mock` — no live MT5 connection or real LLM is configured in this environment.
- `NOTIFICATION_PROVIDER=telegram`, `TELEGRAM_ENABLED=true` — a real bot is configured (set up earlier this
  engagement); used only for the one controlled test in section 12, via the existing, already-vetted
  `/api/notifications/telegram/test` endpoint (a fixed, non-trading message). No other real sends.
- `MONITORING_ENABLED`/`DIGEST_ENABLED` are left at their shipped defaults (monitoring on, digest off) —
  automatic scheduling is not force-enabled for this pass, per the spec's own instruction.

## Methodology

1. **Automated regression baseline** — the existing suite (1015 backend tests, 133 frontend tests, 14 E2E
   checklists as of Stage 18) is re-run and its result recorded as the starting baseline in
   `TEST_RESULTS.md`. This suite already covers most unit-level correctness; this validation phase looks
   for what it *doesn't* catch — integration-level, cross-stage, and judgment-level issues.
2. **Code-level correctness review** — three focused passes over the implementation (not the tests) looking
   for lookahead bias, incorrect state transitions, missing edge-case handling, and safety-filter gaps:
   - Deterministic core: `analysis/`, `ai/strategy/`, `mt5/` (market data, structure, setup state machine,
     A+ evaluation).
   - Risk/Journal/Monitoring/Telegram: `risk/`, `journal/`, `ai/monitoring/`, `ai/notifications/`.
   - AI/RAG/Memory/Similarity/Market Intelligence/downstream analytics: `ai/knowledge/`, `ai/memory/`,
     `ai/similarity/`, `ai/market_intelligence/`, `ai/tools/`, `ai/prompts.py`, `ai/explanations/`,
     `ai/trade_review/`, `ai/strategy_analytics/`, `ai/digest/`.
3. **Live functional testing** — both dev servers started in mock mode; each subsystem exercised through
   its real API/UI, including a manual 20+ question AI Assistant test set (section 8) run against the real
   assistant endpoint with the mock LLM.
4. **Strategy Analytics / Trade Review / Digest edge cases** — 0 trades, 1-4 trades, 5+ trades, and missing
   historical fields, exercised against the real endpoints with seeded journal data.
5. **Real-World Shadow Testing (section 17) — scoped limitation.** This environment has no live MT5
   connection (`MODE=mock`, no `MT5_LOGIN`/`MT5_SERVER`) and no real LLM (`AI_PROVIDER=mock`), so genuine
   real-market shadow observations (real timestamp vs. real market outcome) cannot be fabricated here —
   doing so would violate the spec's own "don't overfit/fabricate" instruction. This pass instead delivers:
   (a) a ready-to-use shadow-log template and process, and (b) one dry run of the *mechanism* against mock
   data to confirm the logging/observation workflow itself works, explicitly labeled as a mechanism check,
   not real-world evidence. Actual shadow testing requires the user to run XAU Sentinel against a live MT5
   connection over real trading sessions — noted as a follow-up in the final report, not simulated here.

## Deliverables

- `docs/validation/TEST_PLAN.md` (this file)
- `docs/validation/ISSUE_LOG.md` — every discovered issue, ID/severity/repro/evidence
- `docs/validation/TEST_RESULTS.md` — pass/fail counts and notes per section (3-16)
- A final report in chat, in the spec's own 15-item format

No code fixes are made during this phase except where a confirmed defect actively blocks testing itself
(the spec's own stated exception) — and any such fix is called out explicitly, not silently folded in.
