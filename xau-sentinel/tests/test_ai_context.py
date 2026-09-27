"""Tests for the deterministic AI context builder (ai/context.py). Every
assertion checks that a section is either genuinely populated from the real
engine output, or explicitly marked unavailable with the engine's own
reason — never a fabricated fact."""
from unittest.mock import Mock

import pytest

import config
from ai import context
from journal import trades as trades_repo
from mt5 import account as mt5_account, market_data
from risk.fundednext_journal import init_table as init_fundednext_table, save_snapshot as save_fn_snapshot
from risk.models import AccountSnapshot, AccountType, FundedNextStatus, Phase, SafetyLevel


@pytest.fixture(autouse=True)
def _fundednext_table(temp_db):
    """build_trade_section() reads the fundednext_context table; temp_db
    alone only creates the frozen Stage 1 schema (journal/database.py), so
    every test in this file also needs risk.fundednext_journal's own
    migration — exactly what api/main.py's lifespan does for the real app."""
    init_fundednext_table()


def test_market_and_setup_sections_available_in_mock_mode():
    assembled = context.build_context(["market"])
    labels = {s.label: s for s in assembled.sections}

    assert set(labels) == {context.MARKET_LABEL, context.SETUP_LABEL}
    assert labels[context.MARKET_LABEL].available is True
    assert "Price:" in labels[context.MARKET_LABEL].text
    assert "H1 structure:" in labels[context.MARKET_LABEL].text
    assert labels[context.SETUP_LABEL].available is True
    assert "Setup state:" in labels[context.SETUP_LABEL].text


def test_market_and_setup_sections_unavailable_when_mt5_disconnected(monkeypatch):
    """Mirrors tests/test_market_data.py's own disconnected-MT5 pattern —
    the context builder must degrade the same way the rest of the app does,
    never crash and never invent a price."""
    monkeypatch.setattr(config, "IS_MOCK", False)
    monkeypatch.setattr(market_data, "mt5", None)

    assembled = context.build_context(["market"])
    labels = {s.label: s for s in assembled.sections}

    assert labels[context.MARKET_LABEL].available is False
    assert labels[context.SETUP_LABEL].available is False
    assert "MT5" in labels[context.MARKET_LABEL].text or "not connected" in labels[context.MARKET_LABEL].text.lower()
    # The rendered block must say UNAVAILABLE, not silently omit the section.
    rendered = assembled.render()
    assert f"UNAVAILABLE — {labels[context.MARKET_LABEL].text}" in rendered
    assert context.MARKET_LABEL not in assembled.used_labels


def test_risk_section_reports_fundednext_status_in_mock_mode():
    section = context.build_risk_section()
    assert section.available is True
    assert "Balance:" in section.text
    assert "Daily loss remaining:" in section.text
    assert "Safety level:" in section.text


def test_risk_section_unavailable_when_fundednext_data_missing(monkeypatch):
    monkeypatch.setattr(
        mt5_account, "get_account_snapshot",
        Mock(return_value=AccountSnapshot(balance=0, equity=0, source="live",
                                           available=False, error="MT5 not connected")),
    )
    section = context.build_risk_section()
    assert section.available is False
    assert "not connected" in section.text.lower()
    # Never fabricate a balance/equity figure when the source says unavailable.
    assert "Balance:" not in section.text


def test_journal_section_unavailable_when_no_trades(temp_db):
    section = context.build_journal_section()
    assert section.available is False
    assert section.detail == "0 trades"


def test_journal_section_reports_recent_trades_and_analytics(temp_db):
    trade_id = trades_repo.create_trade(
        {"trade_date": "2026-01-05", "trade_time": "09:00:00", "symbol": "XAUUSD",
         "direction": "BUY", "session": "London", "entry": 100.0, "stop_loss": 95.0,
         "take_profit": 110.0, "planned_rr": 2.0, "setup": "Sweep+MSS", "market_regime": "TRENDING UP",
         "notes": None, "screenshot_path": None},
        {"h4_bias": "BULLISH", "h1_bias": "BULLISH", "m15_bias": "PULLBACK", "m5_bias": "BULLISH",
         "regime": "TRENDING UP", "liquidity": "PDL swept", "mss": "Bullish", "displacement": "Bullish",
         "session": "London"},
    )
    trades_repo.close_trade(trade_id, {
        "exit_price": 110.0, "result": "WIN", "pnl": 1000, "r_multiple": 2.0,
        "duration_minutes": 45, "exit_reason": "Hit TP", "rule_followed": "Yes",
        "mistake": None, "exit_notes": None,
    })

    section = context.build_journal_section()
    assert section.available is True
    assert "Total closed trades: 1" in section.text
    assert "Win rate: 100.0%" in section.text
    assert "Sweep+MSS" in section.text
    assert "WIN" in section.text
    assert section.detail == "1 trades · 100.0% win rate"


