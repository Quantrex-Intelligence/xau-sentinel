"""Tests for ai/tools/risk_tools.py: get_risk_status traces to
risk.fundednext.compute_status() (the same settings resolution
api/routes/fundednext.py uses); get_open_positions is the Stage 6-new
capability wrapping mt5.account.get_open_positions()."""
from ai.tools import risk_tools


def test_get_risk_status_returns_data_in_mock_mode():
    result = risk_tools.get_risk_status({})
    assert result.data_available is True
    assert result.data["safety_level"] in ("SAFE", "WARNING", "CRITICAL", "BREACHED")
    assert result.timestamp is not None


def test_get_risk_status_degrades_when_account_snapshot_unavailable(monkeypatch):
    import config
    from mt5 import account as mt5_account
    from risk.models import AccountSnapshot

    monkeypatch.setattr(config, "IS_MOCK", False)
    monkeypatch.setattr(mt5_account, "mt5", None)

    result = risk_tools.get_risk_status({})
    assert result.data_available is False
    assert result.reason


def test_get_open_positions_returns_a_list_in_mock_mode():
    result = risk_tools.get_open_positions({})
    assert result.data_available is True
    assert isinstance(result.data["positions"], list)


def test_get_open_positions_unavailable_when_mt5_disconnected(monkeypatch):
    import config
    from mt5 import account as mt5_account

    monkeypatch.setattr(config, "IS_MOCK", False)
    monkeypatch.setattr(mt5_account, "mt5", None)

    result = risk_tools.get_open_positions({})
    assert result.data_available is False
    assert result.reason
