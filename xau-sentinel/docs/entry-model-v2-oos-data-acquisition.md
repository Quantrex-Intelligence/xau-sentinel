# Entry Model V2 OOS: fresh MT5 data acquisition

Infrastructure/data task. No strategy logic touched, no OOS hypothesis study run. This documents
the MT5 integration audit, the new fresh-data acquisition pipeline, and what it found when pointed
at the actually-connected live MT5 terminal on this machine.

## 1. MT5 integration audit (read-only, no changes made)

- **Initialization**: `mt5/connection.py::connect()` calls `MetaTrader5.initialize()`, then
  `mt5.login()` only if `MT5_LOGIN`/`MT5_PASSWORD`/`MT5_SERVER` are all set. If they are blank (as in
  this machine's `.env`), `initialize()` alone is enough — it attaches to whatever MT5 terminal
  installation Python can find (and will auto-launch the terminal process if it isn't already
  running, observed directly: `connect()` returned `True` and a `terminal64.exe` process appeared
  that was not running moments before).
- **Credentials/config**: `config.py` reads `MT5_LOGIN`, `MT5_PASSWORD`, `MT5_SERVER`,
  `TRADING_SYMBOL` (default `XAUUSD`, this `.env` overrides to `XAUUSDm`) from environment. Never
  logged; `connection.py` only ever surfaces `mt5.last_error()`'s own text.
- **Broker/server/symbol resolution**: once connected, `_ensure_symbol()` calls
  `mt5.symbol_info(TRADING_SYMBOL)` and `symbol_select(..., True)` if not already visible.
  `connection.symbol_ready()` reports whether that succeeded, independent of connection success
  itself — `market_data._no_data_error()` surfaces the real cause (symbol not available) rather than
  a generic "no data" message.
- **Timestamp normalization**: `mt5/timeutil.py` is the one explicit MT5-server-time → UTC boundary
  in the codebase (its own docstring flags this as a previously-fixed bug class, VAL-003: MT5's raw
  epoch values are the broker server's own wall-clock reading, not true UTC, so naive
  `datetime.utcfromtimestamp()` silently shifts every timestamp by the server's UTC offset unless
  explicitly corrected via `FUNDEDNEXT_SERVER_TIMEZONE`). This machine's `.env` sets
  `FUNDEDNEXT_SERVER_TIMEZONE=UTC`, so for this specific broker the correction is currently a no-op —
  but the conversion path is still exercised, not bypassed.
- **Closed-candle identification**: `market_data._with_candle_state()` adds `close_time = time +
  timeframe_duration` and `is_closed = close_time <= now`, derived from each row's own timestamp,
  never from row position.
- **Connection failure handling**: `connect()` never raises; every failure path sets `_last_error`
  and returns `False`/leaves `_connected=False`. `get_candles()`/`get_price_info()` raise
  `MarketDataError("MT5 not connected")` if called while disconnected — the existing contract is
  already "fail clearly," not "silently fall back."
- **Caching/persistence**: none, in the production path. `get_candles()` always makes a live
  `copy_rates_from_pos` call; there is no existing on-disk cache in `mt5/` to preserve or worry about
  overwriting. (The only pre-existing "cache" in this research line is the set of ad hoc pickles
  under `%TEMP%` from earlier manual research sessions — outside the repo, untouched here.)

**No changes were made to `mt5/connection.py`, `mt5/market_data.py`, or `mt5/timeutil.py`.** Every
requirement below was met by building new code around the existing integration, not by modifying it.

## 2. New fresh-data acquisition pipeline

`research/entry_model_v2_oos/data_acquisition.py` — new, read-only with respect to both MT5 (never
trades) and Entry Model V2/A+ (never imports them).

- `ensure_live_connection()` — connects if needed, raises `AcquisitionError` (never silently
  substitutes mock data) if `MODE != live`, the connection fails, or the symbol isn't ready.
- `fetch_fresh(timeframe, max_bars)` — calls the existing `market_data.get_candles()` unchanged,
  then checks freshness before trusting the read.
- `fresh_since_boundary(timeframe)` — the above, filtered to rows strictly after
  `spec.IS_DATA_END` **and** closed-only. This is the only function that applies the boundary filter.
- `append_fresh(timeframe, new_df)` — merges into a dedicated on-disk store
  (`research/entry_model_v2_oos/fresh_data/<TF>.pkl`, gitignored), deduplicating by `time`. A stored
  timestamp whose OHLC doesn't match a freshly fetched read for the same timestamp raises
  `AcquisitionError` (a genuine revision, not a normal duplicate) rather than silently overwriting.
  Reports every gap wider than one bar, without judging which are "expected" — that's left to
  whoever reads the report.
- `acquire_all()` — runs the above across all six timeframes, stopping immediately (not partially
  continuing) if any timeframe fails.

### A real bug found and fixed while building this

The integrity check above (store-vs-fetch OHLC mismatch ⇒ raise) initially fired on the very first
real run: the then-forming M5 candle's `low` had moved between two fetches a few seconds apart. A
forming candle's OHLC legitimately changes tick by tick until it closes — that is not a revision.
Fixed by having `fresh_since_boundary()` keep only `is_closed` rows, so nothing that can still change
is ever persisted. The still-forming bar is simply picked up on the next run, once closed.

### A second real gap found and fixed: silent contamination filtering

Requirement 4 of this task (OOS boundary compatibility) asks the pipeline to "fail loudly if
overlapping data is supplied... never silently filter contaminated samples into a valid OOS
dataset." Testing this directly (mixing a few genuine pre-boundary bars from the old in-sample cache
into the fresh M5 series) showed the existing `build_sample_times()` helper simply filtered the bad
rows out and proceeded — exactly the silent-filtering failure mode this research line exists to
prevent, just one level removed from the final sample list.

