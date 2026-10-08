"""Fresh MT5 data acquisition for the Entry Model V2 OOS pipeline.

Pulls real candles through the EXISTING, unmodified mt5/connection.py and mt5/market_data.py
read-only integration (no new MT5 wiring, no change to the live data layer the running app uses),
keeps only the portion that is genuinely new since the frozen IS boundary
(research/entry_model_v2_oos/spec.py::IS_DATA_END), and appends it -- deduplicated, gap-checked,
UTC-normalized -- to a dedicated fresh-data cache that is entirely separate from any historical IS
dataset. That cache is written in exactly the shape
research/entry_model_v2_oos/run_oos_evaluation.py::load_raw() already expects (a directory of
per-timeframe pickles), so it can be pointed at directly once a real OOS run is warranted.

Read-only with respect to MT5 (never places, closes, or modifies an order -- same contract as
mt5/connection.py itself). Read-only with respect to Entry Model V2 and A+: this module never
imports analysis.entry_model or ai.strategy, and never alters a V2 parameter or threshold. It is
pure data plumbing.
"""
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import pandas as pd

import config
from mt5 import connection, market_data
from research.entry_model_v2_oos import spec

logger = logging.getLogger(__name__)

FRESH_DATA_DIR = Path(__file__).resolve().parent / "fresh_data"

TIMEFRAME_MINUTES = {"M1": 1, "M5": 5, "M15": 15, "H1": 60, "H4": 240, "D1": 1440}

# How many recent bars to request per timeframe when polling for "everything since the boundary."
# Generous on purpose (the boundary is currently only ~2 days behind "now", so these defaults leave
# wide headroom); callers can override via `max_bars` for a specific run.
DEFAULT_MAX_BARS = {"M1": 5000, "M5": 3000, "M15": 2000, "H1": 1000, "H4": 500, "D1": 120}


class AcquisitionError(Exception):
    """Raised whenever returning candle data would be misleading: not connected, symbol not ready,
    or a fresh read that still looks stale after retrying. Never caught-and-silently-substituted
    with cache or mock data by this module -- the caller must see the real failure."""


def ensure_live_connection() -> None:
    """Connects if not already connected, raising AcquisitionError (never falling back to mock
    data) on any failure. Mirrors mt5/connection.py's own 'never crash, always report clearly'
    contract, but turns the failure into an exception here since silent acquisition of nothing
    would otherwise look identical to a successful empty fetch."""
    if not config.IS_LIVE:
        raise AcquisitionError(
            f"MODE={config.MODE!r}, not 'live'. Fresh MT5 acquisition requires a live connection; "
            f"refusing to silently substitute mock data for data that was requested as real."
        )
    if not connection.is_connected():
        connection.connect()
    if not connection.is_connected():
        raise AcquisitionError(f"MT5 connection failed: {connection.last_error() or 'unknown error'}")
    if not connection.symbol_ready():
        raise AcquisitionError(
            f"Symbol {config.TRADING_SYMBOL!r} is not ready on this connection: "
            f"{connection.last_error() or 'symbol not visible/found'}"
        )


def fetch_fresh(timeframe: str, max_bars: Optional[int] = None, max_sync_retries: int = 5,
                retry_wait_seconds: float = 1.5) -> pd.DataFrame:
    """Fetches the most recent `max_bars` candles for `timeframe` via the existing
    market_data.get_candles() (unmodified), then verifies the read is actually fresh before
    trusting it.

    A terminal that was just connected/auto-launched can return a BRIEFLY stale or
    partially-synced history read -- this was observed directly while building this module (a cold
    connect returned a read whose newest bar was roughly a day old; re-reading moments later
    returned fully current data). Rather than silently accepting whatever MT5 hands back as "the
    fresh data," this retries a few times and raises AcquisitionError if the read never catches up,
    so a sync problem is reported, not hidden."""
    ensure_live_connection()
    max_bars = max_bars or DEFAULT_MAX_BARS[timeframe]
    minutes = TIMEFRAME_MINUTES[timeframe]
    df = None
    for attempt in range(max_sync_retries):
        df = market_data.get_candles(timeframe, count=max_bars)
        now = datetime.now(timezone.utc)
        newest_close = df["close_time"].max()
        lag_seconds = (now - newest_close).total_seconds()
        # A forming (not-yet-closed) bar's close_time is naturally still ahead of `now`, so a
        # negative lag here is expected and fine. Anything lagging by more than a few bar-widths is
        # the stale/unsynced-history symptom this retries for.
        if lag_seconds <= minutes * 60 * 3:
            return df
        logger.warning(
            "%s read looks stale on attempt %d/%d: newest close_time %s is %.1f min behind now (%s); retrying",
            timeframe, attempt + 1, max_sync_retries, newest_close, lag_seconds / 60, now,
        )
        time.sleep(retry_wait_seconds)
    raise AcquisitionError(
        f"{timeframe}: MT5 kept returning stale data after {max_sync_retries} attempts (newest "
        f"close_time {df['close_time'].max()} vs now {datetime.now(timezone.utc)}). Refusing to "
        f"report this as fresh -- the terminal's history has likely not finished syncing. Try again "
        f"shortly rather than trusting this read."
    )


