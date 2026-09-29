"""Regression tests for the MT5/risk batch: VAL-016 (commission/swap/fee left
out of realized P/L), VAL-017 (deal timestamps and the history query
window), VAL-027 (mock seeds from randomized hash()), VAL-028 (a missing
symbol surfacing only as "no candle data") and VAL-031 (no Stellar phase-2
case). Each runs the real code path against a FakeMT5, the same pattern as
tests/test_fundednext.py and tests/test_market_data.py."""
import subprocess
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock

import pytest

import config
from mt5 import account as mt5_account, connection, market_data
from risk import settings_store
from risk.fundednext import compute_status
from risk.models import AccountSnapshot, AccountType, Phase
from stable_seed import stable_seed

XAU_ROOT = Path(__file__).resolve().parents[1]


class FakeDeal:
    def __init__(self, deal_type, profit=0.0, time=None, commission=0.0, swap=0.0, fee=0.0):
        self.type = deal_type
        self.profit = profit
        self.commission = commission
        self.swap = swap
        self.fee = fee
        self.time = time if time is not None else int(datetime(2026, 1, 5, 10, tzinfo=timezone.utc).timestamp())


class FakeMT5:
    """Mirrors MT5's own filter: a deal is returned only when its raw
    (server wall-clock) epoch lies inside [date_from, date_to]."""
    DEAL_TYPE_BUY = 0
    DEAL_TYPE_SELL = 1
    DEAL_TYPE_BALANCE = 2

    def __init__(self, deals):
        self.deals = deals
        self.window = None

    def history_deals_get(self, from_dt, to_dt):
        self.window = (from_dt, to_dt)
        lo, hi = from_dt.timestamp(), to_dt.timestamp()
        return [d for d in self.deals if lo <= d.time <= hi]


@pytest.fixture
def live_deals(monkeypatch):
    def install(deals, tz="UTC"):
        fake = FakeMT5(deals)
        monkeypatch.setattr(config, "IS_MOCK", False)
        monkeypatch.setattr(config, "FUNDEDNEXT_SERVER_TIMEZONE", tz)
        monkeypatch.setattr(mt5_account, "mt5", fake)
        monkeypatch.setattr(mt5_account.connection, "is_connected", Mock(return_value=True))
        return fake
    return install


# ---------------------------------------------------------------------------
# VAL-016 — realized P/L includes commission, swap and fee
# ---------------------------------------------------------------------------

def test_realized_pnl_includes_commission_swap_and_fee(live_deals):
    live_deals([
        FakeDeal(FakeMT5.DEAL_TYPE_BUY, profit=0.0, commission=-3.5),            # opening deal: commission only
        FakeDeal(FakeMT5.DEAL_TYPE_SELL, profit=500.0, commission=-3.5, swap=-2.0, fee=-1.0),
        FakeDeal(FakeMT5.DEAL_TYPE_BALANCE, profit=50_000.0),                    # deposit: excluded
    ])
    history = mt5_account.get_daily_pnl_history(days=400)
    assert history == [(date(2026, 1, 5), 490.0)]


def test_deal_without_commission_attributes_still_counts(live_deals):
    class BareDeal:
        type = FakeMT5.DEAL_TYPE_BUY
        profit = 120.0
        time = int(datetime(2026, 1, 5, 10, tzinfo=timezone.utc).timestamp())

    live_deals([BareDeal()])
    assert mt5_account.get_daily_pnl_history(days=400) == [(date(2026, 1, 5), 120.0)]


