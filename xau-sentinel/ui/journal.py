"""Journal page: manual trade entry (with automatic market-context capture),
trade table + detail view, and simple analytics."""
from datetime import datetime, date, time
from pathlib import Path

import streamlit as st

import config
from journal import trades as trades_repo

SCREENSHOT_DIR = config.BASE_DIR / "data" / "screenshots"


def _save_screenshot(uploaded_file, trade_date: str) -> str:
    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    safe_name = f"{trade_date}_{uploaded_file.name}".replace(" ", "_")
    dest = SCREENSHOT_DIR / safe_name
    dest.write_bytes(uploaded_file.getbuffer())
    return str(dest)


def render_context_summary(context_snapshot: dict):
    st.caption("Captured automatically from current market analysis — nothing here needs to be typed.")
    cols = st.columns(4)
    labels = [
        ("H4 Bias", context_snapshot.get("h4_bias", "—")),
        ("H1 Bias", context_snapshot.get("h1_bias", "—")),
        ("M15 Bias", context_snapshot.get("m15_bias", "—")),
        ("M5 Bias", context_snapshot.get("m5_bias", "—")),
    ]
    for col, (label, value) in zip(cols, labels):
        col.metric(label, value)

    cols2 = st.columns(3)
    cols2[0].metric("Regime", context_snapshot.get("regime", "—"))
    cols2[1].metric("Session", context_snapshot.get("session", "—"))
    cols2[2].metric("Displacement", context_snapshot.get("displacement") or "None")
    st.caption(f"Liquidity: {context_snapshot.get('liquidity') or 'None detected'}")
    st.caption(f"MSS: {context_snapshot.get('mss') or 'None'}")


