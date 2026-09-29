"""MT5 / market data robustness validation (spec section 4)."""
import config
from mt5 import connection, market_data


def test_mock_mode_never_touches_mt5_and_is_labeled_mock(monkeypatch):
    monkeypatch.setattr(config, "MODE", "mock")
    monkeypatch.setattr(config, "IS_MOCK", True)
    monkeypatch.setattr(config, "IS_LIVE", False)

    df = market_data.get_candles("M5", count=50)
    assert len(df) == 50
    assert list(df.columns) == ["time", "open", "high", "low", "close", "volume"]

    price_info = market_data.get_price_info()
    assert price_info["source"] == "mock"


def test_mock_price_is_never_reported_as_live(monkeypatch):
    monkeypatch.setattr(config, "IS_MOCK", True)
    price_info = market_data.get_price_info()
    assert price_info["source"] != "live"


def test_connect_is_a_noop_when_mode_is_mock(monkeypatch):
    monkeypatch.setattr(config, "IS_LIVE", False)
    assert connection.connect() is False
    assert connection.is_connected() is False


def test_connect_reports_unavailable_when_mt5_package_missing(monkeypatch):
    """On Linux/macOS (or any host without the MetaTrader5 package), LIVE mode
    must degrade to a clear disconnected state, never raise."""
    monkeypatch.setattr(config, "IS_LIVE", True)
    monkeypatch.setattr(connection, "mt5", None)
    result = connection.connect()
    assert result is False
    assert connection.last_error() is not None
    assert "Windows-only" in connection.last_error()


def test_connect_never_raises_on_initialize_failure(monkeypatch):
    monkeypatch.setattr(config, "IS_LIVE", True)

    class FakeMT5:
        def initialize(self):
            return False

        def last_error(self):
            return (1, "terminal not found")

    monkeypatch.setattr(connection, "mt5", FakeMT5())
    result = connection.connect()
    assert result is False
    assert "initialize" in connection.last_error()


def test_connect_never_raises_on_unexpected_exception(monkeypatch):
    monkeypatch.setattr(config, "IS_LIVE", True)

    class ExplodingMT5:
        def initialize(self):
            raise RuntimeError("terminal crashed")

    monkeypatch.setattr(connection, "mt5", ExplodingMT5())
    result = connection.connect()  # must not propagate the exception
    assert result is False
    assert connection.is_connected() is False


def test_connect_reports_missing_symbol(monkeypatch):
    monkeypatch.setattr(config, "IS_LIVE", True)
    monkeypatch.setattr(config, "MT5_LOGIN", "")
    monkeypatch.setattr(config, "MT5_PASSWORD", "")
    monkeypatch.setattr(config, "MT5_SERVER", "")

    class FakeMT5:
        def initialize(self):
            return True

        def symbol_info(self, symbol):
            return None  # symbol not found by this broker

    monkeypatch.setattr(connection, "mt5", FakeMT5())
    result = connection.connect()
    assert result is True  # connection itself succeeded...
    assert connection.symbol_ready() is False  # ...but the symbol is unusable
    assert "not found" in connection.last_error()


def test_get_candles_converts_server_time_to_true_utc_not_a_naive_misread(monkeypatch):
    """Stage 19 regression (see docs/validation/ISSUE_LOG.md VAL-003): MT5's
    raw candle `time` is the broker SERVER's wall-clock reading, not true
    UTC seconds. A FakeMT5 returning a candle whose raw time corresponds to
    a known non-UTC server reading must come back through get_candles()
    already correctly shifted to true UTC, not misread as if it were
    already UTC."""
    import calendar
    monkeypatch.setattr(config, "FUNDEDNEXT_SERVER_TIMEZONE", "Europe/Nicosia")
    monkeypatch.setattr(config, "IS_MOCK", False)
    monkeypatch.setattr(config, "TRADING_SYMBOL", "XAUUSD")

    # Server wall-clock reading 2026-01-15 14:00:00 == true UTC 12:00:00
    # (Nicosia is UTC+2 in January).
    from datetime import datetime, timezone
    server_wallclock = datetime(2026, 1, 15, 14, 0, 0)
    raw_epoch = calendar.timegm(server_wallclock.timetuple())

    class FakeMT5:
        TIMEFRAME_M5 = 5

        def copy_rates_from_pos(self, symbol, timeframe, pos, count):
            return [{
                "time": raw_epoch, "open": 3700.0, "high": 3701.0, "low": 3699.0,
                "close": 3700.5, "tick_volume": 100,
            }]

    monkeypatch.setattr(market_data, "mt5", FakeMT5())
    monkeypatch.setattr(connection, "is_connected", lambda: True)

    df = market_data.get_candles("M5", count=1)
    candle_time = df["time"].iloc[0].to_pydatetime()
    assert candle_time == datetime(2026, 1, 15, 12, 0, 0, tzinfo=timezone.utc)


def test_get_candles_raises_market_data_error_when_disconnected(monkeypatch):
    monkeypatch.setattr(config, "IS_MOCK", False)
    monkeypatch.setattr(market_data, "mt5", None)
    try:
        market_data.get_candles("M5")
        assert False, "expected MarketDataError"
    except market_data.MarketDataError:
        pass


def test_get_candles_rejects_unsupported_timeframe():
    try:
        market_data.get_candles("W1")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_is_connected_false_when_not_live_even_if_mt5_present(monkeypatch):
    monkeypatch.setattr(config, "IS_LIVE", False)
    assert connection.is_connected() is False


def test_status_label_reflects_connection_state(monkeypatch):
    monkeypatch.setattr(config, "IS_LIVE", False)
    label, ok = connection.status_label()
    assert ok is False
    assert "DISCONNECTED" in label


# ---------------------------------------------------------------------------
# Data staleness (spec section 21)
# ---------------------------------------------------------------------------

def test_fresh_tick_is_not_stale(monkeypatch):
    from datetime import datetime, timezone
    monkeypatch.setattr(config, "IS_MOCK", False)
    monkeypatch.setattr(config, "DATA_STALE_SECONDS", 120)
    now = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
    price_info = {"time": now, "price": 100.0}
    assert market_data.is_stale(price_info, now=now) is False


def test_old_tick_is_flagged_stale(monkeypatch):
    from datetime import datetime, timedelta, timezone
    monkeypatch.setattr(config, "IS_MOCK", False)
    monkeypatch.setattr(config, "DATA_STALE_SECONDS", 120)
    tick_time = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)
    now = tick_time + timedelta(seconds=200)  # well past the 120s threshold
    price_info = {"time": tick_time, "price": 100.0}
    assert market_data.is_stale(price_info, now=now) is True


def test_mock_data_is_never_reported_stale_in_practice(monkeypatch):
    """Mock candles are timestamped relative to "now" every call, so a live
    read of mock price info must never be flagged stale."""
    monkeypatch.setattr(config, "IS_MOCK", True)
    price_info = market_data.get_price_info()
    assert market_data.is_stale(price_info) is False


def test_missing_price_info_is_not_stale():
    assert market_data.is_stale(None) is False
    assert market_data.is_stale({}) is False