def test_day_start_balance_is_exact_once_charges_are_counted(monkeypatch):
    """End to end through compute_status(): the account opened the day at
    100,000, closed +500 gross with 10 of charges, so balance is 100,490.
    Before the fix the anchor came out 10 too high (100,010)."""
    today = date(2026, 1, 5)
    monkeypatch.setattr(config, "IS_MOCK", False)
    monkeypatch.setattr(config, "ACCOUNT_BALANCE", 100_000.0)
    monkeypatch.setattr(mt5_account, "get_account_snapshot",
                        lambda: AccountSnapshot(balance=100_490.0, equity=100_490.0, source="live"))
    monkeypatch.setattr(mt5_account, "server_now", lambda: datetime(2026, 1, 5, 12, tzinfo=timezone.utc))
    monkeypatch.setattr(mt5_account, "get_daily_pnl_history", lambda days: [(today, mt5_account._realized_pnl(
        FakeDeal(FakeMT5.DEAL_TYPE_SELL, profit=500.0, commission=-7.0, swap=-3.0)))])
    status = compute_status(AccountType.STELLAR_2STEP, Phase.CHALLENGE)
    assert status.day_start_balance == 100_000.0
    assert status.today_pnl == 490.0


# ---------------------------------------------------------------------------
# VAL-017 — deal timestamps and the history query window
# ---------------------------------------------------------------------------

def _server_wall_epoch(server_wall: datetime) -> int:
    """What MT5 returns for a deal at `server_wall` (a naive server
    wall-clock reading): that reading's digits encoded as if they were UTC."""
    return int(server_wall.replace(tzinfo=timezone.utc).timestamp())


def test_late_evening_deal_stays_on_its_server_day_no_double_shift(live_deals):
    """A deal at 23:30 Nicosia server time belongs to that server day. The
    double conversion VAL-017 suspected (tag UTC, then convert to Nicosia)
    would push it to 01:30 the next day."""
    live_deals([FakeDeal(FakeMT5.DEAL_TYPE_SELL, profit=100.0,
                         time=_server_wall_epoch(datetime(2026, 1, 5, 23, 30)))], tz="Europe/Nicosia")
    assert mt5_account.get_daily_pnl_history(days=400) == [(date(2026, 1, 5), 100.0)]


def test_query_window_includes_a_deal_that_just_closed_on_a_utc_plus_server(live_deals):
    """The server clock (UTC+2/+3) is ahead of true UTC, so a deal closed a
    minute ago carries an epoch hours past true-UTC "now". The old window
    ended at true-UTC now and silently dropped it."""
    tz = "Europe/Nicosia"
    from zoneinfo import ZoneInfo
    server_wall_now = datetime.now(ZoneInfo(tz)).replace(tzinfo=None)
    just_closed = FakeDeal(FakeMT5.DEAL_TYPE_SELL, profit=-250.0,
                           time=_server_wall_epoch(server_wall_now - timedelta(minutes=1)))
    fake = live_deals([just_closed], tz=tz)

    history = mt5_account.get_daily_pnl_history(days=10)
    assert sum(p for _, p in history) == -250.0
    assert fake.window[1] > datetime.now(timezone.utc) + timedelta(hours=3)


# ---------------------------------------------------------------------------
# VAL-027 — mock seeds don't depend on the per-process hash salt
# ---------------------------------------------------------------------------

_SEED_PROBE = (
    "import sys; sys.path.insert(0, '.');"
    "from mt5 import market_data, account;"
    "from ai.market_intelligence.providers import mock;"
    "print(market_data._mock_seed('M5'), account._mock_seed('balance-2026-01-05'), mock._mock_seed('macro'))"
)


def _probe(hash_seed: str) -> str:
    import os
    env = {**os.environ, "PYTHONHASHSEED": hash_seed}
    out = subprocess.run([sys.executable, "-c", _SEED_PROBE], cwd=XAU_ROOT, env=env,
                         capture_output=True, text=True, check=True, timeout=120)
    return out.stdout.strip()


def test_mock_seeds_are_identical_across_processes_with_different_hash_salts():
    assert _probe("1") == _probe("2") == _probe("12345")


def test_stable_seed_is_32_bit_and_depends_only_on_parts():
    assert stable_seed("M5", "xau-sentinel-mock") == stable_seed("M5", "xau-sentinel-mock")
    assert stable_seed("M5", "xau-sentinel-mock") != stable_seed("M15", "xau-sentinel-mock")
    assert 0 <= stable_seed("anything") < 2**32