def render_new_trade_form(context_snapshot: dict):
    st.markdown("#### New Trade")
    render_context_summary(context_snapshot)
    st.divider()

    with st.form("new_trade_form", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        trade_date = c1.date_input("Date", value=date.today())
        trade_time = c2.time_input("Time", value=datetime.now().time().replace(microsecond=0))
        direction = c3.selectbox("Direction", ["BUY", "SELL"])

        c4, c5, c6 = st.columns(3)
        entry = c4.number_input("Entry", min_value=0.0, step=0.01, format="%.2f")
        stop_loss = c5.number_input("Stop Loss", min_value=0.0, step=0.01, format="%.2f")
        take_profit = c6.number_input("Take Profit", min_value=0.0, step=0.01, format="%.2f")

        planned_rr = None
        if entry and stop_loss and take_profit and entry != stop_loss:
            planned_rr = round(abs(take_profit - entry) / abs(entry - stop_loss), 2)

        c7, c8 = st.columns(2)
        setup_label = c7.text_input("Setup", placeholder="e.g. Sweep + MSS")
        c8.metric("Planned RR", f"1:{planned_rr}" if planned_rr else "—")

        notes = st.text_area("Notes", placeholder="Why did you take this trade?")
        screenshot = st.file_uploader("Screenshot", type=["png", "jpg", "jpeg"])

        submitted = st.form_submit_button("Save Trade", type="primary")

    if submitted:
        if not entry or not stop_loss:
            st.error("Entry and Stop Loss are required.")
            return

        screenshot_path = _save_screenshot(screenshot, trade_date.isoformat()) if screenshot else None

        data = {
            "trade_date": trade_date.isoformat(),
            "trade_time": trade_time.strftime("%H:%M:%S"),
            "symbol": config.TRADING_SYMBOL,
            "direction": direction,
            "session": context_snapshot.get("session"),
            "entry": entry,
            "stop_loss": stop_loss,
            "take_profit": take_profit or None,
            "planned_rr": planned_rr,
            "setup": setup_label or None,
            "market_regime": context_snapshot.get("regime"),
            "notes": notes or None,
            "screenshot_path": screenshot_path,
        }
        context = {
            "h4_bias": context_snapshot.get("h4_bias"),
            "h1_bias": context_snapshot.get("h1_bias"),
            "m15_bias": context_snapshot.get("m15_bias"),
            "m5_bias": context_snapshot.get("m5_bias"),
            "regime": context_snapshot.get("regime"),
            "liquidity": context_snapshot.get("liquidity"),
            "mss": context_snapshot.get("mss"),
            "displacement": context_snapshot.get("displacement"),
            "session": context_snapshot.get("session"),
        }
        trade_id = trades_repo.create_trade(data, context)
        st.success(f"Trade #{trade_id} saved.")
        st.rerun()


def render_trade_table():
    st.markdown("#### Trades")

    with st.expander("Filters", expanded=False):
        f1, f2, f3, f4 = st.columns(4)
        all_trades = trades_repo.list_trades()
        session_opts = ["All"] + sorted(all_trades["session"].dropna().unique().tolist()) if not all_trades.empty else ["All"]
        setup_opts = ["All"] + sorted(all_trades["setup"].dropna().unique().tolist()) if not all_trades.empty else ["All"]
        regime_opts = ["All"] + sorted(all_trades["market_regime"].dropna().unique().tolist()) if not all_trades.empty else ["All"]

        session_f = f1.selectbox("Session", session_opts)
        setup_f = f2.selectbox("Setup", setup_opts)
        direction_f = f3.selectbox("Direction", ["All", "BUY", "SELL"])
        regime_f = f4.selectbox("Regime", regime_opts)

    filters = {
        "session": None if session_f == "All" else session_f,
        "setup": None if setup_f == "All" else setup_f,
        "direction": None if direction_f == "All" else direction_f,
        "regime": None if regime_f == "All" else regime_f,
    }
    df = trades_repo.list_trades(filters)

    if df.empty:
        st.info("No trades logged yet. Create one above.")
        return df

    display_df = df.rename(columns={
        "trade_date": "DATE", "session": "SESSION", "setup": "SETUP", "direction": "DIR",
        "entry": "ENTRY", "planned_rr": "PLANNED RR", "result": "RESULT",
    })[["id", "DATE", "SESSION", "SETUP", "DIR", "ENTRY", "PLANNED RR", "RESULT", "status"]]

    st.dataframe(display_df, width="stretch", hide_index=True)
    render_analytics(df)

    st.divider()
    trade_id = st.selectbox("View / update trade", df["id"].tolist(),
                             format_func=lambda i: f"#{i} — {df.loc[df['id'] == i, 'trade_date'].values[0]}")
    if trade_id:
        render_trade_detail(trade_id)

    return df


def render_trade_detail(trade_id: int):
    trade = trades_repo.get_trade(trade_id)
    if not trade:
        return

    st.markdown(f"##### Trade #{trade_id} detail")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Direction", trade["direction"])
    c2.metric("Entry", f"{trade['entry']:.2f}")
    c3.metric("Stop Loss", f"{trade['stop_loss']:.2f}")
    c4.metric("Take Profit", f"{trade['take_profit']:.2f}" if trade["take_profit"] else "—")

    st.caption(
        f"Setup: {trade['setup'] or '—'} · Regime: {trade['market_regime'] or '—'} · "
        f"Session: {trade['session'] or '—'} · Planned RR: 1:{trade['planned_rr']}" if trade["planned_rr"] else ""
    )
    st.caption(
        f"Context at entry — H4 {trade['h4_bias'] or '—'} · H1 {trade['h1_bias'] or '—'} · "
        f"M15 {trade['m15_bias'] or '—'} · M5 {trade['m5_bias'] or '—'} · "
        f"Liquidity: {trade['liquidity'] or 'None'} · MSS: {trade['mss'] or 'None'} · "
        f"Displacement: {trade['displacement'] or 'None'}"
    )
    if trade.get("notes"):
        st.write(trade["notes"])
    if trade.get("screenshot_path") and Path(trade["screenshot_path"]).exists():
        st.image(trade["screenshot_path"], width=400)

    if trade["status"] == "CLOSED":
        st.divider()
        st.markdown("**Result**")
        r1, r2, r3, r4 = st.columns(4)
        r1.metric("Exit", f"{trade['exit_price']:.2f}" if trade["exit_price"] else "—")
        r2.metric("Result", trade["result"] or "—")
        r3.metric("R Multiple", trade["r_multiple"] if trade["r_multiple"] is not None else "—")
        r4.metric("Duration (min)", trade["duration_minutes"] or "—")
        st.caption(f"Exit reason: {trade['exit_reason'] or '—'} · Rule followed: {trade['rule_followed'] or '—'}")
        if trade.get("mistake"):
            st.caption(f"Mistake: {trade['mistake']}")
        return

    st.divider()
    st.markdown("**Close this trade**")
    with st.form(f"close_trade_{trade_id}"):
        c1, c2, c3 = st.columns(3)
        exit_price = c1.number_input("Exit", min_value=0.0, step=0.01, format="%.2f")
        result = c2.selectbox("Result", ["WIN", "LOSS", "BE"])
        r_multiple = c3.number_input("R Multiple", step=0.1, format="%.2f")

        c4, c5 = st.columns(2)
        duration = c4.number_input("Duration (minutes)", min_value=0, step=1)
        exit_reason = c5.text_input("Exit Reason", placeholder="e.g. Hit TP, manual close")

        c6, c7 = st.columns(2)
        rule_followed = c6.selectbox("Rule Followed", ["Yes", "No", "Partially"])
        mistake = c7.text_input("Mistake", placeholder="If any")

        exit_notes = st.text_area("Exit Notes")
        pnl = st.number_input("P/L ($)", step=1.0, format="%.2f")

        if st.form_submit_button("Save Result", type="primary"):
            trades_repo.close_trade(trade_id, {
                "exit_price": exit_price, "result": result, "pnl": pnl, "r_multiple": r_multiple,
                "duration_minutes": duration, "exit_reason": exit_reason or None,
                "rule_followed": rule_followed, "mistake": mistake or None, "exit_notes": exit_notes or None,
            })
            st.success("Trade closed.")
            st.rerun()


def render_analytics(df):
    st.markdown("#### Analytics")
    stats = trades_repo.compute_analytics(df)

    if stats["total_trades"] == 0:
        st.info("No closed trades in this selection yet.")
        return

    if stats["total_trades"] < 10:
        st.warning(f"Sample size: {stats['total_trades']} closed trades — too small to draw firm conclusions.")
    else:
        st.caption(f"Sample size: {stats['total_trades']} closed trades.")

    cols = st.columns(6)
    cols[0].metric("Total Trades", stats["total_trades"])
    cols[1].metric("Wins", stats["wins"])
    cols[2].metric("Losses", stats["losses"])
    cols[3].metric("Win Rate", f"{stats['win_rate']}%")
    cols[4].metric("Total R", f"{stats['total_r']}")
    cols[5].metric("Profit Factor", stats["profit_factor"] if stats["profit_factor"] is not None else "—")


def render_journal_page(context_snapshot: dict):
    render_new_trade_form(context_snapshot)
    st.divider()
    render_trade_table()
