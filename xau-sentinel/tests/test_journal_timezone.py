"""Stage 22 (VAL-012): journal trade_date/trade_time must come from ONE
timezone boundary -- config.SESSION_TIMEZONE via journal.trades.session_now()
-- on every write path and every "today" read path, so a trade near
midnight lands on the correct local trading date. All instants below are
frozen; nothing depends on the real wall clock."""
import inspect
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

import config
from ai.digest import service as digest_service
from ai.digest.models import DigestType
from api.main import app
from journal import trades as trades_repo

NEW_YORK = ZoneInfo("America/New_York")
TOKYO = ZoneInfo("Asia/Tokyo")

# Sunday 23:55 in New York is already Monday 03:55 UTC.
NY_LATE_SUNDAY = datetime(2026, 10, 4, 23, 55, 0, tzinfo=NEW_YORK)
# Monday 00:05 in Tokyo is still Sunday 15:05 UTC.
TOKYO_EARLY_MONDAY = datetime(2026, 10, 5, 0, 5, 0, tzinfo=TOKYO)


@pytest.fixture
def api_client(temp_db):
    with TestClient(app) as client:
        yield client


def _freeze(monkeypatch, instant: datetime):
    monkeypatch.setattr(config, "SESSION_TIMEZONE", instant.tzinfo.key)
    monkeypatch.setattr(trades_repo, "session_now", lambda: instant)


def _post_trade(api_client, **extra):
    resp = api_client.post("/api/journal/trades", json={
        "direction": "BUY", "entry": 3740.0, "stop_loss": 3735.0, "take_profit": 3750.0, **extra,
    })
    assert resp.status_code == 200
    return resp.json()


def _close(api_client, trade_id, r_multiple=2.0):
    resp = api_client.patch(f"/api/journal/trades/{trade_id}/close", json={
        "exit_price": 3750.0, "result": "WIN" if r_multiple > 0 else "LOSS", "r_multiple": r_multiple,
    })
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# The single clock
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("zone", ["UTC", "America/New_York", "Asia/Tokyo", "Europe/Nicosia"])
def test_session_now_is_aware_and_in_the_configured_session_timezone(monkeypatch, zone):
    monkeypatch.setattr(config, "SESSION_TIMEZONE", zone)
    now = trades_repo.session_now()
    assert now.tzinfo is not None
    assert now.tzinfo == ZoneInfo(zone)


def test_session_now_uses_the_same_boundary_as_the_digest_clock(monkeypatch):
    monkeypatch.setattr(config, "SESSION_TIMEZONE", "Asia/Tokyo")
    assert trades_repo.session_now().tzinfo == digest_service._now().tzinfo


# ---------------------------------------------------------------------------
# Write path: POST /api/journal/trades
# ---------------------------------------------------------------------------

def test_api_trade_date_is_the_session_local_date_when_utc_is_already_tomorrow(api_client, monkeypatch):
    _freeze(monkeypatch, NY_LATE_SUNDAY)
    trade = _post_trade(api_client)
    assert trade["trade_date"] == "2026-10-04"  # UTC would say 2026-10-05
    assert trade["trade_time"] == "23:55:00"


def test_api_trade_date_is_the_session_local_date_when_utc_is_still_yesterday(api_client, monkeypatch):
    _freeze(monkeypatch, TOKYO_EARLY_MONDAY)
    trade = _post_trade(api_client)
    assert trade["trade_date"] == "2026-10-05"  # UTC would say 2026-10-04
    assert trade["trade_time"] == "00:05:00"


@pytest.mark.parametrize("instant", [NY_LATE_SUNDAY, TOKYO_EARLY_MONDAY])
def test_api_trade_date_and_time_reconstruct_the_exact_same_instant(api_client, monkeypatch, instant):
    _freeze(monkeypatch, instant)
    trade = _post_trade(api_client)
    local = datetime.strptime(f"{trade['trade_date']} {trade['trade_time']}", "%Y-%m-%d %H:%M:%S")
    assert local.replace(tzinfo=instant.tzinfo) == instant
    assert local.replace(tzinfo=instant.tzinfo).astimezone(timezone.utc) == instant.astimezone(timezone.utc)


def test_explicit_date_and_time_pair_is_stored_as_a_session_local_backfill(api_client, monkeypatch):
    """Existing API compatibility: a client that deliberately supplies both
    fields (a backfill, same meaning as the Streamlit form's editable
    pickers) gets exactly that pair, never mixed with the server clock."""
    _freeze(monkeypatch, NY_LATE_SUNDAY)
    trade = _post_trade(api_client, trade_date="2026-09-30", trade_time="14:30:00")
    assert (trade["trade_date"], trade["trade_time"]) == ("2026-09-30", "14:30:00")