Fixed by adding `boundary.assert_raw_data_has_no_pre_boundary_contamination(raw)`, which checks the
**source** data (before any filtering) for any row at or before `IS_DATA_END` and raises
`OOSBoundaryViolation` naming the offending timeframe, row count, and latest contaminated timestamp.
Wired into `run_oos_evaluation.run()` immediately after loading the data, before
`build_sample_times()` touches it. Verified directly: a contaminated copy of the real fresh-data
directory, run through the actual `run()` entrypoint, now aborts immediately with a clear message
instead of silently proceeding on the clean subset.

## 3. Freshness verification (real MT5 data, this machine, this session)

MT5 connected successfully (`MODE=live`, blank `MT5_LOGIN`/`PASSWORD`/`SERVER` — `initialize()`
alone attached to and auto-launched the already-configured terminal). Account/server identity is
intentionally not reproduced here beyond what's needed to confirm it's real: a live Exness account,
symbol `XAUUSDm`, `FUNDEDNEXT_SERVER_TIMEZONE=UTC`.

A cold-connect's very first candle read came back about a day stale (terminal still syncing its
local history cache) — this is exactly what `fetch_fresh()`'s retry logic now guards against; a
re-read moments later was fully current, matching a direct raw `copy_rates_from_pos` check.

After the fixes above, `acquire_all()` against this live connection produced:

| Timeframe | New candles | Earliest | Latest | Gaps found |
|---|---|---|---|---|
| M1 | 2897 | 2026-10-06 12:21:00 UTC | 2026-10-08 14:41:00 UTC | 2× ~1h03m |
| M5 | 579 | 2026-10-06 12:25:00 UTC | 2026-10-08 14:35:00 UTC | 2× ~1h05m |
| M15 | 192 | 2026-10-06 12:30:00 UTC | 2026-10-08 14:15:00 UTC | 2× ~1h15m |
| H1 | 47 | 2026-10-06 13:00:00 UTC | 2026-10-08 13:00:00 UTC | 2× 2h |
| H4 | 11 | 2026-10-06 16:00:00 UTC | 2026-10-08 08:00:00 UTC | none |
| D1 | 1 | 2026-10-07 00:00:00 UTC | 2026-10-07 00:00:00 UTC | none |

The two gaps on the finer timeframes both sit at **20:55–22:00 UTC**, once per day — consistent with
a routine daily broker maintenance/rollover window, not a data defect. Reported as-is in each
acquisition summary's `unexpected_gaps` field rather than hidden or auto-classified as "expected."