def test_mock_candles_are_reproducible_within_a_bar():
    a = market_data._mock_candles("H4", 50)
    b = market_data._mock_candles("H4", 50)
    assert a["close"].tolist() == b["close"].tolist()


# ---------------------------------------------------------------------------
# VAL-028 — a missing symbol names itself in the data error
# ---------------------------------------------------------------------------

@pytest.fixture
def live_terminal_without_symbol(monkeypatch):
    class FakeTerminal:
        TIMEFRAME_M5 = 5

        def initialize(self):
            return True

        def symbol_info(self, symbol):
            return None

        def copy_rates_from_pos(self, *args):
            return None

        def symbol_info_tick(self, symbol):
            return None

    fake = FakeTerminal()
    # Snapshot connection's module state so connect() below can't leak it.
    for name in ("_connected", "_symbol_ready", "_last_error"):
        monkeypatch.setattr(connection, name, getattr(connection, name))
    monkeypatch.setattr(config, "IS_LIVE", True)
    monkeypatch.setattr(config, "IS_MOCK", False)
    for name in ("MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"):
        monkeypatch.setattr(config, name, "")
    monkeypatch.setattr(connection, "mt5", fake)
    monkeypatch.setattr(market_data, "mt5", fake)
    monkeypatch.setattr(connection, "is_connected", Mock(return_value=True))
    return fake


def test_missing_symbol_is_named_in_the_candle_error(live_terminal_without_symbol):
    assert connection.connect() is True  # the terminal itself is up
    with pytest.raises(market_data.MarketDataError) as exc:
        market_data.get_candles("M5")
    message = str(exc.value)
    assert "No candle data returned for M5" in message
    assert config.TRADING_SYMBOL in message and "not found" in message


def test_missing_symbol_is_named_in_the_tick_error(live_terminal_without_symbol):
    connection.connect()
    with pytest.raises(market_data.MarketDataError, match="not found"):
        market_data.get_price_info()


def test_generic_error_kept_when_the_symbol_is_fine(live_terminal_without_symbol, monkeypatch):
    monkeypatch.setattr(connection, "_symbol_ready", True)
    monkeypatch.setattr(connection, "_last_error", None)
    with pytest.raises(market_data.MarketDataError) as exc:
        market_data.get_candles("M5")
    assert str(exc.value) == "No candle data returned for M5"


# ---------------------------------------------------------------------------
# VAL-031 — Stellar phase 2 has its own profit target
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("account_type, phase, target_pct, days_required", [
    (AccountType.STELLAR_2STEP, Phase.CHALLENGE, 8.0, 5),
    (AccountType.STELLAR_2STEP, Phase.CHALLENGE_PHASE2, 5.0, 5),
    (AccountType.STELLAR_LITE, Phase.CHALLENGE, 8.0, 5),
    (AccountType.STELLAR_LITE, Phase.CHALLENGE_PHASE2, 4.0, 5),
    (AccountType.STELLAR_2STEP, Phase.FUNDED, None, None),
])
def test_profit_target_and_days_follow_the_phase(account_type, phase, target_pct, days_required):
    status = compute_status(account_type, phase)  # mock mode
    assert status.data_available is True
    assert status.profit_target_pct == target_pct
    assert status.trading_days_required == days_required
    if target_pct is not None:
        assert status.profit_target == round(target_pct / 100 * config.ACCOUNT_BALANCE, 2)


def test_phase2_setting_round_trips(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_store, "SETTINGS_PATH", tmp_path / "fundednext_settings.json")
    saved = settings_store.save_settings(phase="challenge_phase2")
    assert saved["phase"] == "challenge_phase2"
    assert Phase(settings_store.get_settings()["phase"]) is Phase.CHALLENGE_PHASE2


def test_existing_challenge_value_still_means_phase_one():
    assert Phase("challenge") is Phase.CHALLENGE