def test_default_scope_excludes_journal():
    """"Do not send unnecessary data to the LLM" — journal history is the
    heaviest section and must be opt-in, not default."""
    assembled = context.build_context(None)
    assert context.JOURNAL_LABEL not in {s.label for s in assembled.sections}
    assert {s.label for s in assembled.sections} == {context.MARKET_LABEL, context.SETUP_LABEL, context.RISK_LABEL}


def test_journal_included_only_when_requested(temp_db):
    assembled = context.build_context(["journal"])
    assert {s.label for s in assembled.sections} == {context.JOURNAL_LABEL}


def test_unknown_scope_names_are_ignored_not_rejected():
    assembled = context.build_context(["market", "not-a-real-scope"])
    assert {s.label for s in assembled.sections} == {context.MARKET_LABEL, context.SETUP_LABEL}


def test_empty_or_all_unknown_scope_falls_back_to_default():
    assembled = context.build_context(["nonsense"])
    assert {s.label for s in assembled.sections} == {context.MARKET_LABEL, context.SETUP_LABEL, context.RISK_LABEL}


def test_trade_context_unavailable_for_unknown_trade_id(temp_db):
    section = context.build_trade_section(999)
    assert section.available is False
    assert "999" in section.text


def test_trade_context_uses_captured_entry_data_not_live_market(temp_db):
    trade_id = trades_repo.create_trade(
        {"trade_date": "2026-01-05", "trade_time": "09:00:00", "symbol": "XAUUSD",
         "direction": "BUY", "session": "London", "entry": 100.0, "stop_loss": 95.0,
         "take_profit": 110.0, "planned_rr": 2.0, "setup": "Sweep+MSS", "market_regime": "TRENDING UP",
         "notes": "Took it on confluence.", "screenshot_path": None},
        {"h4_bias": "BULLISH", "h1_bias": "BULLISH", "m15_bias": "PULLBACK", "m5_bias": "BULLISH",
         "regime": "TRENDING UP", "liquidity": "PDL swept", "mss": "Bullish", "displacement": "Bullish",
         "session": "London"},
    )

    section = context.build_trade_section(trade_id)
    assert section.available is True
    assert "captured at entry (NOT the current live market)" in section.text
    assert "H1 BULLISH" in section.text
    assert "PDL swept" in section.text
    assert "Took it on confluence." in section.text
    assert "still OPEN" in section.text


def test_trade_context_includes_immutable_fundednext_snapshot(temp_db):
    trade_id = trades_repo.create_trade(
        {"trade_date": "2026-01-05", "trade_time": "09:00:00", "symbol": "XAUUSD",
         "direction": "BUY", "session": "London", "entry": 100.0, "stop_loss": 95.0,
         "take_profit": 110.0, "planned_rr": 2.0, "setup": None, "market_regime": None,
         "notes": None, "screenshot_path": None},
        {"h4_bias": None, "h1_bias": None, "m15_bias": None, "m5_bias": None,
         "regime": None, "liquidity": None, "mss": None, "displacement": None, "session": "London"},
    )
    save_fn_snapshot(
        trade_id,
        FundedNextStatus(account_type=AccountType.STELLAR_2STEP, phase=Phase.CHALLENGE, mode="mock",
                          data_available=True, balance=50_000.0, equity=50_100.0,
                          daily_loss_remaining=2_600.0, max_drawdown_remaining=5_100.0,
                          safety_level=SafetyLevel.SAFE, reason="All FundedNext limits within safe range."),
        rules_daily_loss_pct=0.05, rules_max_loss_pct=0.10,
    )

    section = context.build_trade_section(trade_id)
    assert "FundedNext account snapshot at entry" in section.text
    assert "50000.0" in section.text or "50000" in section.text


def test_trade_id_replaces_scope_entirely(temp_db):
    """Explaining a past trade must never be blended with today's live
    market/risk state."""
    trade_id = trades_repo.create_trade(
        {"trade_date": "2026-01-05", "trade_time": "09:00:00", "symbol": "XAUUSD",
         "direction": "BUY", "session": "London", "entry": 100.0, "stop_loss": 95.0,
         "take_profit": 110.0, "planned_rr": 2.0, "setup": None, "market_regime": None,
         "notes": None, "screenshot_path": None},
        {"h4_bias": None, "h1_bias": None, "m15_bias": None, "m5_bias": None,
         "regime": None, "liquidity": None, "mss": None, "displacement": None, "session": "London"},
    )
    assembled = context.build_context(["market", "risk", "journal"], trade_id=trade_id)
    assert {s.label for s in assembled.sections} == {context.TRADE_LABEL}


def test_deterministic_context_generation():
    """Same inputs -> byte-identical context text. Mock market data is
    seeded deterministically per timeframe (see mt5/market_data.py), so two
    back-to-back builds within the same instant must match exactly."""
    first = context.build_context(["market", "risk"]).render()
    second = context.build_context(["market", "risk"]).render()
    assert first == second
