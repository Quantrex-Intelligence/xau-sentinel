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

## Database

SQLite at `data/xau_sentinel.db` (auto-created on first run), with four
tables: `trades`, `journal_context`, `market_events`, `alerts`. No raw market
data is stored — only journal entries and the discrete events/alerts the
analysis engine produces.

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

## Status

All five phases are implemented: MT5 connection + live dashboard, market
structure/zones/liquidity/regime, the setup detector with alerts, the
journal with automatic context capture, and journal analytics.
