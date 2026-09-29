"""Deterministic Telegram message formatting (Stage 14) — never calls an
LLM, never asks whether an alert is worth sending (that was already
decided by ai/monitoring/rules.py). Reads only fields Stage 13's rules
already put in AlertEvent.payload; never invents a missing value.

One branch per AlertType, matching the spec's own example message shapes.
An unrecognized future AlertType renders through _format_generic() rather
than raising — the delivery worker must never crash because a new alert
type was added upstream without a matching formatter branch yet.
"""
from ai.monitoring.models import AlertEvent, AlertType, Severity

_SEVERITY_EMOJI = {Severity.INFO: "\U0001F7E2", Severity.WARNING: "\U0001F7E1", Severity.CRITICAL: "\U0001F534"}

_TYPE_EMOJI = {
    AlertType.APLUS_SETUP_DETECTED: "\U0001F7E2",
    AlertType.APLUS_SETUP_INVALIDATED: "\U0001F534",
    AlertType.HIGH_IMPACT_EVENT_NEAR: "\U0001F7E1",
}


def _emoji(alert: AlertEvent) -> str:
    return _TYPE_EMOJI.get(alert.type) or _SEVERITY_EMOJI.get(alert.severity, "ℹ️")


def _fmt(value) -> str:
    return "unavailable" if value is None else str(value)


def _format_setup_state_changed(alert: AlertEvent) -> str:
    p = alert.payload
    lines = [
        f"{_emoji(alert)} {alert.symbol} SETUP STATE CHANGED", "",
        f"Previous state: {_fmt(p.get('previous_state'))}",
        f"Current state: {_fmt(p.get('current_state'))}",
        f"Direction: {_fmt(p.get('direction'))}",
    ]
    if p.get("reason"):
        lines += ["", "Reason:", p["reason"]]
    return "\n".join(lines)


def _format_aplus_detected(alert: AlertEvent) -> str:
    p = alert.payload
    criteria = p.get("criteria") or []
    lines = [
        f"{_emoji(alert)} {alert.symbol} A+ SETUP DETECTED", "",
        f"Direction: {_fmt(p.get('direction'))}",
        f"Entry: {_fmt(p.get('entry'))}",
        f"SL: {_fmt(p.get('stop_loss'))}",
        f"TP: {_fmt(p.get('target'))}",
        f"R:R: 1:{_fmt(p.get('rr'))}",
        f"Rating: {_fmt(p.get('rating'))}",
    ]
    if criteria:
        lines += ["", "Technical:"]
        lines += [f"• {c.get('name')}: {c.get('evidence')}" for c in criteria]
    lines += ["", "Risk:", f"FundedNext: {_fmt(p.get('fundednext_safety_level'))}"]
    return "\n".join(lines)


def _format_aplus_invalidated(alert: AlertEvent) -> str:
    p = alert.payload
    lines = [
        f"{_emoji(alert)} {alert.symbol} A+ SETUP INVALIDATED", "",
        "Reason:", _fmt(p.get("invalidation")), "",
        f"Previous direction: {_fmt(p.get('previous_direction'))}",
    ]
    return "\n".join(lines)


def _format_risk_status_changed(alert: AlertEvent) -> str:
    p = alert.payload
    lines = [
        f"{_emoji(alert)} FUNDEDNEXT RISK STATUS CHANGED", "",
        f"Previous status: {_fmt(p.get('previous_status'))}",
        f"Current status: {_fmt(p.get('current_status'))}",
        f"Daily loss used: {_fmt(p.get('daily_loss_used_pct'))}%",
        f"Max drawdown used: {_fmt(p.get('max_drawdown_used_pct'))}%",
    ]
    if p.get("reason"):
        lines += ["", "Reason:", p["reason"]]
    return "\n".join(lines)


def _format_mi_quality_changed(alert: AlertEvent) -> str:
    p = alert.payload
    lines = [
        f"{_emoji(alert)} MARKET INTELLIGENCE QUALITY CHANGED", "",
        f"Previous: {_fmt(p.get('previous_quality'))}",
        f"Current: {_fmt(p.get('current_quality'))}", "",
        "By category:",
        f"Macro: {_fmt(p.get('macro_quality'))}",
        f"Cross-asset: {_fmt(p.get('cross_asset_quality'))}",
        f"News: {_fmt(p.get('news_quality'))}",
    ]
    return "\n".join(lines)


def _format_high_impact_event_near(alert: AlertEvent) -> str:
    p = alert.payload
    assets = p.get("assets") or []
    lines = [
        f"{_emoji(alert)} HIGH-IMPACT EVENT NEAR", "",
        f"Event: {_fmt(p.get('event'))}",
        f"Country: {_fmt(p.get('country'))}",
        f"Importance: {_fmt(p.get('importance'))}", "",
        f"Time: {_fmt(p.get('event_time'))}",
        f"Status: {_fmt(p.get('status'))}",
        f"Minutes until: {_fmt(p.get('minutes_until'))}", "",
        f"Assets: {', '.join(assets) if assets else 'unavailable'}",
        f"Source: {_fmt(p.get('source'))}",
    ]
    return "\n".join(lines)


def _format_generic(alert: AlertEvent) -> str:
    return f"{_emoji(alert)} {alert.title}\n\n{alert.message}"


_FORMATTERS = {
    AlertType.SETUP_STATE_CHANGED: _format_setup_state_changed,
    AlertType.APLUS_SETUP_DETECTED: _format_aplus_detected,
    AlertType.APLUS_SETUP_INVALIDATED: _format_aplus_invalidated,
    AlertType.RISK_STATUS_CHANGED: _format_risk_status_changed,
    AlertType.MARKET_INTELLIGENCE_QUALITY_CHANGED: _format_mi_quality_changed,
    AlertType.HIGH_IMPACT_EVENT_NEAR: _format_high_impact_event_near,
}


def _with_explanation_footer(text: str, alert: AlertEvent) -> str:
    """Stage 15: a plain, informational pointer to the in-app explanation
    for this alert — never a Telegram-side control channel (no bot
    commands, nothing triggers generation from here)."""
    if alert.id is None:
        return text
    return f"{text}\n\nAlert ID: {alert.id}\n\nOpen XAU Sentinel to view explanation."


def format_alert(alert: AlertEvent) -> str:
    formatter = _FORMATTERS.get(alert.type, _format_generic)
    try:
        text = formatter(alert)
    except Exception:  # noqa: BLE001 - a malformed/unexpected payload must never crash delivery
        text = _format_generic(alert)
    return _with_explanation_footer(text, alert)
