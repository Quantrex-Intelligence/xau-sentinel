# XAU Sentinel

A personal XAUUSD market-analysis, setup-alert, and trading-journal app.

**What it does:** connects to MT5 → monitors XAUUSD → analyzes market structure →
detects your setup → alerts you → journals your trades.

**What it does not do:** place, close, or modify a single order. XAU Sentinel is
**read-only**. Every trading decision and every execution stays entirely manual,
in your own MT5 terminal.

## Quick start

```bash
cd xau-sentinel
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
streamlit run app.py
```

By default `.env` sets `MODE=mock`, so the app runs immediately with realistic
synthetic data — no MT5 required. Every mock value is clearly labeled
**🟡 MOCK DATA** and is never presented as if it were live.

## Running live against MT5

MT5 access requires:

1. Windows, with a MetaTrader 5 terminal installed and logged in.
2. The `MetaTrader5` pip package (already in `requirements.txt`, restricted to
   `sys_platform == "win32"` — it cannot install on Linux/macOS, which is why
   development and this container use `MODE=mock`).
3. In `.env`:
   ```
   MODE=live
   MT5_LOGIN=...
   MT5_PASSWORD=...
   MT5_SERVER=...
   TRADING_SYMBOL=XAUUSD   # or XAUUSD., XAUUSDm, GOLD, etc. — whatever your broker calls it
   ```

When connected, the header shows **🟢 MT5 CONNECTED** / **🟢 LIVE MT5**. If MT5 is
unreachable, unauthenticated, or the symbol isn't found, the app shows
**🔴 MT5 DISCONNECTED** and a clear error instead of crashing — the rest of the UI
(including the Journal) stays usable.

## Project structure

```
xau-sentinel/
├── app.py                 # entry point: wires data → analysis → UI, alert transitions
├── config.py               # env-driven configuration (mode, symbol, thresholds)
├── mt5/
│   ├── connection.py        # read-only MT5 connect/verify/disconnect
│   └── market_data.py       # candles + tick data, live or mock
├── analysis/
│   ├── structure.py         # swing points, HH/HL/LH/LL, BOS/MSS, ATR, displacement
│   ├── zones.py              # PDH/PDL, session highs/lows, swing levels, VWAP
│   ├── liquidity.py          # sweep + equal-highs/lows detection
│   ├── regime.py              # TRENDING/RANGING/PULLBACK/BREAKOUT/volatility labels
│   └── setup.py                # NO SETUP → DEVELOPING → VALID → INVALIDATED state machine
├── journal/
│   ├── database.py         # SQLite schema (trades, journal_context, market_events, alerts)
│   └── trades.py             # trade CRUD, context capture, analytics, event/alert logging
└── ui/
    ├── dashboard.py         # header, chart, market/setup/zones/risk/events panels
    ├── chart.py               # Plotly candlestick + zone overlay
    └── journal.py             # trade entry form, table, detail view, analytics
```

## How the analysis works (and its limits)

Everything under `analysis/` is **deterministic price-action logic**, not a
predictive model:

- **Structure** (`structure.py`): swing highs/lows over a configurable lookback,
  labeled HH/HL/LH/LL, producing one of `BULLISH`, `BEARISH`, `RANGING`,
  `PULLBACK` per timeframe (H4/H1/M15/M5). It also flags BOS (trend
  continuation past a swing point) and MSS (a close through structure against
  the prevailing trend), plus ATR-relative "displacement" candles.
- **Zones** (`zones.py`): previous/current day high-low, Asian/London session
  high-low, H1/H4 swing levels, and session VWAP.
- **Liquidity** (`liquidity.py`): a "sweep" requires price to trade beyond a
  known level by a configurable buffer *and* close back on the other side —
  not every wick that grazes a level.
- **Regime** (`regime.py`): H1 structure is the primary signal; ATR (relative
  to its own recent baseline) only adds the volatility-flavored labels.
- **Setup** (`setup.py`): a state machine combining H1/M15 direction, zone
  proximity, a liquidity sweep, an M5 MSS, displacement, and a retracement.

None of this predicts future price or guarantees a profitable trade — it only
tells you when a configurable checklist of price-action conditions has lined
up, using thresholds you can tune in `.env`/`config.py`
(`SWING_LOOKBACK`, `DISPLACEMENT_ATR_MULT`, `LIQUIDITY_SWEEP_BUFFER_PIPS`,
`RETRACEMENT_MIN_PCT`/`MAX_PCT`, ATR volatility multipliers, session windows).
All candle timestamps are handled in UTC internally; `SESSION_TIMEZONE` only
affects how sessions are labeled for display.

## Alerts

The dashboard shows a banner the moment the setup state changes — developing,
valid (with entry zone / SL / TP / RR), or invalidated (with the reason) — and
every transition is written to the `alerts` table. There's no push
notification in V1; the alert lives in the app itself (visible banner +
"Recent Events" panel) so you can keep the dashboard open while you work.

## Trading journal

Create a trade manually (direction, entry, SL, TP, setup, notes, screenshot).
**Nothing the system already knows has to be re-typed** — H4/H1/M15/M5 bias,
regime, session, the most recent liquidity sweep, MSS, and displacement are
captured automatically at the moment you log the trade and stored alongside
it (`journal_context` table). Close a trade later to add exit price, result,
P/L, R multiple, duration, exit reason, and any mistake/notes.

Analytics (win rate, total R, average R, profit factor) are computed only
over closed trades in the current filter (session / setup / direction /
regime), and the UI always shows the sample size — with a warning under 10
trades — rather than drawing conclusions from a handful of results.

## AI Assistant (Stage 3)

