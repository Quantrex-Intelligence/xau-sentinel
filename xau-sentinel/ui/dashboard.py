"""Dashboard page: header status bar, chart, market structure, setup status,
key zones, risk display, and recent events — a read-only trading terminal."""
import streamlit as st

import config
from ui.chart import build_candlestick_chart

_STATE_COLORS = {
    "BULLISH": "#26a69a", "BEARISH": "#ef5350", "RANGING": "#8a8f98", "PULLBACK": "#e0a339",
    "TRENDING UP": "#26a69a", "TRENDING DOWN": "#ef5350", "BREAKOUT": "#61afef",
    "HIGH VOLATILITY": "#c678dd", "LOW VOLATILITY": "#8a8f98",
}

_SETUP_COLORS = {
    "NO SETUP": ("#8a8f98", "⚪"),
    "DEVELOPING": ("#e0a339", "🟡"),
    "VALID": ("#26a69a", "🟢"),
    "INVALIDATED": ("#ef5350", "🔴"),
}


def inject_css():
    st.markdown(
        """
        <style>
        .stApp { background-color: #0d1117; }
        .xs-card-title {
            margin: 0 0 12px 0; font-size: 13px; letter-spacing: 0.06em;
            color: #8a8f98; text-transform: uppercase; font-weight: 600;
        }
        .xs-badge {
            display: inline-block; padding: 2px 10px; border-radius: 4px;
            font-size: 12px; font-weight: 700; color: #0d1117;
        }
        .xs-row { display: flex; justify-content: space-between; align-items: center; padding: 5px 0;
                   border-bottom: 1px solid #1c2129; font-size: 14px; }
        .xs-row:last-child { border-bottom: none; }
        .xs-label { color: #8a8f98; }
        .xs-value { color: #d1d4dc; font-weight: 600; font-variant-numeric: tabular-nums; }
        .xs-event { font-size: 13px; padding: 4px 0; color: #d1d4dc; border-bottom: 1px solid #1c2129; }
        .xs-event-time { color: #8a8f98; margin-right: 8px; }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_header(price_info: dict, conn_label: str, conn_ok: bool, is_stale: bool = False):
    mode_label = "🟡 MOCK DATA" if config.IS_MOCK else "🟢 LIVE MT5"
    col1, col2, col3, col4 = st.columns([3, 1.4, 1.6, 1.6])
    with col1:
        st.markdown("### XAU SENTINEL")
    with col2:
        st.markdown(f"**{mode_label}**")
    with col3:
        color = "#26a69a" if conn_ok else "#ef5350"
        st.markdown(f"<span style='color:{color}; font-weight:700'>{conn_label}</span>", unsafe_allow_html=True)
    with col4:
        if price_info:
            st.markdown(f"**{config.TRADING_SYMBOL} {price_info['price']:.2f}**")

    if is_stale:
        st.warning(
            f"🟠 **DATA STALE** — last update {price_info['time'].strftime('%H:%M:%S UTC')}. "
            "The price shown below is no longer current."
        )

    if price_info:
        b1, b2, b3, b4 = st.columns(4)
        b1.metric("Bid", f"{price_info['bid']:.2f}")
        b2.metric("Ask", f"{price_info['ask']:.2f}")
        b3.metric("Spread", f"{price_info['spread']:.2f}")
        b4.metric("Last Candle (UTC)", price_info["time"].strftime("%H:%M:%S"))
    st.divider()


def _badge(text: str, color: str) -> str:
    return f"<span class='xs-badge' style='background-color:{color}'>{text}</span>"


def _card_title(text: str):
    st.markdown(f"<div class='xs-card-title'>{text}</div>", unsafe_allow_html=True)


def render_market_panel(structures: dict, regime):
    with st.container(border=True):
        _card_title("Market")
        for tf in ["H4", "H1", "M15", "M5"]:
            state = structures[tf].state
            color = _STATE_COLORS.get(state, "#8a8f98")
            st.markdown(
                f"<div class='xs-row'><span class='xs-label'>{tf}</span>{_badge(state, color)}</div>",
                unsafe_allow_html=True,
            )
        st.markdown("<div style='height:14px'></div>", unsafe_allow_html=True)
        _card_title("Regime")
        regime_color = _STATE_COLORS.get(regime.regime, "#8a8f98")
        st.markdown(_badge(regime.regime, regime_color), unsafe_allow_html=True)
        st.caption(regime.reason)


def render_setup_panel(setup):
    color, icon = _SETUP_COLORS.get(setup.state, ("#8a8f98", "⚪"))
    with st.container(border=True):
        _card_title("Setup Status")

        direction_txt = f" — {setup.direction}" if setup.direction else ""
        st.markdown(
            f"<div style='font-size:20px; font-weight:700; color:{color}; margin-bottom:6px'>"
            f"{icon} {setup.state}{direction_txt}</div>",
            unsafe_allow_html=True,
        )
        st.caption(setup.reason)

        cols = st.columns(len(setup.checklist) or 1)
        for col, (step, done) in zip(cols, setup.checklist.items()):
            with col:
                if done is True:
                    st.markdown(f"**{step}**<br/><span style='color:#26a69a'>✓ Confirmed</span>",
                                unsafe_allow_html=True)
                else:
                    st.markdown(f"**{step}**<br/><span style='color:#8a8f98'>WAITING</span>",
                                unsafe_allow_html=True)

        if setup.state == "VALID":
            st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Entry Zone", f"{setup.entry_zone[0]:.2f}–{setup.entry_zone[1]:.2f}")
            c2.metric("Stop Loss", f"{setup.stop_loss:.2f}")
            c3.metric("Take Profit", f"{setup.take_profit:.2f}")
            c4.metric("R:R", f"1:{setup.rr}" if setup.rr else "—")
            st.caption("This is analysis only — you decide whether and how to execute.")


def render_zones_panel(zones: dict):
    with st.container(border=True):
        _card_title("Key Zones")
        if not zones:
            st.caption("Not enough data yet.")
        else:
            for name, price in zones.items():
                st.markdown(
                    f"<div class='xs-row'><span class='xs-label'>{name}</span>"
                    f"<span class='xs-value'>{price:.2f}</span></div>",
                    unsafe_allow_html=True,
                )


def render_risk_panel(today_pnl: float = 0.0):
    with st.container(border=True):
        _card_title("Risk")
        rows = [
            ("Balance", f"${config.ACCOUNT_BALANCE:,.0f}"),
            ("Risk / Trade", f"{config.RISK_PER_TRADE_PCT:.2f}%"),
            ("Today P/L", f"{'+' if today_pnl >= 0 else ''}{today_pnl:.2f}R"),
        ]
        for label, value in rows:
            st.markdown(
                f"<div class='xs-row'><span class='xs-label'>{label}</span>"
                f"<span class='xs-value'>{value}</span></div>",
                unsafe_allow_html=True,
            )
        st.caption("Informational only — this app never sizes or places trades.")


def render_events_panel(events_df, alerts_df):
    with st.container(border=True):
        _card_title("Recent Events")
        if events_df is None or events_df.empty:
            st.caption("No events yet this session.")
        else:
            for _, row in events_df.head(8).iterrows():
                ts = str(row["event_time"])[11:16] if len(str(row["event_time"])) > 16 else row["event_time"]
                st.markdown(
                    f"<div class='xs-event'><span class='xs-event-time'>{ts}</span>{row['description']}</div>",
                    unsafe_allow_html=True,
                )


def render_chart(candles_df, zones: dict):
    fig = build_candlestick_chart(candles_df, zones, title=f"{config.TRADING_SYMBOL} — M5")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})