def fresh_since_boundary(timeframe: str, max_bars: Optional[int] = None) -> pd.DataFrame:
    """fetch_fresh(), filtered to strictly-after-the-frozen-IS-boundary AND closed-only rows. This
    is the only function in this module that applies the boundary -- every other caller must go
    through it rather than re-filtering inline.

    Closed-only matters for more than just "don't look ahead": a forming candle's OHLC legitimately
    keeps changing tick by tick until it closes, so persisting one into the on-disk store and then
    re-fetching it later would look exactly like MT5 silently revising history (append_fresh()
    treats a stored/fetched OHLC mismatch on the same timestamp as a data-integrity problem and
    raises). Excluding forming candles here means every row that ever reaches the store is already
    immutable historical fact; the still-forming bar is simply picked up next time, once closed."""
    df = fetch_fresh(timeframe, max_bars=max_bars)
    return df[(df["time"] > spec.IS_DATA_END) & df["is_closed"]].reset_index(drop=True)


def _store_path(timeframe: str, root: Path = FRESH_DATA_DIR) -> Path:
    return root / f"{timeframe}.pkl"


def load_store(timeframe: str, root: Path = FRESH_DATA_DIR) -> Optional[pd.DataFrame]:
    path = _store_path(timeframe, root)
    if not path.exists():
        return None
    return pd.read_pickle(path)


def append_fresh(timeframe: str, new_df: pd.DataFrame, root: Path = FRESH_DATA_DIR) -> dict:
    """Merges `new_df` into the on-disk fresh-data store for `timeframe`, append-only with respect
    to the historical IS dataset (this store lives in its own directory and this function never
    touches anything else). Deduplicates by `time`; a timestamp that already exists with different
    OHLC values is a data-integrity problem and is RAISED, never silently overwritten with the new
    values (MT5 revising its own history after the fact is rare but real, and silently accepting a
    revision would make this store's own numbers mutate underfoot). Returns a small summary: how
    many rows were newly added, how many duplicates were skipped, and any unexpected gaps found in
    the merged, deduplicated series."""
    root.mkdir(parents=True, exist_ok=True)
    path = _store_path(timeframe, root)
    existing = load_store(timeframe, root)

    if existing is not None and len(existing) and len(new_df):
        overlap = existing.merge(new_df, on="time", suffixes=("_old", "_new"))
        for col in ("open", "high", "low", "close"):
            mismatched = overlap[(overlap[f"{col}_old"] - overlap[f"{col}_new"]).abs() > 1e-6]
            if len(mismatched):
                raise AcquisitionError(
                    f"{timeframe}: {len(mismatched)} existing candle(s) have a different {col!r} "
                    f"value in the newly fetched data than what is already stored (e.g. time="
                    f"{mismatched['time'].iloc[0]}: stored {mismatched[f'{col}_old'].iloc[0]} vs "
                    f"fetched {mismatched[f'{col}_new'].iloc[0]}). This looks like MT5 revising its "
                    f"own history, not a normal duplicate -- refusing to silently overwrite. "
                    f"Investigate before re-running."
                )

    combined = new_df if existing is None else pd.concat([existing, new_df], ignore_index=True)
    before = len(combined)
    combined = combined.drop_duplicates(subset="time", keep="first")
    combined = combined.sort_values("time").reset_index(drop=True)
    n_duplicates_skipped = before - len(combined)
    n_existing = 0 if existing is None else len(existing)
    n_newly_added = len(combined) - n_existing

    gaps = _find_gaps(combined, timeframe)

    combined.to_pickle(path)
    return {
        "timeframe": timeframe, "n_existing_before": n_existing, "n_newly_added": n_newly_added,
        "n_duplicates_skipped": n_duplicates_skipped, "n_total_after": len(combined),
        "earliest": None if len(combined) == 0 else str(combined["time"].min()),
        "latest": None if len(combined) == 0 else str(combined["time"].max()),
        "unexpected_gaps": gaps,
    }


def _find_gaps(df: pd.DataFrame, timeframe: str) -> list:
    """Reports every consecutive-row gap wider than one bar, WITHOUT trying to decide which gaps
    are 'expected' (weekend/market closure) and which are not -- that judgment belongs to whoever
    reads the report, not to this function. A gap is never hidden as if the data were simply
    shorter; every one is listed with its exact bounds and width."""
    if len(df) < 2:
        return []
    minutes = TIMEFRAME_MINUTES[timeframe]
    expected = pd.Timedelta(minutes=minutes)
    deltas = df["time"].diff().iloc[1:]
    gap_mask = deltas > expected
    gaps = []
    idx = df.index[1:][gap_mask.values]
    for i in idx:
        gaps.append({
            "after": str(df["time"].iloc[i - 1]), "before": str(df["time"].iloc[i]),
            "width": str(df["time"].iloc[i] - df["time"].iloc[i - 1]),
        })
    return gaps


def acquire_all(timeframes=tuple(TIMEFRAME_MINUTES), root: Path = FRESH_DATA_DIR) -> dict:
    """Fetches, boundary-filters, and appends fresh data for every timeframe in turn. Returns a
    per-timeframe summary dict suitable for a provenance report. Raises AcquisitionError (and
    acquires nothing further) on the first timeframe that fails -- a partial, silently-incomplete
    acquisition is worse than a clear stop."""
    ensure_live_connection()
    results = {}
    for tf in timeframes:
        fresh = fresh_since_boundary(tf)
        results[tf] = append_fresh(tf, fresh, root=root)
    return results
