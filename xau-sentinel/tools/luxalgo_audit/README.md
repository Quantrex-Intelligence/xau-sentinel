# LuxAlgo ICT Concepts: offline audit tool

Offline research tool. It compares a Python reimplementation of the detection logic of the TradingView
script "ICT Concepts [LuxAlgo]" with Analysis Engine V2's primitives on the same raw XAUUSD candles.

It is not part of the product. Nothing here is imported by the API, the UI, the V2 engine or the A+ path,
and no LuxAlgo threshold is used as a trading rule or a validated edge.

## Licence and attribution

- The original script is © LuxAlgo, licensed CC BY-NC-SA 4.0 (non-commercial, share-alike). This folder
  does **not** include the Pine source. `luxalgo_ref.py` is an independent Python reimplementation of the
  detection rules, written for this audit. Check the licence before reusing the reimplementation outside
  this repository.

## Files

- `pull_big.py`: pulls the raw MT5 history (M5 99,000 bars, M15, H1, H4) into `TEMP/raw_big.pkl`. Needs MetaTrader 5 running and logged in.
- `luxalgo_ref.py`: the reimplementation. Assumptions about Pine semantics are listed in its header (A1 to A5).
- `audit_run.py`: component comparison (displacement, FVG creation and mitigation, MSS/BOS, liquidity clusters, order blocks). Writes `audit_results.json`.
- `liq_asof.py`: liquidity comparison evaluated as-of every bar, because V2's equal-level detector is a snapshot. Writes `liquidity_asof.json`.

## Run

```
# from xau-sentinel/ (MT5 terminal running and logged in)
MODE=live .venv/Scripts/python tools/luxalgo_audit/pull_big.py
MODE=live .venv/Scripts/python tools/luxalgo_audit/audit_run.py
MODE=live .venv/Scripts/python tools/luxalgo_audit/liq_asof.py
```

Outputs go to `XAU_AUDIT_OUT` if set, otherwise to `TEMP`. Raw data is read from `TEMP/raw_big.pkl`.

## Limits

- The reimplementation has not been checked against TradingView's rendered output. Some mismatches could be
  reimplementation errors. Treat the counts as indicative until that check is done.
- Windows: displacement and FVG on the last 20,000 M5 and 6,000 H1 bars; structure and liquidity on the last
  2,000 M5 and 1,500 H1 bars. Structure replay is slow on longer windows.
- Evaluation is on closed bars only. The LuxAlgo script runs live on the forming bar too, so the live
  behaviour can differ.