Every row's `time` is UTC-aware (`pandas` tz-aware `Timestamp`, `tz=UTC`); every row satisfies
`time > 2026-10-06 12:20:00 UTC` (the frozen IS boundary) by construction. A second confirmation run
of `acquire_all()` a few minutes later added 0 new rows and skipped the existing ones as duplicates,
with no integrity error — confirming the dedup/append-only behavior is stable across repeated runs.

**This means genuinely-unseen, post-boundary MT5 data now exists locally** — currently about 2 days'
worth. That is almost certainly still far too little for a statistically meaningful OOS test of the
`0.5–1.0R` hypothesis (the in-sample study needed ~16,449 M5 samples to produce 115 tradeable
candidates; 579 samples would be expected to produce perhaps 1–4). No such study was run or implied
by this stage — this only establishes that the acquisition mechanism itself works correctly end to
end against a real connection.

## 4. OOS boundary compatibility (tested, not evaluated)

Confirmed directly against the real fresh data (not synthetic):

- `run_oos_evaluation.build_sample_times()` on the real fresh M5 store returns 579 valid sample
  instants, all strictly after `IS_DATA_END`; `boundary.assert_sample_times_after_boundary()` passes.
- A deliberately contaminated copy (5 genuine pre-boundary M5 bars mixed in) is rejected by
  `assert_raw_data_has_no_pre_boundary_contamination()` **and** by the full `run()` entrypoint,
  before any sampling or evaluation occurs.

`pipeline.run_evaluation_samples()` / `extract_candidates()` / outcome labeling were **not** run
against the real fresh data in this stage — doing so would begin the actual OOS evaluation, which
this task explicitly defers.

## 5. Files changed

New (all uncommitted):
- `research/entry_model_v2_oos/data_acquisition.py`
- `tests/test_entry_model_v2_oos_data_acquisition.py`
- `docs/entry-model-v2-oos-data-acquisition.md` (this document)
- `research/entry_model_v2_oos/fresh_data/*.pkl` (gitignored real data cache, not part of the commit
  surface regardless)

Changed:
- `.gitignore` — added `research/entry_model_v2_oos/fresh_data/`.
- `research/entry_model_v2_oos/boundary.py` — added
  `assert_raw_data_has_no_pre_boundary_contamination()`.
- `research/entry_model_v2_oos/run_oos_evaluation.py` — added a call to the new contamination guard
  right after loading raw data; fixed `build_sample_times()` to filter on each bar's `time` (open)
  field rather than `close_time` (an off-by-5-minutes boundary leak found and fixed in the prior
  stage, re-verified here against real data).

Not touched: `mt5/connection.py`, `mt5/market_data.py`, `mt5/timeutil.py`, `analysis/entry_model/*`,
`ai/strategy/rules.py`, `config.py`, any production route, any A+ or Analysis V2 logic.

## 6. Tests

```
tests/test_entry_model_v2_oos_data_acquisition.py   17 passed
tests/test_entry_model_v2_oos_pipeline.py           24 passed
tests/test_entry_model_hierarchy.py                 46 passed
tests/test_entry_model.py                           37 passed
tests/test_entry_model_outcome.py                   12 passed
----------------------------------------------------------------
136 passed
```

Full backend suite re-run after these changes; see the final chat report for the pass count.

## 7. Remaining MT5/account configuration required

None, for data acquisition specifically — the connection already works end to end on this machine
with the current `.env` (blank login/password/server, relying on the already-configured terminal
installation). The only real constraint is **time**: enough calendar days need to pass for the fresh
data volume to reach a size where an OOS evaluation of the `0.5–1.0R` hypothesis would be
statistically meaningful, per the same `MIN_N` convention (`research/entry_model_v2_oos/stats.py`)
used throughout this research line.

## 8. How to acquire more fresh data later

```python
from research.entry_model_v2_oos import data_acquisition as da
results = da.acquire_all()  # requires MODE=live and a working MT5 terminal; raises AcquisitionError clearly otherwise
```

Run this periodically (e.g. once a day) to keep extending the fresh-data cache under
`research/entry_model_v2_oos/fresh_data/`. That directory is already in exactly the shape
`run_oos_evaluation.py --data research/entry_model_v2_oos/fresh_data` expects, so once enough data
has accumulated, the OOS evaluation itself can be run with no data-wrangling step in between —
following the exact procedure in `docs/entry-model-v2-oos-readiness.md` §8.
