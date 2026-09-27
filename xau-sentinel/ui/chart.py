"""Candlestick chart builder with key-zone overlays. Deliberately uncluttered —
only the most relevant zones are drawn by default."""
import plotly.graph_objects as go

_ZONE_COLORS = {
    "Previous Day High": "#e06c75", "Previous Day Low": "#e06c75",
    "Current Day High": "#c678dd", "Current Day Low": "#c678dd",
    "Asian High": "#d19a66", "Asian Low": "#d19a66",
    "London High": "#56b6c2", "London Low": "#56b6c2",
    "H1 Swing High": "#98c379", "H1 Swing Low": "#98c379",
    "H4 Swing High": "#e5c07b", "H4 Swing Low": "#e5c07b",
    "VWAP": "#abb2bf",
}

DEFAULT_CHART_ZONES = [
    "Previous Day High", "Previous Day Low", "Current Day High", "Current Day Low", "VWAP",
]


def build_candlestick_chart(df, zones: dict = None, title: str = "XAUUSD", zone_names=None):
    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=df["time"], open=df["open"], high=df["high"], low=df["low"], close=df["close"],
        name="XAUUSD",
        increasing_line_color="#26a69a", decreasing_line_color="#ef5350",
        increasing_fillcolor="#26a69a", decreasing_fillcolor="#ef5350",
    ))

    zones = zones or {}
    zone_names = zone_names if zone_names is not None else DEFAULT_CHART_ZONES
    for name in zone_names:
        price = zones.get(name)
        if price is None:
            continue
        color = _ZONE_COLORS.get(name, "#abb2bf")
        fig.add_hline(
            y=price, line_dash="dot", line_color=color, line_width=1,
            annotation_text=f"{name} {price:.2f}", annotation_position="right",
            annotation_font_size=10, annotation_font_color=color,
        )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="#131722", plot_bgcolor="#131722",
        font=dict(color="#d1d4dc", size=12),
        title=title,
        xaxis_rangeslider_visible=False,
        margin=dict(l=10, r=70, t=40, b=10),
        height=560,
        xaxis=dict(gridcolor="#242832"),
        yaxis=dict(gridcolor="#242832"),
        showlegend=False,
    )
    return fig
