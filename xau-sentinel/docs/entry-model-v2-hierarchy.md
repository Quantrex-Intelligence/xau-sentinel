# Top-Down Multi-Timeframe Entry Model: design

Replaces Entry Model V1's rigid state machine (`analysis/entry_model/model.py`, kept in the repo,
unimported from `analysis/entry_model/__init__.py`, for historical reference and its own tests —
`tests/test_entry_model.py`, `tests/test_entry_model_outcome.py`). The active implementation behind
`analysis.entry_model.evaluate` is now `analysis/entry_model/hierarchy.py` and its five layer
modules. Manual decision support only: deterministic, no LLM in the decision path, no order
placement, no SL/TP mutation — same safety boundary as V1.

## Why V1 was replaced

V1 required a sweep, then a fresh M5 structure shift at the *exact* moment price retraced into the
M15 FVG. The raw-MT5 research (`docs/entry-model-v1-research.md`) found that conjunction never
fired once in 350 tracked sweeps over 17 months. A dedicated M5-resolution audit
(`docs/entry-model-v1-m5-confirmation-audit.md`) then ruled out sampling resolution as the cause:
replaying 11 cases at every closed M5 bar still found 0/11 confirmations, and in 3 of them the M5
structure shift *did* happen — just before the retracement, not after it, because the model's own
`retested_at or formed_at` reference time moves forward once the real retest happens, retroactively
disqualifying an earlier-satisfying shift. That is a **finding about the rigid timing requirement
V1 used, not evidence that 5M confirmation itself has no value** — this redesign removes the
timing requirement, not the concept.

## Architecture

```text
1D + 4H -> Higher-timeframe location & context   ("Where is price, and is this important?")
1H      -> Intraday bias                          ("What is the intraday direction?")
15M     -> Setup formation                        ("Is a meaningful setup forming?")
5M      -> Entry confirmation                      ("Is there lower-timeframe confirmation?")
1M      -> Precision entry (optional)              ("Can the entry be refined more precisely?")
-> Entry candidate -> risk / invalidation / target
```

Each rung is its own module and answers one question; none requires the ones below it to exist
yet (HTF location never requires a setup; 1H bias never requires a sweep or FVG).

