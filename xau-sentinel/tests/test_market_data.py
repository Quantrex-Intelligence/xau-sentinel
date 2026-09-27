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
