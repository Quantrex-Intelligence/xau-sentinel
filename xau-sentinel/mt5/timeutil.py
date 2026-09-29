"""The ONE explicit MT5-server-time -> UTC conversion boundary (Stage 19,
see docs/validation/ISSUE_LOG.md VAL-003). Every place that reads a raw
epoch-seconds value from the MT5 API (candle time, tick time, deal time)
must convert it through here, not repeat the conversion inline.

MT5's raw epoch-seconds values represent the broker server's own
wall-clock reading, NOT true UTC seconds — treating them as UTC (as
mt5/market_data.py and mt5/account.py both did before this fix) silently
shifts every timestamp by the server's UTC offset, which in turn breaks
staleness checks, sweep-window expiry, and session/day-boundary logic
whenever the broker server isn't itself UTC (this project's own
FUNDEDNEXT_SERVER_TIMEZONE default, Europe/Nicosia, is not).

server_timezone()/server_now() live here (moved out of mt5/account.py,
which needs both this module's conversion AND is imported by it) rather
than in mt5/account.py, to avoid a circular import — see
[[feedback-circular-import-via-extraction]]. mt5/account.py re-exports
both names unchanged for its existing external callers.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pandas as pd

import config


def server_timezone() -> ZoneInfo:
    return ZoneInfo(config.FUNDEDNEXT_SERVER_TIMEZONE)


def server_now() -> datetime:
    return datetime.now(server_timezone())


def to_utc(epoch_seconds) -> datetime:
    """A single raw MT5 epoch-seconds value (the broker server's own
    wall-clock reading) -> a true UTC-aware datetime."""
    naive_server_time = datetime.utcfromtimestamp(epoch_seconds)
    return naive_server_time.replace(tzinfo=server_timezone()).astimezone(timezone.utc)


def series_to_utc(epoch_seconds: pd.Series) -> pd.Series:
    """Vectorized form of to_utc(), for a DataFrame column of raw MT5
    epoch-seconds values (e.g. candle open times)."""
    naive = pd.to_datetime(epoch_seconds, unit="s")
    return naive.dt.tz_localize(server_timezone()).dt.tz_convert("UTC")