| Module | Question | Reused primitives (nothing re-detected) |
|---|---|---|
| `htf.py` | Where is price, is it important? | `analysis.v2.key_areas.build_key_areas`/`relationship` (supply/demand, S/R, PDH/PDL, session levels, swings), `analysis.structure.find_swing_points` (D1 POIs, the one thing key_areas doesn't cover) |
| `intraday.py` | What is the 1H direction? | `analysis.structure.analyze_structure` |
| `setup_15m.py` | Is a setup forming? | `common.gather_directional_evidence` (below) |
| `confirmation_5m.py` | Is there LTF confirmation? | `common.gather_directional_evidence` (the same function, same timeframe-generic logic, called on M5) |
| `precision_1m.py` | Can the entry be refined? | `analysis.v2.events.structure_transitions` (bar-tied M1 MSS/BOS, the same primitive V1's own hardening stage used) |
| `hierarchy.py` | Orchestration | `ai.strategy.rules` (stop/target/R:R — unmodified), `analysis.v2.sequence.build_sequences` (sweep invalidation, when a sweep anchors the setup) |

`common.gather_directional_evidence(df, zones, atr_series, price, key_areas, timeframe)` is the one
place liquidity sweeps, MSS/BOS, displacement, FVG and key-area reaction are read as *independent*
evidence — used identically by the 15M and 5M layers, so there is exactly one implementation to
reason about, not one copy per timeframe.

## Evidence, not a chain

V1 required `sweep -> MSS -> displacement -> FVG -> retracement` in that literal order. Every
condition here is independent evidence; a setup can be built from any real combination that
occurred (sweep+MSS+displacement+FVG, or MSS+displacement+retracement+FVG, or otherwise). Only the
**single most recent** instance of each evidence kind counts (the latest sweep, the latest
non-filled FVG, the nearest key area, the current `last_mss`-or-`last_bos` reading) — this was a
deliberate fix during validation: counting every sweep or FVG within a lookback window made
`CONFLICTED` fire on ~99% of real samples, because a ranging market routinely has *some* evidence
on both sides within any window. Only the current, most relevant fact on each side is counted.

## Direction and conflict

Direction is resolved by the **majority of independent evidence categories**, not by vetoing on any
single opposing data point (that also fires far too often in real price action — see above). A
genuine tie, or a majority that contradicts an already-established 1H bias, reports `CONFLICTED`
rather than forcing a side — the explicit anti-override rule from the hierarchy (1D/4H -> 1H -> 15M
-> 5M -> 1M; a lower timeframe's evidence can outvote a higher timeframe's *absence* of a bias, but
never outvote an opposing established one).

1M precision is never consulted until 5M confirmation has already reached at least `DEVELOPING` on
its own (`hierarchy.py` does not even call `evaluate_precision` before that) — a strong 1M pattern
alone can never create or upgrade a candidate.

## State machine

```text
NO_CONTEXT -> HTF_LOCATION_IDENTIFIED -> HTF_CONTEXT_ALIGNED -> INTRADAY_BIAS_ESTABLISHED
  -> SETUP_DEVELOPING -> SETUP_CONFIRMED -> ENTRY_CONFIRMATION_DEVELOPING -> ENTRY_CONFIRMED
  -> [PRECISION_AVAILABLE] -> ENTRY_READY
(CONFLICTED | INVALIDATED | EXPIRED can occur at any point and override the ladder)
```

`state` reflects the evidence actually available, not mechanical progression — e.g.
`HTF_CONTEXT_ALIGNED` with a `NEUTRAL` 1H bias stays at `HTF_CONTEXT_ALIGNED`, never advances.

**Invalidation** reuses existing structural facts only: a sweep-anchored setup's own
`build_sequences(...).invalidated` (exactly V1's mechanism), an opposing 1H `last_mss` superseding
the established bias, or price closing decisively through the identified HTF area
(`atr_normalized_distance`). **Expiry** only applies when a sweep anchors the setup (now optional
evidence, not required), using the same `config.ENTRY_MODEL_SWEEP_MAX_BARS` V1 used — a setup built
from MSS+displacement+FVG with no sweep has no existing deterministic expiry rule to reuse, and none
was invented (per the no-new-detectors constraint); this is a stated limitation, not an oversight.

## Confidence

Additive to V1's `analysis/entry_model/confidence.py` (new `v2_*` names and groups; V1's own
`WEIGHTS`/`GROUP_CAP` entries are untouched, so V1's tests and behavior never change). Still
`CONFIDENCE_TYPE = "HEURISTIC"`, still uncalibrated, still never a probability.

## Validation (real XAUUSD MT5 history, 400 samples, ~17-month window)

| State | Count |
|---|---|
| CONFLICTED | 182 |
| HTF_LOCATION_IDENTIFIED | 119 |
| EXPIRED | 59 |
| HTF_CONTEXT_ALIGNED | 23 |
| INVALIDATED | 11 |
| ENTRY_READY | 4 |
| ENTRY_CONFIRMED | 1 |
| ENTRY_CONFIRMATION_DEVELOPING | 1 |

0 exceptions across all 400 samples. Reaching `ENTRY_READY`/`ENTRY_CONFIRMED` at all is a material
difference from V1, which reached neither once in 17 months at any tested sweep window. `CONFLICTED`
at ~45% is a real, evidence-based result (ties or bias-opposing majorities), not the ~99%-degenerate
rate seen before the evidence-scoping fixes above — still worth narrowing further in a future pass,
but no longer a bug.

## Known limitations

- No expiry rule exists for a setup that formed without a sweep (see Invalidation above).
- `CONFLICTED` at ~45% of samples has not been independently validated against real outcomes —
  it is a descriptive rate from this validation run, not a calibrated figure.
- Confidence weights for the new evidence categories are, like V1's, research settings — not fitted
  to outcomes.
- OTE here is computed from the latest swing-to-swing leg (no sweep required to define the
  impulse), a deliberate change from V1's sweep-anchored impulse; it has not been separately
  re-validated against raw data under this new definition.
- `htf.py`'s "major D1 POIs" are D1 swing highs/lows only — there is still no dedicated daily
  supply/demand detector (the same gap V1's plan doc noted for H1/H4).
