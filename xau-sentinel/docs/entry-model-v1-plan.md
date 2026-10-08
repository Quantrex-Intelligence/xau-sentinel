# Intraday ICT Entry Model V1: implementation plan

Manual decision support only. No orders, no SL/TP changes, no LLM in the decision path, no change to the
A+ rules or to V2's primitive definitions.

## What exists and will be reused

| Need | Existing primitive | Where |
|---|---|---|
| Structure per timeframe (BULLISH, BEARISH, PULLBACK, RANGING) | `analyze_structure` | `analysis/structure.py` |
| Liquidity sweeps (PDH/PDL, sessions, H1/H4 swings) | `detect_sweeps`, `compute_zones` | `analysis/liquidity.py`, `analysis/zones.py` |
| Sweep to MSS to displacement to retracement, with chronology and ownership | `build_sequences`, `sequence_wording` | `analysis/v2/sequence.py` |
| FVG creation, retest and fill | `find_fvgs` | `analysis/v2/fvg.py` |
| Key areas (supply and demand from H1, S/R, rejections, week-to-date) | `build_key_areas`, `classify_area` | `analysis/v2/key_areas.py`, `relations.py` |
| Stop buffer, R:R, expiry window | `rules.compute_stop_loss`, `compute_risk_reward`, `config.AI_STRATEGY_SWEEP_WINDOW_MINUTES` | `ai/strategy/rules.py`, `config.py` |
| Closed-candle filter | `closed_only` / `is_closed` | `analysis/structure.py` |

## What does not exist and is added (V1, deliberately narrow)

- **Timeframe roles.** D1 bias, H4 bias, H1 context, M15 formation, M5 confirmation, M1 precision.
  Data is already fetched for all six (`mt5/market_data.py`).
- **OTE.** A retracement observation only, never mandatory. The band is 0.62 to 0.79 of the impulse
  from the sweep extreme to the displacement extreme. It is an ICT convention, not validated.
- **Premium and discount.** Position of price in the H1 range between its latest confirmed swing
  high and low.
- **State machine.** Pure function over closed candles. Chronology is taken from the V2 sequence,
  not re-derived.
- **Checklist.** Each condition has a status, timeframe, evidence and reason.
- **Confidence.** Heuristic and uncalibrated. Each item is recorded with its weight and its
  correlation group. Groups have caps, so correlated evidence is not double-counted. It is never
  called a probability.
- **Contradictions.** Listed explicitly, each subtracting a fixed amount from confidence.

## Known gaps (stated, not hidden)

- No dedicated 1D supply and demand detector. Daily context is structure plus PDH/PDL.
- No weekly high and low as a separate primitive. Week-to-date is already a V2 key-area source.
- No M1 structure detector beyond the structure state of M1 candles.
- OTE and premium and discount are observations with no validated edge.
- Confidence weights are a research aid. They are not calibrated against outcomes.

## Validation plan

1. Unit tests on synthetic frames: state order, both chronologies, invalidation, expiry, FVG status,
   OTE arithmetic, premium and discount, LONG and SHORT symmetry, forming-bar exclusion, and a check
   that the module imports no LLM or order code.
2. Raw MT5 sample check: for chosen timestamps, verify each detector against the raw bars by hand.
3. Dataset: a reproducible per-setup record (context, sweep, MSS, FVG, OTE, confirmations, entry,
   stop, target, R:R, confidence, and later MFE and MAE). No edge is claimed.

## Implementation status and raw validation (added after the build)

Built: `analysis/entry_model/` (ote, confidence, model), `api/routes/entry_model.py` (`GET /api/entry-model`,
read-only), a card on the Market page, 22 backend tests, 4 frontend label tests.

Raw MT5 check: 3,800 as-of times, one per M15 bar, from 2026-08-07 (M1 history starts 2026-08-06, plus
a 24h warm-up). Closed candles only, the forming candle is never used.

| State | Count |
|---|---|
| NO_SETUP | 2,520 |
| HTF_ALIGNED | 583 |
| LIQUIDITY_SWEPT | 107 |
| EXPIRED | 676 |
| DISPLACEMENT_CONFIRMED | 10 |
| MSS_CONFIRMED | 3 |
| INVALIDATED | 1 |
| RETRACEMENT_WAITING, ENTRY_CONFIRMATION, ENTRY_READY | 0 |

