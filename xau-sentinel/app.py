"""XAU Sentinel — a personal, read-only XAUUSD analysis, setup-alert, and
trading journal app. It connects to MT5, watches the market, flags when a
configured setup is developing, and journals trades. It never places,
closes, or modifies an order — all trading decisions stay manual.
"""
from datetime import datetime, timezone

import streamlit as st

import config
from mt5 import connection, market_data
from analysis.structure import analyze_structure, detect_displacement
from analysis.regime import classify_regime
from analysis.zones import compute_zones, current_session
from analysis.liquidity import detect_sweeps, detect_equal_levels
from analysis.setup import detect_setup
from journal.database import init_db
from journal import trades as trades_repo
from ui import dashboard
from ui.journal import render_journal_page

st.set_page_config(page_title="XAU Sentinel", page_icon="📈", layout="wide")
dashboard.inject_css()

init_db()

if config.IS_LIVE and not connection.is_connected():
    connection.connect()

conn_label, conn_ok = connection.status_label()


def _load_market_data():
    try:
        candles = market_data.get_all_candles(300)
        price_info = market_data.get_price_info()
        return candles, price_info, None
    except market_data.MarketDataError as exc:
        return None, None, str(exc)


def _log_new_events(setup_result, sweeps, equal_levels, m5_struct, displacement):
    """Writes newly-seen liquidity/MSS/displacement events to the DB, deduped
    within this browser session so a stable rerun doesn't spam the feed (and,
    per BUG-2 in the Stage 1 report, deduped again at the DB level in
    log_event so a fresh session can't re-log the same historical event)."""
    seen = st.session_state.setdefault("seen_event_keys", set())

    for sweep in sweeps:
        key = ("sweep", sweep.label, sweep.time.isoformat())
        if key not in seen:
            seen.add(key)
            trades_repo.log_event("liquidity", sweep.label, "M5", sweep.time.to_pydatetime())

    for equal in equal_levels:
        key = ("equal_level", equal.label, equal.level_price, equal.time.isoformat())
        if key not in seen:
            seen.add(key)
            trades_repo.log_event("liquidity", f"{equal.label} ({equal.level_price:.2f})", "M5",
                                   equal.time.to_pydatetime())

    if m5_struct.last_mss and m5_struct.last_mss != st.session_state.get("last_m5_mss"):
        trades_repo.log_event("mss", f"{m5_struct.last_mss.title()} MSS confirmed", "M5")
    st.session_state["last_m5_mss"] = m5_struct.last_mss

    if displacement and displacement != st.session_state.get("last_displacement"):
        trades_repo.log_event("displacement", f"{displacement.title()} displacement detected", "M5")
    st.session_state["last_displacement"] = displacement


def _log_setup_transition(setup_result):
    """Alerts only on a state change, not on every rerun."""
    prev_state = st.session_state.get("last_setup_state")
    prev_direction = st.session_state.get("last_setup_direction")

    changed = setup_result.state != prev_state or setup_result.direction != prev_direction
    if changed and setup_result.state in ("DEVELOPING", "VALID", "INVALIDATED"):
        if setup_result.state == "VALID":
            message = (f"{setup_result.direction} setup valid — entry {setup_result.entry_zone}, "
                       f"SL {setup_result.stop_loss}, TP {setup_result.take_profit}, RR 1:{setup_result.rr}")
        else:
            message = setup_result.reason
        trades_repo.log_alert(setup_result.state.lower(), message, setup_result.direction or "",
                               details=setup_result.checklist)

    st.session_state["last_setup_state"] = setup_result.state
    st.session_state["last_setup_direction"] = setup_result.direction


def render_alert_banner(setup_result):
    if setup_result.state == "DEVELOPING":
        st.warning(f"🟡 **{config.TRADING_SYMBOL} SETUP DEVELOPING** — {setup_result.reason}")
    elif setup_result.state == "VALID":
        st.success(
            f"🟢 **{config.TRADING_SYMBOL} VALID SETUP** — Direction: {setup_result.direction}  \n"
            f"Entry Zone: {setup_result.entry_zone[0]:.2f}–{setup_result.entry_zone[1]:.2f} · "
            f"SL: {setup_result.stop_loss:.2f} · TP: {setup_result.take_profit:.2f} · RR: 1:{setup_result.rr}"
        )
    elif setup_result.state == "INVALIDATED":
        st.error(f"🔴 **{config.TRADING_SYMBOL} SETUP INVALIDATED** — {setup_result.reason}")


with st.sidebar:
    st.markdown("## XAU Sentinel")
    page = st.radio("Navigation", ["Dashboard", "Journal"], label_visibility="collapsed")
    st.divider()
    if st.button("🔄 Refresh"):
        st.rerun()
    st.caption(f"Mode: {'MOCK' if config.IS_MOCK else 'LIVE'}")
    st.caption(f"Symbol: {config.TRADING_SYMBOL}")

candles, price_info, data_error = _load_market_data()
is_stale = market_data.is_stale(price_info) if price_info else False
dashboard.render_header(price_info, conn_label, conn_ok, is_stale)

context_snapshot = {}

if data_error:
    st.error(f"Market data unavailable: {data_error}. Check your MT5 terminal/login, or switch MODE=mock.")
else:
    structures = {tf: analyze_structure(candles[tf]) for tf in market_data.TIMEFRAMES}
    regime = classify_regime(candles["H1"], candles["M15"])
    zones = compute_zones(candles["M5"], candles["H1"], candles["H4"])
    sweeps = detect_sweeps(candles["M5"], zones)
    equal_levels = detect_equal_levels(candles["M5"])
    displacement = detect_displacement(candles["M5"])
    setup_result = detect_setup(candles)

    _log_new_events(setup_result, sweeps, equal_levels, structures["M5"], displacement)
    _log_setup_transition(setup_result)

    now_utc = datetime.now(timezone.utc)
    context_snapshot = {
        "h4_bias": structures["H4"].state,
        "h1_bias": structures["H1"].state,
        "m15_bias": structures["M15"].state,
        "m5_bias": structures["M5"].state,
        "regime": regime.regime,
        "session": current_session(now_utc),
        "liquidity": sweeps[-1].label if sweeps else None,
        "equal_levels": equal_levels[-1].label if equal_levels else None,
        "mss": (structures["M5"].last_mss or "").title() or None,
        "displacement": (displacement or "").title() or None,
    }

    if page == "Dashboard":
        col_chart, col_market = st.columns([3, 1])
        with col_chart:
            dashboard.render_chart(candles["M5"], zones)
        with col_market:
            dashboard.render_market_panel(structures, regime)

        render_alert_banner(setup_result)
        dashboard.render_setup_panel(setup_result)

        col_zones, col_risk, col_events = st.columns(3)
        with col_zones:
            dashboard.render_zones_panel(zones)
        with col_risk:
            dashboard.render_risk_panel(trades_repo.today_r_total())
        with col_events:
            dashboard.render_events_panel(trades_repo.recent_events(), trades_repo.recent_alerts())

if page == "Journal":
    if data_error:
        st.warning("Market context can't be captured automatically right now — live analysis is unavailable.")
    render_journal_page(context_snapshot)
