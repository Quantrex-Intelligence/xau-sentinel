"""Tests for ai/notifications/formatter.py — deterministic, per-type
rendering. Every alert type gets its own test proving the real payload
fields (not invented ones) appear in the message, no fabricated fields,
no trading-directive language, quality labels rendered honestly, and an
unrecognized future type falls back to a safe generic formatter."""
from ai.monitoring.models import AlertEvent, AlertType, Severity
from ai.notifications.formatter import format_alert

_TS = "2026-01-01T00:00:00+00:00"


def _alert(alert_type, severity=Severity.INFO, payload=None, **overrides):
    defaults = dict(
        type=alert_type, severity=severity, title="Title", message="Message",
        dedup_key="k", payload=payload or {}, symbol="XAUUSD", timestamp=_TS,
    )
    defaults.update(overrides)
    return AlertEvent(**defaults)


def test_setup_state_changed_renders_real_fields():
    alert = _alert(AlertType.SETUP_STATE_CHANGED, payload={
        "previous_state": "NO SETUP", "current_state": "DEVELOPING", "direction": "BUY",
        "checklist": {"Liquidity Sweep": True}, "reason": "H1 bullish bias confirmed.",
    })
    text = format_alert(alert)
    assert "NO SETUP" in text
    assert "DEVELOPING" in text
    assert "BUY" in text
    assert "H1 bullish bias confirmed." in text


def test_aplus_detected_renders_real_fields_and_no_fabricated_ones():
    alert = _alert(AlertType.APLUS_SETUP_DETECTED, payload={
        "direction": "BUY", "entry": 3700.0, "stop_loss": 3690.0, "target": 3730.0, "rr": 3.0,
        "rating": "A+", "criteria": [{"name": "Liquidity Sweep", "evidence": "swept PDL"}],
        "fundednext_safety_level": "SAFE",
    })
    text = format_alert(alert)
    assert "BUY" in text
    assert "3700.0" in text
    assert "3690.0" in text
    assert "3730.0" in text
    assert "1:3.0" in text
    assert "swept PDL" in text
    assert "SAFE" in text
    assert "🟢" in text


def test_aplus_detected_does_not_invent_missing_optional_fields():
    alert = _alert(AlertType.APLUS_SETUP_DETECTED, payload={"direction": "BUY"})
    text = format_alert(alert)
    assert "unavailable" in text.lower()


def test_aplus_invalidated_renders_reason_and_emoji():
    alert = _alert(AlertType.APLUS_SETUP_INVALIDATED, payload={
        "previous_direction": "BUY", "invalidation": "Opposing M5 MSS", "rating": "INVALID",
    })
    text = format_alert(alert)
    assert "Opposing M5 MSS" in text
    assert "🔴" in text


def test_risk_status_changed_renders_metrics():
    alert = _alert(AlertType.RISK_STATUS_CHANGED, severity=Severity.CRITICAL, payload={
        "previous_status": "SAFE", "current_status": "CRITICAL",
        "daily_loss_used_pct": 42.5, "max_drawdown_used_pct": 30.0, "reason": "Daily loss threshold breached.",
    })
    text = format_alert(alert)
    assert "SAFE" in text
    assert "CRITICAL" in text
    assert "42.5" in text
    assert "Daily loss threshold breached." in text
    assert "🔴" in text  # CRITICAL severity


def test_risk_status_changed_emoji_reflects_severity_not_a_fixed_type_color():
    info_alert = _alert(AlertType.RISK_STATUS_CHANGED, severity=Severity.INFO, payload={
        "previous_status": "CRITICAL", "current_status": "SAFE",
    })
    assert "🟢" in format_alert(info_alert)


def test_market_intelligence_quality_changed_renders_real_quality_labels():
    alert = _alert(AlertType.MARKET_INTELLIGENCE_QUALITY_CHANGED, severity=Severity.WARNING, payload={
        "previous_quality": "AVAILABLE", "current_quality": "PARTIALLY_AVAILABLE",
        "macro_quality": "GOOD", "cross_asset_quality": "DEGRADED", "news_quality": "UNAVAILABLE",
    })
    text = format_alert(alert)
    assert "GOOD" in text
    assert "DEGRADED" in text
    assert "UNAVAILABLE" in text
    assert "PARTIALLY_AVAILABLE" in text


def test_high_impact_event_near_renders_proximity_never_a_prediction():
    alert = _alert(AlertType.HIGH_IMPACT_EVENT_NEAR, severity=Severity.WARNING, payload={
        "event": "FOMC Rate Decision", "country": "US", "importance": "HIGH", "event_time": _TS,
        "status": "UPCOMING", "minutes_until": 12, "assets": ["XAUUSD", "USD"], "source": "real",
    })
    text = format_alert(alert)
    assert "FOMC Rate Decision" in text
    assert "US" in text
    assert "12" in text
    assert "🟡" in text
    lowered = text.lower()
    assert "will" not in lowered
    assert "forecast" not in lowered


def test_no_formatted_message_contains_trading_directive_language():
    payloads = [
        (AlertType.SETUP_STATE_CHANGED, {"previous_state": "NO SETUP", "current_state": "DEVELOPING"}),
        (AlertType.APLUS_SETUP_DETECTED, {"direction": "BUY", "entry": 3700.0}),
        (AlertType.APLUS_SETUP_INVALIDATED, {"invalidation": "reason"}),
        (AlertType.RISK_STATUS_CHANGED, {"previous_status": "SAFE", "current_status": "WARNING"}),
        (AlertType.MARKET_INTELLIGENCE_QUALITY_CHANGED, {"previous_quality": "AVAILABLE", "current_quality": "UNAVAILABLE"}),
        (AlertType.HIGH_IMPACT_EVENT_NEAR, {"event": "US CPI", "minutes_until": 5}),
    ]
    banned = ("buy now", "sell now", "gold will rise", "fed will cut", "cpi will beat", "guaranteed")
    for alert_type, payload in payloads:
        text = format_alert(_alert(alert_type, payload=payload)).lower()
        for phrase in banned:
            assert phrase not in text


def test_generic_fallback_for_unknown_alert_type_never_crashes():
    class _FakeUnknownType:
        value = "SOMETHING_NEW"
    alert = AlertEvent(
        type=_FakeUnknownType(), severity=Severity.INFO, title="A new kind of alert",
        message="Something happened.", dedup_key="k", payload={}, symbol="XAUUSD", timestamp=_TS,
    )
    text = format_alert(alert)
    assert "A new kind of alert" in text
    assert "Something happened." in text


def test_malformed_payload_falls_back_to_generic_instead_of_raising():
    alert = _alert(AlertType.APLUS_SETUP_DETECTED, payload={"criteria": "not-a-list"}, title="Fallback title")
    text = format_alert(alert)
    assert "Fallback title" in text