Checked by hand against the raw M15 candles, with an independent calculation (not the model's code):
- 14 of 14 recorded sweeps satisfy the sweep rule (wick beyond the level by the buffer, close back through).
- 14 of 14 displacement candles pass the 1.5 x ATR body test used by the existing detector.

Not validated on raw data: the entry path. No sample reached an entry state in this window, so the FVG,
retracement, 5M and 1M confirmations, the entry/stop/target plan, and the OTE overlap are covered only by
tests on synthetic frames.

Findings from the raw run:
1. The 60-minute sweep window (reused from the A+ setting) expires most setups before they develop: 676
   samples are EXPIRED. A separate window for this model is a decision for you, not changed here.
2. In every displacement sample the displacement candle is the sweep candle itself. The existing rules allow
   this, so the ordering is effectively simultaneous, not MSS first.
3. Three defects were found and fixed during the run: an FVG was counted before its MSS and displacement
   (fixed: an FVG needs both, and must form at or after the later one), the next-condition text quoted
   raw state names, and the 1D/4H checklist items showed a pass or fail on a neutral reading.

Known limitations: the confidence weights are research settings, not calibrated; OTE and premium/discount
are observations with no validated edge; there is no dedicated daily supply and demand detector; the 1M
confirmation uses the M1 structure state, which is not bound to a bar.

## Hardening (after the first raw-MT5 run)

Four targeted changes, from the findings above, plus a dataset foundation for later research. No new entry
conditions, no threshold tuning, no confidence calibration.

1. **Its own sweep-validity window.** `config.ENTRY_MODEL_SWEEP_MAX_BARS` (default 8, on M15 — about 2
   hours), independent of `config.AI_STRATEGY_SWEEP_WINDOW_MINUTES` (A+ never reads this one, and this
   model never reads that one). Bar-count, not wall-clock, so it is reproducible from historical data.
   Sweep age is recorded in both bars and minutes on the output.
2. **Simultaneous sweep, structure shift and displacement are explicit.** `sequence.sweep_is_mss_bar` and
   `sequence.sweep_is_displacement_bar` are now on the output; `sequence` is now also attached to the
   INVALIDATED result (previously missing). All three orderings (MSS_FIRST, DISPLACEMENT_FIRST,
   SIMULTANEOUS) were already structurally supported by the underlying V2 sequence; this only surfaces it.
3. **1M confirmation is bar-tied.** Replaced the M1 structure-state reading with a specific closed M1 MSS
   bar, found by `analysis.v2.events.structure_transitions` (the same primitive already used for bar-tied
   M5/M15/H1/H4 events), at or after the 5M confirmation bar. The result is `m1_confirmation`: time, bar
   index, direction, event type, price, `closed_bar: true` — or `None` (checklist WAITING) when no such
   bar exists yet. Never read from the current forming bar.
4. **Outcome-dataset foundation.** `analysis/entry_model/dataset.py`: `build_setup_record()` reshapes an
   already-built `evaluate()` result (recomputes nothing) into one record per sweep, with identity,
   chronology, multi-timeframe context, confluence, trade plan, market conditions and an evidence log
   (the engine's own checklist). Every outcome field (`mfe`, `mae`, `outcome_r`, `target_hit`, `stop_hit`,
   ...) starts and stays `None`; only `outcome_status` is set, to a lifecycle label (`PENDING`,
   `EXPIRED_BEFORE_ENTRY`, `INVALIDATED_BEFORE_ENTRY`), never a trading result. `dedupe_setup_records()`
   keeps one record per `setup_id` (`direction:sweep_time`) across repeated evaluations of the same
   evolving sweep. `setup_record` is `None` before a sweep exists (NO_SETUP, HTF_ALIGNED).

### Raw-MT5 re-run: before vs after

Same raw M1/M5/M15/H1/H4/D1 history, replayed once per M15 bar. The sample count differs slightly (3,800 vs
3,900) because of a step-size difference between the two extraction runs; NO_SETUP and HTF_ALIGNED match
exactly, which is the expected sanity check (nothing upstream of the sweep changed).

| State | Before | After |
|---|---|---|
| NO_SETUP | 2,520 | 2,520 |
| HTF_ALIGNED | 583 | 583 |
| LIQUIDITY_SWEPT | 107 | 268 |
| EXPIRED | 676 | 436 |
| MSS_CONFIRMED | 3 | 22 |
| DISPLACEMENT_CONFIRMED | 10 | 53 |
| RETRACEMENT_WAITING | 0 | 16 |
| ENTRY_CONFIRMATION | 0 | 0 |
| ENTRY_READY | 0 | 0 |
| INVALIDATED | 1 | 2 |

The new window (8 M15 bars, ~2h) is wider than the old reused A+ one (effectively ~4 bars, 60 minutes), so
fewer sweeps expire and more survive long enough to reach MSS, displacement and retracement. This is a
reproducible consequence of the independent window, not a claim that 8 bars is correct.

Diagnostics (not a sample-count target, counted only): 8 simultaneous sweep+MSS+displacement bars, 4
MSS-first, 9 displacement-first; sweep bar == MSS bar in 12 cases, sweep bar == displacement bar in 27; 16
setups reached an FVG and a retracement; 5 reached 5M confirmation; 0 reached 1M confirmation (the entry
path is still outside this M1-limited window — the same honest gap as the first run). 797 setup records
were produced before dedupe, 81 distinct setups after.

### Validation

- 32 records (6 states) had their sweep age (bars and minutes), sweep extreme price, and sequence-ordering
  flags independently recomputed from the raw M15 window and matched exactly.
- 6 records (RETRACEMENT_WAITING, DISPLACEMENT_CONFIRMED, MSS_CONFIRMED) had `analysis.sequence.evaluate_sequence`
  run again from scratch (not the engine's own object) against the raw bars; `mss_ok`/`displacement_ok`
  matched the engine's checklist in every case, including a DISPLACEMENT_CONFIRMED case with `mss_ok=False`
  — a real displacement-before-MSS instance in the raw data.
  - All 797 setup records across the full run were scanned for a fabricated outcome field: zero found.
    `dedupe_setup_records` collapsed them to 81 distinct setups with no duplicate `setup_id`.
- Full regression: 1,722 backend tests (including 37 Entry Model tests, up from 22), 184 frontend tests,
  `tsc --noEmit`, ESLint, `next build`, and 6 E2E checklists (99/99 checks) all pass. A+ and V2 behavior
  unchanged; no trading execution, no SL/TP mutation, and no LLM dependency anywhere in `analysis/entry_model/`.

Known limitations, unchanged or extended: the 1M confirmation path is still unvalidated on raw data (0
samples reached it, same as the first run — M1 history is the limiting factor at ~2 months); confidence
weights remain uncalibrated; `ENTRY_MODEL_SWEEP_MAX_BARS=8` is a starting value for research, not validated
as optimal; the outcome-dataset fields are schema only, with no labeling process yet.

## Outcome labeling (the research stage the dataset was built for)

`analysis/entry_model/outcome.py::label_outcome(setup_record, path)` fills the outcome fields that
`build_setup_record()` leaves `None`: it replays the closed bars after the record's own time against the
record's own entry/stop/target, and reports `TARGET_HIT`/`STOP_HIT`/`STILL_OPEN`, MFE/MAE (price and R),
`outcome_r`, and time-to-target/invalidation. A setup with no plan yet (every state before
ENTRY_CONFIRMATION) is left exactly as it was — there is nothing to measure against. Both levels touched on
the same bar resolve to the stop, the conservative reading. It changes none of the setup's own facts.

12 tests (synthetic): target-first, stop-first, same-bar-resolves-to-stop, LONG/SHORT symmetry, MFE/MAE
tracked independently of the eventual outcome, still-open when price runs out, no fabrication when there is
no plan or no price history yet, determinism, and that the input record is never mutated.

Run against the 797 raw-MT5 setup records from this session's extraction: **0 were labelable**, because
none reached ENTRY_CONFIRMATION/ENTRY_READY (same gap reported above) — there is no entry plan on any of
them to measure against yet. The pipeline itself was proven end to end on a realistic record instead: a
synthetic `evaluate()` run reaching `ENTRY_READY` (via the same monkeypatch used in the model's own
`test_entry_ready_requires_a_real_bar_tied_1m_event_end_to_end`), its `setup_record`, and a synthetic
continuation path that hits the target — `label_outcome` returned the correct `TARGET_HIT`/`outcome_r`/MFE.
This confirms the code path is correct; it is not a claim that any real setup has been labeled, because
none exist yet in this data window.
