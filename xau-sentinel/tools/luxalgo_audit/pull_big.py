"""Pull a longer raw MT5 history for the A+ parity validation. Read-only. Writes raw_big.pkl to TEMP."""
import os
import pickle
import sys

import pandas as pd


sys.path.insert(0, REPO)
os.chdir(REPO)

import MetaTrader5 as mt5  # noqa: E402
import config  # noqa: E402
from mt5.timeutil import series_to_utc  # noqa: E402

OUT = RAW
SPEC = {
    "M5": (mt5.TIMEFRAME_M5, 99000, 5),
    "M15": (mt5.TIMEFRAME_M15, 60000, 15),
    "H1": (mt5.TIMEFRAME_H1, 30000, 60),
    "H4": (mt5.TIMEFRAME_H4, 5000, 240),
}

assert mt5.initialize(), mt5.last_error()
out = {}
for tf, (code, n, mins) in SPEC.items():
    rates = mt5.copy_rates_from_pos(config.TRADING_SYMBOL, code, 0, n)
    assert rates is not None and len(rates), (tf, mt5.last_error())
    df = pd.DataFrame(rates)
    df["time"] = series_to_utc(pd.Series(df["time"].values))
    df = df.rename(columns={"tick_volume": "volume"})[["time", "open", "high", "low", "close", "volume"]]
    df["close_time"] = df["time"] + pd.Timedelta(minutes=mins)
    df = df.reset_index(drop=True)
    df["is_closed"] = True
    out[tf] = df
    print(tf, len(df), df["time"].iloc[0], "->", df["time"].iloc[-1])
mt5.shutdown()
pickle.dump(out, open(OUT, "wb"))
print("saved", OUT)