A read-only analyst and explainer layer over the deterministic engine above
— available on the Next.js/FastAPI UI (`api/` + `frontend/`) at
`/assistant`, or directly via `POST /api/ai/chat`. It answers questions like
"What is the current market structure?", "How much FundedNext daily loss do
I have remaining?", or "Explain trade #12 using its captured entry context"
— but it **never places, modifies, or recommends executing a trade**; a
deterministic filter (`ai/prompts.py::contains_actionable_directive`) also
catches and replaces any directive-style answer (e.g. "BUY NOW") before it
reaches the user, as a second layer behind the system prompt.

The LLM is never a source of truth: `ai/context.py` builds a plain-text
context block from the same engine calls the rest of the app already uses
(`api/snapshot.py` for market/setup, `risk/fundednext.py` for account risk,
`journal/trades.py` for journal history), and every answer's "Context used"
panel — and each source's FACT/CALCULATION/INTERPRETATION/UNKNOWN category —
comes from that object directly, never parsed back out of the model's prose.
A missing/unavailable source is always labeled as such, never fabricated.
Journal history is only included when explicitly requested (via
`context_scope`), to avoid sending more than a question needs.

**Provider**: set in `.env` — `AI_PROVIDER=anthropic` (needs `AI_API_KEY`
and `AI_MODEL`) or `AI_PROVIDER=mock` (offline, deterministic, no key; used
by the test suite and for local development). An unconfigured provider
surfaces as a clear message in the UI (`GET /api/ai/config`), never a crash.
See `ai/providers/` for the provider abstraction — adding another backend
means adding one file there, nothing else changes.

Conversation history persists per `conversation_id` in its own `ai_messages`
SQLite table (added via its own migration, same pattern as
`risk/fundednext_journal.py` — the frozen Stage 1 schema is never touched).

## A+ Strategy Evaluation (Stage 4)

A second, stricter evaluation layered on top of the Stage 1 setup detector
— `GET /api/strategy/aplus`, shown on the Next.js Setups page next to (not
replacing) the frozen `SetupPanel`. It encodes a locked, user-specified
strategy (see `ai/strategy/rules.py` for every threshold and its source)
as explicit criteria: H1 bias, a qualifying liquidity sweep within a
60-minute window, M5 MSS, displacement, retracement, a stop-loss beyond
the swept level, a minimum 1:3 reward:risk against the nearest qualifying
opposing liquidity level, and a FundedNext risk gate (SAFE and daily loss
used below 50%). A candidate is invalidated by an opposing M5 structure
break, H1 bias flipping to the hard opposite state, or the sweep aging
past the window — all checked before scoring the rest.

`ai/strategy/evaluator.py` computes the rating (`A+` / `DEVELOPING` /
`INVALID`) entirely from these deterministic checks; an LLM call (via the
same provider abstraction as Stage 3) only adds a plain-language
explanation afterward and can never change the rating, even if it ignores
its own instructions — a provider failure, missing config, or an
attempted directive-style answer all leave the deterministic result
untouched. A+ alerts are deduplicated by (direction, sweep timestamp) in
the existing `alerts` table, so re-polling the same candidate never spams
a second alert.

## Database

SQLite at `data/xau_sentinel.db` (auto-created on first run), with tables
for `trades`, `journal_context`, `market_events`, `alerts`,
`fundednext_context` (an immutable per-trade FundedNext snapshot), and
`ai_messages` (AI conversation history). No raw market data is stored —
only journal entries and the discrete events/alerts/messages these layers
produce.

## Safety

- Read-only: the app never calls an order-placing, closing, or modifying MT5
  function. It only reads prices, candles, and account/symbol info.
- No look-ahead: displacement is measured against ATR computed through the
  *prior* candle, never the candle it's judging.
- No hard-coded credentials — everything sensitive comes from `.env` (see
  `.env.example`), which is gitignored.
- MT5 disconnects, missing symbols, and package-unavailable (e.g. running on
  Linux/macOS) all degrade to a visible `🔴 MT5 DISCONNECTED` state rather
  than crashing the app.

## Safety (AI Assistant)

- The AI Assistant is read-only in the same sense as the rest of the app:
  it cannot place, close, or modify an order, and never claims to.
- Never hardcoded credentials — `AI_API_KEY` comes from the environment and
  is never returned by any API response (`GET /api/ai/config` reports
  `configured: true/false`, never the key itself).
- A missing provider/key degrades to a clear, visible configuration message
  (both API and UI), never a crash.
- Context sent to the LLM traces to existing engine calls only — nothing is
  invented for the assistant's benefit, and journal history is opt-in per
  request to avoid over-sharing.

## Safety (A+ Strategy Evaluation)

- Read-only like everything else here: the evaluator only ever returns a
  rating and evidence — it never places, modifies, or closes an order, and
  the LLM step it calls has no access to any order-placing function.
- The deterministic rating is computed and finalized before the LLM is ever
  called; the LLM can only attach an explanation, never change `rating`,
  `criteria`, or `missing_conditions` — enforced structurally (the LLM step
  receives an already-built result object and only sets its own
  `llm_explanation`/`llm_error` fields).
- No invented strategy rules: every threshold in `ai/strategy/rules.py`
  traces to an explicit, user-provided specification, not a default assumed
  by the model.

## Status

All five original phases are implemented: MT5 connection + live dashboard,
market structure/zones/liquidity/regime, the setup detector with alerts,
the journal with automatic context capture, and journal analytics. Stage 2
(FundedNext risk monitor), Stage 3 (AI Assistant), and Stage 4 (A+ Strategy
Evaluation) are also implemented, on top of a FastAPI (`api/`) + Next.js
(`frontend/`) layer that now sits alongside the original Streamlit UI
(`app.py`, `ui/`) during the migration.
