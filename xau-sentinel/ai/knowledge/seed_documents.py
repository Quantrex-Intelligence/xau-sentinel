"""Seed knowledge documents — reference material only, never live facts.
Every document's content is restated from the project's own existing
docstrings/README (cited in each entry's `source`), not invented. Seeded
once at API startup via seed_if_empty(), which only acts when the knowledge
base is completely empty — it never overwrites documents someone has since
added or re-versioned (use ai.knowledge.store.add_document directly, which
handles versioning, for that).

"user_notes" is intentionally left with zero seed documents — it's the
category reserved for the user's own future trading notes/playbook (see
Stage 5 spec), and seeding placeholder content into it would misrepresent
it as real user input.
"""
from ai.knowledge import store

SEED_DOCUMENTS = [
    {
        "source": "ai/strategy/rules.py",
        "category": "strategy_rules",
        "version": "1.0",
        "title": "Locked A+ Strategy Rules",
        "content": """
The A+ strategy evaluator (Stage 4) rates one candidate setup at a time against an explicit,
locked specification — every threshold below is configurable in config.py but never invented.

Candidate selection: the most recent qualifying liquidity sweep anchors the candidate. Only
Stage 1's own qualifying sweep types count (Previous Day High/Low, session High/Low, H1 swing,
H4 swing) — equal highs/lows are supporting evidence only, never the anchor. A sweep_low anchors
a BUY candidate; a sweep_high anchors a SELL candidate.

Mandatory criteria, all required for an A+ rating:
1. H1 bias must support the candidate direction: BULLISH or PULLBACK (with no opposing MSS) for
   BUY; BEARISH or PULLBACK (with no opposing MSS) for SELL.
2. The qualifying sweep must be recent — within AI_STRATEGY_SWEEP_WINDOW_MINUTES (default 60
   minutes) of the current M5 snapshot. Older sweeps expire.
3. M5 must show an actual confirmed structure shift (MSS) in the candidate's direction — not
   merely an already-established M5 trend. This is the same strict MSS definition Stage 1 itself
   uses (an established trend is not the same claim as a shift just happened).
4. Displacement must be confirmed on the M5 candle in the candidate's direction.
5. Stop-loss sits beyond the swept level by AI_STRATEGY_SL_BUFFER (default $0.30) — below the
   level for a BUY, above it for a SELL.
6. The target is the nearest qualifying OPPOSING liquidity level beyond entry (same qualifying
   zone list as item 1's sweep types). If no such level exists, there is no target and no rating
   can reach A+ — a fixed-multiple or fabricated target is never substituted.
7. Reward:risk, computed from the actual entry/stop-loss/target, must be at least
   AI_STRATEGY_MIN_RR (default 1:3).
8. FundedNext gate: the account's current risk status must be SAFE (not WARNING, CRITICAL,
   BREACHED, or UNKNOWN), and today's daily-loss-used percentage must be below
   AI_STRATEGY_FUNDEDNEXT_MAX_DAILY_LOSS_USED_PCT (default 50%).

Invalidation (cancels a candidate outright, checked before scoring anything else):
- An opposing M5 structure break (M5 flips hard against the candidate direction).
- H1 bias flipping to the hard opposite state (not just becoming RANGING — only the opposite
  hard state counts as a flip).
- The qualifying sweep aging past the recency window.

Rating: A+ means every mandatory criterion passed and nothing invalidated the candidate.
DEVELOPING means some criteria have passed and nothing has failed or invalidated it yet.
INVALID means a mandatory criterion failed, or the candidate was invalidated.

The rating is computed entirely by deterministic rules before any LLM is involved. An LLM may
attach a plain-language explanation afterward, but it can never change the rating, the criteria,
or the missing-conditions list — a provider failure, missing configuration, or even a
directive-style answer from the model all leave the deterministic result untouched.
""".strip(),
    },
    {
        "source": "risk/rules.py",
        "category": "fundednext_rules",
        "version": "1.0",
        "title": "FundedNext Risk Rules (Stellar CFD accounts)",
        "content": """
XAU Sentinel's FundedNext risk monitor implements the officially researched rules for two Stellar
CFD account types (not guessed — sourced from fundednext.com/general-rules and
help.fundednext.com):

Stellar 2-Step: 5% daily loss limit, 10% static maximum loss, 8% Phase 1 / 5% Phase 2 profit
target, 5 minimum trading days during the challenge phase.

Stellar Lite: 4% daily loss limit, 8% static maximum loss, 8% Phase 1 / 4% Phase 2 profit target,
5 minimum trading days during the challenge phase.

Key mechanics that apply to both:
- Both the daily loss limit and the maximum loss limit are measured against EQUITY (including
  open floating profit/loss) — a breach can occur intraday on a losing position that is still
  open, before it is ever closed.
- The maximum loss limit is a STATIC floor computed from the account's INITIAL balance
  (floor = initial_balance * (1 - max_loss_pct)). It never moves down; every dollar of profit
  only increases the buffer above it. It does not trail upward like a trailing-drawdown account
  type would.
- The daily loss limit resets at 00:00 "server time." FundedNext describes this only as GMT+2 in
  winter / GMT+3 during EU daylight saving (an EET/EEST pattern) without publishing an exact IANA
  timezone name — XAU Sentinel makes this configurable (FUNDEDNEXT_SERVER_TIMEZONE) rather than
  hardcoding a fixed offset.
- CFD Stellar accounts (2-Step, 1-Step, Lite, Instant) have NO consistency rule by default in
  either phase. A 40% single-day-profit-share cap exists only as part of the optional, separately
  purchased "On-Demand Rewards" add-on — XAU Sentinel models this as an explicit opt-in toggle,
  never assumed active.
- Funded-phase minimum-trading-days and payout-cadence rules depend on which payout option (21-day,
  3-day, or on-demand) was selected at checkout — that choice isn't exposed through any data source
  this app can read, so it is intentionally left untracked for the funded phase rather than guessed.

Safety levels — SAFE, WARNING, CRITICAL, BREACHED, UNKNOWN — are computed from how much of the
daily/maximum loss allowance is currently used, against two configurable thresholds
(FUNDEDNEXT_WARNING_THRESHOLD_PCT default 50%, FUNDEDNEXT_CRITICAL_THRESHOLD_PCT default 80%).
BREACHED means the remaining allowance has reached zero or below. UNKNOWN means the account data
itself is unavailable (e.g. MT5 disconnected) — never fabricated as SAFE or any other level.
""".strip(),
    },
    {
        "source": "analysis/structure.py, analysis/liquidity.py, analysis/regime.py, analysis/setup.py",
        "category": "methodology",
        "version": "1.0",
        "title": "Trading Methodology & Definitions",
        "content": """
XAU Sentinel's market analysis is deterministic price-action logic, not a predictive model. These
are the definitions the engine itself uses:

Swing points / HH-HL-LH-LL: a bar is a swing high or low if it is the strict extreme within a
configurable lookback (default 3 bars) on both sides. Once labeled, a swing high is HH (higher
high) if above the previous swing high, else LH (lower high); a swing low is HL (higher low) if
above the previous swing low, else LL (lower low). Structure state per timeframe is BULLISH
(latest HH + HL), BEARISH (latest LH + LL), RANGING (no clean HH/HL or LH/LL sequence), or
PULLBACK (a close breaks through the trend's own last swing without yet confirming the opposite
direction).

BOS (Break of Structure): the current close trades beyond the prior (not just the most recent)
labeled swing high/low in the direction of the established trend — a continuation signal, not a
reversal signal.

MSS (Market Structure Shift): a close through structure AGAINST the prevailing trend — the actual
moment a trend's own last swing gets violated. Critically, MSS means an actual shift just
happened, not merely that the timeframe already has an established trend in a given direction —
these are different claims, and the strategy rules above rely on this distinction precisely.

Liquidity sweep: price must trade beyond a known level (Previous Day High/Low, session High/Low,
H1/H4 swing level) by a configurable buffer AND close back on the other side. A wick that merely
grazes a level, or a breakout that closes through and keeps going, does not count as a sweep.

Equal highs/lows: swing points of the same kind within a small price tolerance of each other —
a liquidity pool concept, tracked separately from sweeps and never used as a sweep's anchor.

Displacement: an ATR-relative outsized candle body in a given direction, measured against ATR
computed through the PRIOR candle only — never against a baseline that includes the candle being
judged, avoiding look-ahead bias.

Regime: TRENDING UP / TRENDING DOWN / RANGING / BREAKOUT / PULLBACK / HIGH VOLATILITY / LOW
VOLATILITY. H1 structure is the primary signal; ATR (relative to its own recent baseline) only
adds the volatility-flavored labels — regime never overrides or contradicts what H1 structure
itself reports.

Setup state machine: NO SETUP -> DEVELOPING -> VALID -> INVALIDATED, combining H1/M15 direction,
zone proximity, a liquidity sweep, an M5 MSS, displacement, and a retracement into a checklist.
A liquidity sweep alone, or an MSS alone, is never sufficient for VALID — every checklist item is
required. INVALIDATED triggers when a liquidity sweep has already been confirmed and M5 structure
then breaks firmly against the setup's direction.

None of this predicts future price or guarantees a profitable trade — it only reports when a
configurable checklist of already-happened price-action conditions has lined up.
""".strip(),
    },
    {
        "source": "README.md",
        "category": "system_docs",
        "version": "1.0",
        "title": "XAU Sentinel — System Overview",
        "content": """
XAU Sentinel is a personal, read-only XAUUSD market-analysis, setup-alert, FundedNext risk
monitoring, and trading-journal application. It connects to MT5, monitors price, analyzes market
structure, detects a configurable setup, alerts on state changes, tracks FundedNext account risk,
and journals trades with automatically captured context.

What it does not do: place, close, or modify a single order. Every trading decision and every
execution stays entirely manual, in the user's own MT5 terminal. This applies equally to the AI
Assistant and the A+ Strategy Evaluator — both are read-only analysts/explainers, never an
execution path.

Architecture: a Python deterministic engine (analysis/, journal/, mt5/, risk/) is the source of
truth for every fact. A FastAPI layer (api/) exposes it as a thin, non-duplicating read-only API.
A Next.js/TypeScript frontend (frontend/) is the primary UI, alongside a legacy Streamlit UI
(app.py, ui/) kept running during the migration. An AI layer (ai/) — the Stage 3 Assistant, the
Stage 4 A+ Strategy Evaluator, and this Stage 5 knowledge/RAG layer — sits on top of all of it,
strictly as an analyst/explainer, never a second source of facts.

Modes: MODE=mock runs the entire app on realistic deterministic synthetic data, no MT5 required —
always clearly labeled MOCK, never presented as live. MODE=live connects to a real MT5 terminal
(Windows only); any disconnection, missing symbol, or unavailable package degrades to a visible
disconnected state rather than crashing.

FundedNext account type and phase (Stellar 2-Step or Stellar Lite; Challenge or Funded) are
user-selectable at runtime via the FundedNext page, not fixed at startup — every trade's captured
FundedNext context reflects whichever account type/phase was selected at the moment that specific
trade was created, and that snapshot never changes afterward even if the selection changes later.
""".strip(),
    },
]


def seed_if_empty() -> int:
    """Seeds SEED_DOCUMENTS only when the knowledge base has zero documents
    — never overwrites or re-versions anything that already exists (a
    developer's or a later session's own additions are left alone). Returns
    the number of documents seeded (0 if the base already had content)."""
    if store.count_documents(active_only=False) > 0:
        return 0
    for doc in SEED_DOCUMENTS:
        store.add_document(doc["source"], doc["category"], doc["version"], doc["title"], doc["content"])
    return len(SEED_DOCUMENTS)
