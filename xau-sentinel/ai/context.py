"""Deterministic context builder for the AI assistant.

Every field rendered here traces to one direct call into an existing,
frozen engine — api.snapshot.build_snapshot() (Stage 1 market/setup wiring),
risk.fundednext.compute_status() (Stage 2 risk engine), or journal.trades
(the journal). Nothing is computed fresh just for the assistant, and nothing
is invented: a source that has no data comes back with available=False and
an explicit reason, never a guess.

Kept narrow on purpose ("do not send unnecessary data to the LLM"): journal
history is only included when the caller's context_scope asks for it, since
it's the most token-heavy section and most questions don't need it.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from api.snapshot import build_snapshot
from journal import trades as trades_repo
from risk import settings_store
from risk.fundednext import compute_status
from risk.fundednext_journal import get_snapshot as get_fundednext_trade_snapshot
from risk.models import AccountType, Phase

MARKET_LABEL = "Market Structure"
SETUP_LABEL = "Setup"
RISK_LABEL = "FundedNext Risk"
JOURNAL_LABEL = "Journal"
TRADE_LABEL = "Trade Context (captured at entry)"

# "market" covers price/structure/zones/liquidity/regime/setup together, per
# the Stage 3 spec's own "Current market" grouping — it renders as two
# separate transparency-panel entries (Market Structure + Setup) below, but
# is one scope flag since they come from a single build_snapshot() call.
ALL_SCOPES = ("market", "risk", "journal")
DEFAULT_SCOPES = ("market", "risk")

JOURNAL_HISTORY_LIMIT = 10

# VAL-038: structure, zones, sweeps, displacement and the setup are all built
# from the same candles as the price line, so when that data is stale every
# one of them is stale too — the warning can't live on the price line alone.
STALE_DERIVED_NOTE = (
    "DATA FRESHNESS: STALE — market data has not updated recently; everything in this "
    "section was computed from that same stale data and may not reflect the current market."
)


def _is_stale(snapshot) -> bool:
    return bool(snapshot.price is not None and snapshot.price.stale)


@dataclass
class ContextSection:
    label: str
    available: bool
    text: str  # deterministic, LLM-ready rendering of this section
    detail: Optional[str] = None  # short summary for the UI's transparency panel


@dataclass
class AssembledContext:
    sections: List[ContextSection] = field(default_factory=list)

    @property
    def used_labels(self) -> List[str]:
        return [s.label for s in self.sections if s.available]

    def render(self) -> str:
        """Plain-text block handed to the LLM as part of the system prompt —
        one clearly-labeled section per source, so the model (and a human
        reading the raw prompt) can attribute every fact back to where it
        came from. See ai/prompts.py."""
        if not self.sections:
            return "No context is currently available."
        parts = []
        for s in self.sections:
            parts.append(f"### {s.label} ###")
            parts.append(s.text if s.available else f"UNAVAILABLE — {s.text}")
            parts.append("")
        return "\n".join(parts).strip()


def _market_section_from_snapshot(snapshot) -> ContextSection:
    if snapshot.data_error or snapshot.price is None:
        reason = snapshot.data_error or "Market data unavailable."
        return ContextSection(MARKET_LABEL, available=False, text=reason, detail=reason)

    lines = [STALE_DERIVED_NOTE] if _is_stale(snapshot) else []
    lines += [
        f"Mode: {snapshot.connection.mode.upper()} ({snapshot.connection.label})",
        f"Price: {snapshot.price.price:.2f} (bid {snapshot.price.bid:.2f} / ask {snapshot.price.ask:.2f}, "
        f"spread {snapshot.price.spread:.2f})" + (" — STALE, may not reflect the current market" if snapshot.price.stale else ""),
        f"Session: {snapshot.session or 'unknown'}",
    ]

    for tf in ("H4", "H1", "M15", "M5"):
        s = snapshot.structure.get(tf)
        if s is None:
            continue
        tags = [t for t in (f"BOS={s.last_bos}" if s.last_bos else None,
                             f"MSS={s.last_mss}" if s.last_mss else None) if t]
        suffix = f" ({', '.join(tags)})" if tags else ""
        lines.append(f"{tf} structure: {s.state}{suffix} — {s.reason}")

    if snapshot.regime:
        lines.append(f"Regime: {snapshot.regime.regime} — {snapshot.regime.reason}")

    if snapshot.zones:
        lines.append("Key zones: " + ", ".join(f"{name} {price:.2f}" for name, price in snapshot.zones.items()))

    sweeps = snapshot.liquidity.sweeps
    lines.append(
        "Liquidity sweeps: " + "; ".join(f"{e.label} (level {e.level_price:.2f})" for e in sweeps[-5:])
        if sweeps else "Liquidity sweeps: none detected in the current window."
    )

    equal_levels = snapshot.liquidity.equal_levels
    if equal_levels:
        lines.append("Equal highs/lows: " + "; ".join(f"{e.label} ({e.level_price:.2f})" for e in equal_levels[-5:]))

    lines.append(f"Displacement (M5): {snapshot.displacement}" if snapshot.displacement
                 else "Displacement (M5): none detected on the latest candle.")

    return ContextSection(
        MARKET_LABEL, available=True, text="\n".join(lines),
        detail=f"{snapshot.connection.mode.upper()} · price {snapshot.price.price:.2f}"
               + (" · STALE data" if _is_stale(snapshot) else ""),
    )


def _setup_section_from_snapshot(snapshot) -> ContextSection:
    if snapshot.data_error or snapshot.setup is None:
        reason = snapshot.data_error or "Setup data unavailable."
        return ContextSection(SETUP_LABEL, available=False, text=reason, detail=reason)

    setup = snapshot.setup
    checklist_txt = ", ".join(
        f"{k}={'confirmed' if v is True else 'waiting'}" for k, v in setup.checklist.items()
    )
    direction_txt = f" ({setup.direction})" if setup.direction else ""
    lines = [STALE_DERIVED_NOTE] if _is_stale(snapshot) else []
    lines += [
        f"Setup state: {setup.state}{direction_txt} — {setup.reason}",
        f"Checklist: {checklist_txt}" if checklist_txt else "Checklist: n/a",
    ]
    if setup.state == "VALID":
        rr_txt = f"RR 1:{setup.rr}" if setup.rr is not None else "RR unavailable"
        lines.append(
            "Setup plan (analysis only — not an instruction to trade): "
            f"entry zone {setup.entry_zone}, SL {setup.stop_loss}, TP {setup.take_profit}, {rr_txt}"
        )

    detail = f"{setup.state}{direction_txt}" + (" · STALE data" if _is_stale(snapshot) else "")
    return ContextSection(SETUP_LABEL, available=True, text="\n".join(lines), detail=detail)


def build_risk_section() -> ContextSection:
    settings = settings_store.get_settings()
    status = compute_status(
        AccountType(settings["account_type"]), Phase(settings["phase"]),
        consistency_enabled=settings["consistency_enabled"],
    )
    if not status.data_available:
        return ContextSection(RISK_LABEL, available=False, text=status.reason, detail=status.reason)

    lines = [
        f"Account: {status.account_type.value} ({status.phase.value}), mode={status.mode}",
        f"Balance: {status.balance:.2f} · Equity: {status.equity:.2f}",
        f"Today's P/L: {status.today_pnl:+.2f}",
        f"Daily loss remaining: {status.daily_loss_remaining:.2f} "
        f"({status.daily_loss_used_pct:.0f}% of today's allowance used)",
        f"Max drawdown remaining: {status.max_drawdown_remaining:.2f} "
        f"({status.max_drawdown_used_pct:.0f}% of the static buffer used)",
        f"Safety level: {status.safety_level.value} — {status.reason}",
    ]
    if status.profit_target is not None:
        lines.append(f"Profit target: {status.profit_target:.2f} ({status.progress_to_target_pct}% reached)")
    if status.trading_days_required is not None:
        lines.append(f"Trading days completed: {status.trading_days_completed}/{status.trading_days_required}")
    if status.violations:
        lines.append("Violations: " + "; ".join(f"{v.level.value} {v.rule}: {v.message}" for v in status.violations))

    detail = f"{status.safety_level.value}"
    if status.daily_loss_remaining is not None:
        detail += f" · {status.daily_loss_remaining:.2f} daily loss remaining"
    return ContextSection(RISK_LABEL, available=True, text="\n".join(lines), detail=detail)


def build_journal_section(limit: int = JOURNAL_HISTORY_LIMIT) -> ContextSection:
    df = trades_repo.list_trades()
    if df.empty:
        return ContextSection(JOURNAL_LABEL, available=False, text="No trades have been journaled yet.",
                               detail="0 trades")

    analytics = trades_repo.compute_analytics(df)
    lines = [
        f"Total closed trades: {analytics['total_trades']} "
        f"(wins {analytics['wins']}, losses {analytics['losses']}, breakeven {analytics['breakeven']})",
        f"Win rate: {analytics['win_rate']}% · Total R: {analytics['total_r']} · Avg R: {analytics['avg_r']} · "
        f"Profit factor: {analytics['profit_factor'] if analytics['profit_factor'] is not None else 'n/a'}",
    ]
    if analytics["total_trades"] < 10:
        lines.append(f"Sample size is small ({analytics['total_trades']} closed trades) — avoid firm conclusions.")

    recent = df.head(limit)
    lines.append(f"Most recent {len(recent)} trade(s), newest first:")
    for _, row in recent.iterrows():
        result = row.get("result") or ("OPEN" if row.get("status") == "OPEN" else "n/a")
        rr = f", R={row['r_multiple']}" if row.get("r_multiple") is not None else ""
        lines.append(
            f"- {row['trade_date']} {row['session'] or 'unknown session'} {row['direction']} "
            f"\"{row['setup'] or 'unlabeled setup'}\" entry {row['entry']} -> {result}{rr} "
            f"(regime at entry: {row.get('market_regime') or 'unknown'})"
        )

    return ContextSection(JOURNAL_LABEL, available=True, text="\n".join(lines),
                           detail=f"{analytics['total_trades']} trades · {analytics['win_rate']}% win rate")


def build_trade_section(trade_id: int) -> ContextSection:
    """"Explain this trade using the market and account context captured at
    entry" (Stage 3 spec section 3). Reads the trade's own stored
    journal_context and its immutable FundedNext snapshot (see
    risk/fundednext_journal.py — captured once, never updated) — never the
    LIVE market/account state, so an old trade is never explained using
    today's conditions."""
    trade = trades_repo.get_trade(trade_id)
    if trade is None:
        reason = f"No trade with id {trade_id} was found in the journal."
        return ContextSection(TRADE_LABEL, available=False, text=reason, detail=reason)

    lines = [
        f"Trade #{trade_id}: {trade['direction']} {trade.get('symbol', '')} on "
        f"{trade['trade_date']} {trade['trade_time']} ({trade.get('session') or 'unknown session'})",
        f"Entry {trade['entry']}, SL {trade['stop_loss']}, TP {trade.get('take_profit')}, "
        f"planned RR {trade.get('planned_rr')}",
        f"Setup label: {trade.get('setup') or 'none recorded'}",
        "Market context captured at entry (NOT the current live market) — "
        f"H4 {trade.get('h4_bias') or 'unknown'}, H1 {trade.get('h1_bias') or 'unknown'}, "
        f"M15 {trade.get('m15_bias') or 'unknown'}, M5 {trade.get('m5_bias') or 'unknown'}, "
        f"regime {trade.get('regime') or 'unknown'}",
        f"Liquidity at entry: {trade.get('liquidity') or 'none recorded'} · "
        f"MSS: {trade.get('mss') or 'none'} · Displacement: {trade.get('displacement') or 'none'}",
    ]

    if trade.get("status") == "CLOSED":
        lines.append(
            f"Result: {trade.get('result') or 'n/a'}, exit {trade.get('exit_price')}, "
            f"R multiple {trade.get('r_multiple')}, duration {trade.get('duration_minutes')} min, "
            f"exit reason: {trade.get('exit_reason') or 'n/a'}"
        )
        if trade.get("mistake"):
            lines.append(f"Recorded mistake: {trade['mistake']}")
    else:
        lines.append("Status: still OPEN — no exit recorded yet.")

    fn_snapshot = get_fundednext_trade_snapshot(trade_id)
    if fn_snapshot and fn_snapshot.get("data_available"):
        lines.append(
            "FundedNext account snapshot at entry (NOT the current live account) — "
            f"balance {fn_snapshot['balance']}, equity {fn_snapshot['equity']}, "
            f"daily loss remaining {fn_snapshot['daily_loss_remaining']}, "
            f"max drawdown remaining {fn_snapshot['max_drawdown_remaining']}, "
            f"safety level {fn_snapshot['safety_level']}"
        )
    else:
        lines.append("FundedNext account snapshot at entry: not available for this trade.")

    if trade.get("notes"):
        lines.append(f"Notes: {trade['notes']}")

    return ContextSection(
        TRADE_LABEL, available=True, text="\n".join(lines),
        detail=f"Trade #{trade_id} · {trade['direction']} · {trade.get('result') or trade.get('status')}",
    )


def build_context(scope: Optional[List[str]] = None, trade_id: Optional[int] = None) -> AssembledContext:
    """`scope` is a subset of ALL_SCOPES; unknown names are ignored rather
    than rejected (never trust client input blindly, but degrade gracefully
    instead of erroring on a typo). Falls back to DEFAULT_SCOPES when the
    caller passes nothing or nothing recognizable.

    `trade_id`, when given, replaces the scope entirely: explaining a past
    trade must use ONLY what was captured at entry, never blended with
    today's live market/risk state (see build_trade_section's docstring)."""
    if trade_id is not None:
        return AssembledContext(sections=[build_trade_section(trade_id)])

    requested = set(scope) & set(ALL_SCOPES) if scope else set(DEFAULT_SCOPES)
    if not requested:
        requested = set(DEFAULT_SCOPES)

    sections: List[ContextSection] = []
    if "market" in requested:
        snapshot = build_snapshot()
        sections.append(_market_section_from_snapshot(snapshot))
        sections.append(_setup_section_from_snapshot(snapshot))
    if "risk" in requested:
        sections.append(build_risk_section())
    if "journal" in requested:
        sections.append(build_journal_section())

    return AssembledContext(sections=sections)