@pytest.mark.parametrize("partial", [{"trade_date": "2026-10-05"}, {"trade_time": "09:55:00"}])
def test_supplying_only_one_of_date_or_time_is_rejected(api_client, monkeypatch, partial):
    """Half a client value plus half a server value is exactly the
    two-clocks mix VAL-012 was about -- refuse it rather than store it."""
    _freeze(monkeypatch, NY_LATE_SUNDAY)
    resp = api_client.post("/api/journal/trades", json={
        "direction": "BUY", "entry": 3740.0, "stop_loss": 3735.0, **partial,
    })
    assert resp.status_code == 422
    assert api_client.get("/api/journal/trades").json() == []


def test_new_trade_form_no_longer_computes_its_own_date_or_time():
    """The Next.js form was the source of the UTC-date/local-time mix; it
    must leave both fields to the server."""
    form = (config.BASE_DIR / "frontend" / "components" / "journal" / "new-trade-form.tsx").read_text(encoding="utf-8")
    for banned in ("trade_date", "trade_time", "toISOString", "toTimeString"):
        assert banned not in form


def test_api_day_boundary_one_second_either_side_of_session_midnight(api_client, monkeypatch):
    before = datetime(2026, 10, 4, 23, 59, 59, tzinfo=NEW_YORK)
    after = before + timedelta(seconds=1)

    _freeze(monkeypatch, before)
    t_before = _post_trade(api_client)
    _freeze(monkeypatch, after)
    t_after = _post_trade(api_client)

    assert (t_before["trade_date"], t_before["trade_time"]) == ("2026-10-04", "23:59:59")
    assert (t_after["trade_date"], t_after["trade_time"]) == ("2026-10-05", "00:00:00")


# ---------------------------------------------------------------------------
# Read path: "Today P/L"
# ---------------------------------------------------------------------------

def test_today_r_total_default_uses_the_session_local_date_not_utc(api_client, monkeypatch):
    _freeze(monkeypatch, NY_LATE_SUNDAY)
    local_today = _post_trade(api_client)
    _close(api_client, local_today["id"], r_multiple=2.0)

    _freeze(monkeypatch, datetime(2026, 10, 5, 9, 0, tzinfo=NEW_YORK))
    next_day = _post_trade(api_client)
    _close(api_client, next_day["id"], r_multiple=-1.0)

    _freeze(monkeypatch, NY_LATE_SUNDAY)
    # UTC's "today" at this instant is 2026-10-05, which would return -1.0.
    assert trades_repo.today_r_total() == 2.0


def test_today_r_total_explicit_day_argument_is_unchanged(api_client, monkeypatch):
    _freeze(monkeypatch, NY_LATE_SUNDAY)
    trade = _post_trade(api_client)
    _close(api_client, trade["id"], r_multiple=1.5)
    assert trades_repo.today_r_total("2026-10-04") == 1.5
    assert trades_repo.today_r_total("2026-10-05") == 0.0


# ---------------------------------------------------------------------------
# End to end: API write -> digest period assignment (real code path)
# ---------------------------------------------------------------------------

def test_near_midnight_trades_land_in_the_digest_week_of_their_local_date(api_client, monkeypatch):
    """Sunday 23:55 New York belongs to the week Mon 2026-09-28..Sun 10-04;
    Monday 00:05 New York belongs to the next week. Before the fix the
    Sunday trade was stored with the UTC date (Monday) and fell out of its
    own week's digest."""
    _freeze(monkeypatch, NY_LATE_SUNDAY)
    sunday = _post_trade(api_client)
    _close(api_client, sunday["id"], r_multiple=2.0)

    _freeze(monkeypatch, datetime(2026, 10, 5, 0, 5, tzinfo=NEW_YORK))
    monday = _post_trade(api_client)
    _close(api_client, monday["id"], r_multiple=-1.0)

    summary = digest_service.build_digest(DigestType.WEEKLY, reference=date(2026, 10, 5))
    assert (summary.period_start, summary.period_end) == (date(2026, 9, 28), date(2026, 10, 5))
    assert summary.overview.total_trades == 1
    assert summary.overview.total_r == 2.0

    next_week = digest_service.build_digest(DigestType.WEEKLY, reference=date(2026, 10, 12))
    assert next_week.overview.total_trades == 1
    assert next_week.overview.total_r == -1.0


# ---------------------------------------------------------------------------
# Streamlit entry path
# ---------------------------------------------------------------------------

def test_streamlit_form_defaults_come_from_session_now_not_the_machine_clock():
    """ui/journal.py's date/time pickers stay editable (backfilling is a
    legitimate use) but their default must be the same journal clock the
    API path uses, never the machine's local date.today()/datetime.now()."""
    from ui import journal as ui_journal
    source = inspect.getsource(ui_journal.render_new_trade_form)
    assert "trades_repo.session_now()" in source
    for banned in ("date.today()", "datetime.now("):
        assert banned not in source
