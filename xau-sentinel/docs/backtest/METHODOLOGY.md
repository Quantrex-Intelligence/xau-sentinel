# Backtest baseline methodology

This benchmark measures what the existing deterministic engine's signals do on real XAUUSD history. It is a
diagnostic baseline. It is not a trading system, and the outcome label is not a target to optimise for.

## Dataset

- Source: MetaTrader 5 history for the symbol in `TRADING_SYMBOL` (XAUUSDm, Exness), via `copy_rates_range`.
- Timeframes: M5 (primary), M15, H1, H4 (context for the engine).
- Period: six months ending at the latest available bar.
- Timestamps: converted by `mt5/timeutil.py` from broker server time to UTC, the same path the live engine uses.
- Cache: `backtest/data/*.csv` (gitignored), regenerable with `--refresh`.

## In-sample / out-of-sample split

- Out-of-sample (OOS): the last 60 days.
- In-sample (IS): everything before that, starting at M5 bar 300 (the engine needs a 300-bar window).
- No parameter is tuned on either window in this baseline. The split exists so any apparent edge can be checked
  on data it was not chosen on.

## Replay and lookahead protection

- At each M5 bar `i`, the engine receives only candles closed by the bar's close time (`now = t_i + 5 min`).
  Each timeframe window is the last 300 closed candles.
- The engine functions are unchanged: `analyze_structure`, `compute_zones`, `detect_sweeps`, `displacement_at`,
  `detect_setup`, `classify_regime`.
- A regression test (`tests/test_backtest_harness.py::test_replay_never_uses_future_bars`) replays a truncated
  history and checks that every signal before the cutoff is identical. It passes on mock data.

## Signal definitions (frozen for this baseline)

| Type | Fires when | Direction |
|---|---|---|
| BOS | `last_bos` on M5 or H1 changes from the previous bar to a non-null value | bullish = BUY, bearish = SELL |
| MSS | `last_mss` on M5 or H1 changes to a non-null value | bullish = BUY, bearish = SELL |
| SWEEP | `detect_sweeps` returns an event timed at this M5 bar | sweep_low = BUY, sweep_high = SELL |
| DISPLACEMENT | `displacement_at` returns a value for this M5 bar | bullish = BUY, bearish = SELL |
| SETUP_VALID | `detect_setup` state changes to VALID on this bar | the setup's direction |

BOS and MSS are pooled across M5 and H1 for the headline numbers. Each signal records its timeframe, so the
per-timeframe split can be reported later.

## Outcome label

- Entry: the close of the signal bar.
- Scale: ATR(14) on M5, computed as a rolling mean of the true range (`analysis/structure.py::compute_atr`), read
  at the signal bar. The ATR is trailing, so it uses no future data.
- For a BUY: target = entry + 1.0 ATR, stop = entry - 1.0 ATR. SELL is mirrored.
- Window: the next 48 M5 bars (4 hours).
- First level touched decides the outcome. If one bar touches both levels, the order is unknown and it is
  counted as a loss.
- No level reached in the window is a timeout.
- Win rate = wins / (wins + losses). Timeouts are reported separately and excluded from the rate.
- Costs (spread, slippage) are not modelled.

## Overlapping signals

- Raw: every emitted signal is counted.
- Non-overlapping: per (type, direction), keep a signal only if it is at least 48 bars after the last kept one.
  Signals inside another signal's outcome window describe the same move, so counting both overstates the sample.
- Both views are reported. Stability is judged on the non-overlapping view.

## Baseline

- For every sampled bar in the window, label both a BUY and a SELL with the same rule.
- Baseline win rate = pooled wins / (wins + losses) across both directions.
- An uninformed signal would be expected to score near this value. Lift = signal win rate - baseline.

## Uncertainty

- 95% intervals use the Wilson score method, which behaves well at small n and at extreme proportions.
- A signal type is called STABLE only if all of these hold: at least 30 decided signals in both IS and OOS, the
  lift has the same sign in both, and each window's interval excludes the baseline on the same side. Otherwise
  it is reported as noise or unstable.

## Breakdowns

- Month (YYYY-MM).
- Direction (BUY vs SELL, i.e. bullish vs bearish).
- Session, by UTC hour.
- Regime, from `analysis/regime.py::classify_regime(H1, M15)` at the signal bar.

## Known limitations

- Session breakdown: the replay labels the Asian session as 0-7 UTC, but `config.py` defines it as 0-6
  (`ASIAN_SESSION_END_UTC=6`), so hour 6 is "OFF" in the engine and "ASIAN" in the report. This affects only the
  session breakdown labels, not signals. It is recorded here rather than changed mid-benchmark.
- The label is a fixed ±1 ATR barrier and does not match any trading plan. Results describe the signals under
  this label only.
- A single data source (one broker's M5 history) is used.
- The engine is evaluated as it is, including any known weaknesses.
