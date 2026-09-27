"""Orchestrates one A+ evaluation:

    Deterministic Market Engine -> Candidate Setup -> Strategy Rules
    -> Structured Evidence -> LLM Evaluation -> A+ / DEVELOPING / INVALID

evaluate_deterministic() is a pure function — same inputs, same output,
every time, independent of any LLM call — and it alone decides `rating`.
attach_llm_explanation() runs strictly after, as a best-effort enrichment
that can never change `rating`, `criteria`, or `missing_conditions`: if the
provider is unconfigured or fails, the deterministic result is returned
unchanged with `llm_error` set instead. This is the literal implementation
of "deterministic rules always override the LLM."

Every fact fed to the LLM comes from `criteria`/`context_evidence`, which
are themselves built only from analysis/structure.py, analysis/liquidity.py,
analysis/zones.py, and risk/fundednext.py — the same frozen engines the
rest of the app uses. Nothing here re-derives or second-guesses them.
"""
from datetime import datetime, timezone
from typing import List, Optional

import config
from analysis.setup import _check_retracement
from analysis.structure import analyze_structure, detect_displacement
from analysis.liquidity import detect_equal_levels, detect_sweeps
from analysis.zones import compute_zones
from mt5 import market_data
from risk.fundednext import compute_status
from risk.models import AccountType, FundedNextStatus, Phase
from risk import settings_store

from ai.providers import get_provider
from ai.providers.base import ProviderConfigError, ProviderRequestError, ProviderResponseError
from ai.prompts import SAFETY_OVERRIDE_MESSAGE, contains_actionable_directive
from ai.strategy import rules
from ai.strategy.schemas import Criterion, CriterionStatus, FundedNextGateOut, Rating, StrategyEvaluationOut

STRATEGY_SYSTEM_PROMPT = """You are explaining a deterministic A+ trade-setup evaluation for XAU \
Sentinel, a personal, read-only XAUUSD terminal. You do NOT decide the rating — it has already \
been computed deterministically by a rules engine and is given to you below as a fact you cannot \
change. Your only job is to explain, in plain language, why the rating came out the way it did: \
which criteria passed or failed, and what (if anything) is still missing.

Rules:
1. Use ONLY the evidence given below. Never invent a market fact, price, or condition not listed.
2. Never suggest the rating should be different from what is given.
3. Never issue a trade instruction — no "buy now", "enter now", "you should take this." The user \
decides everything manually, in their own MT5 terminal, regardless of this rating.
4. If the rating is DEVELOPING or INVALID, explain what's missing or what invalidated it — never \
imply the user should act anyway.
5. Be concise.
"""


def _status(ok: Optional[bool]) -> CriterionStatus:
    if ok is None:
        return CriterionStatus.UNKNOWN
    return CriterionStatus.PASSED if ok else CriterionStatus.FAILED


def _fundednext_gate_out(status: FundedNextStatus, passed: bool, reason: str) -> FundedNextGateOut:
    return FundedNextGateOut(
        data_available=status.data_available,
        safety_level=status.safety_level.value if status.data_available else None,
        daily_loss_used_pct=status.daily_loss_used_pct,
        max_daily_loss_used_pct_allowed=config.AI_STRATEGY_FUNDEDNEXT_MAX_DAILY_LOSS_USED_PCT,
        reason=reason,
    )


def _sweep_time_iso(event) -> Optional[str]:
    if event is None or event.time is None:
        return None
    ts = event.time
    return ts.isoformat() if hasattr(ts, "isoformat") else str(ts)


def evaluate_deterministic(candles: dict, fundednext_status: FundedNextStatus,
                            now: Optional[datetime] = None) -> StrategyEvaluationOut:
    """`candles` is a dict of timeframe -> DataFrame for M5/M15/H1/H4, same
    shape analysis.setup.detect_setup already expects. Pure and
    side-effect-free — no DB writes, no LLM call, no live I/O — so it can be
    tested with synthetic candles exactly like tests/test_setup.py does."""
    now = now or datetime.now(timezone.utc)

    h4 = analyze_structure(candles["H4"])
    h1 = analyze_structure(candles["H1"])
    m15 = analyze_structure(candles["M15"])
    m5 = analyze_structure(candles["M5"])
    zones = compute_zones(candles["M5"], candles["H1"], candles["H4"])
    sweeps = detect_sweeps(candles["M5"], zones)
    equal_levels = detect_equal_levels(candles["M5"])
    displacement = detect_displacement(candles["M5"])
    last_price = float(candles["M5"]["close"].iloc[-1])

    fn_gate_ok, fn_reason = rules.check_fundednext_gate(fundednext_status)
    fundednext_out = _fundednext_gate_out(fundednext_status, fn_gate_ok, fn_reason)

    context_evidence: List[str] = [
        f"H4 bias: {h4.state} — {h4.reason}",
        f"M15 bias: {m15.state} — {m15.reason}",
    ]
    if equal_levels:
        context_evidence.append(
            "Equal highs/lows (supporting evidence only — never a qualifying sweep): "
            + "; ".join(e.label for e in equal_levels[-3:])
        )

    candidate = rules.select_candidate(sweeps)
    if candidate is None:
        return StrategyEvaluationOut(
            rating=Rating.DEVELOPING, direction=None,
            criteria=[Criterion(name="Liquidity Sweep", status=CriterionStatus.FAILED,
                                 evidence="No qualifying liquidity sweep (PDH/PDL/session/H1/H4 swing) "
                                          "detected in the current window.")],
            context_evidence=context_evidence, missing_conditions=["Liquidity Sweep"],
            fundednext=fundednext_out, evaluated_at=now.isoformat(),
        )

    direction = rules.candidate_direction(candidate)
    sweep_time_iso = _sweep_time_iso(candidate)

    if rules.is_opposing_mss_invalidated(direction, m5.state):
        return StrategyEvaluationOut(
            rating=Rating.INVALID, direction=direction, context_evidence=context_evidence,
            invalidation=f"Opposing M5 structure break ({m5.state}) invalidated the {direction} candidate.",
            fundednext=fundednext_out, evaluated_at=now.isoformat(), candidate_sweep_time=sweep_time_iso,
        )

    if rules.is_h1_flip_invalidated(direction, h1.state):
        return StrategyEvaluationOut(
            rating=Rating.INVALID, direction=direction, context_evidence=context_evidence,
            invalidation=f"H1 bias flipped to {h1.state}, invalidating the {direction} candidate before entry.",
            fundednext=fundednext_out, evaluated_at=now.isoformat(), candidate_sweep_time=sweep_time_iso,
        )

    if not rules.is_within_sweep_window(candidate.time, now):
        return StrategyEvaluationOut(
            rating=Rating.INVALID, direction=direction, context_evidence=context_evidence,
            invalidation=(f"Setup expired — no entry within {config.AI_STRATEGY_SWEEP_WINDOW_MINUTES} minutes "
                          f"of the {candidate.level_name} sweep at {candidate.time}."),
            fundednext=fundednext_out, evaluated_at=now.isoformat(), candidate_sweep_time=sweep_time_iso,
        )

    h1_ok = rules.h1_supports_direction(direction, h1.state, h1.last_mss)
    mss_ok = rules.is_m5_mss_confirmed(direction, m5.last_mss)
    displacement_ok = rules.is_displacement_confirmed(direction, displacement)
    retracement_ok = _check_retracement(candles["M5"], direction)

    entry = round(last_price, 2)
    stop_loss = rules.compute_stop_loss(direction, candidate.level_price)
    target = rules.select_target(direction, zones, entry)
    rr, _risk, _reward = rules.compute_risk_reward(direction, entry, stop_loss, target)
    rr_ok = rules.passes_min_rr(rr)

    criteria_specs = [
        ("H1 Bias", h1_ok,
         f"H1 structure: {h1.state}" + (f" (MSS={h1.last_mss})" if h1.last_mss else "") + f" — {h1.reason}"),
        ("Liquidity Sweep", True,
         f"{candidate.label} at {candidate.level_price} ({candidate.time}), "
         f"within the {config.AI_STRATEGY_SWEEP_WINDOW_MINUTES}-minute window."),
        ("M5 MSS", mss_ok,
         f"M5 structure: {m5.state}" + (f" (MSS={m5.last_mss})" if m5.last_mss else "") + f" — {m5.reason}"),
        ("Displacement", displacement_ok,
         f"M5 displacement: {displacement or 'none detected on the latest candle'}"),
        ("Retracement", retracement_ok,
         f"M5 retracement into the {config.RETRACEMENT_MIN_PCT * 100:.0f}-"
         f"{config.RETRACEMENT_MAX_PCT * 100:.0f}% band: {'within band' if retracement_ok else 'not within band'}"),
        ("Minimum R:R", rr_ok if rr is not None else None,
         (f"Entry {entry}, SL {stop_loss}, target {target}, actual R:R 1:{rr} "
          f"(minimum required 1:{config.AI_STRATEGY_MIN_RR})") if rr is not None
         else "No qualifying opposing liquidity level found beyond entry — R:R cannot be computed."),
        ("FundedNext Risk", fn_gate_ok, fn_reason),
    ]

    criteria = [Criterion(name=name, status=_status(ok), evidence=evidence) for name, ok, evidence in criteria_specs]
    missing_conditions = [name for name, ok, _ in criteria_specs if ok is not True]
    rating = Rating.A_PLUS if not missing_conditions else Rating.DEVELOPING

    return StrategyEvaluationOut(
        rating=rating, direction=direction, criteria=criteria, context_evidence=context_evidence,
        missing_conditions=missing_conditions, entry=entry, stop_loss=stop_loss, target=target, rr=rr,
        fundednext=fundednext_out, evaluated_at=now.isoformat(), candidate_sweep_time=sweep_time_iso,
    )


def _render_for_llm(result: StrategyEvaluationOut) -> str:
    lines = [f"Rating: {result.rating.value}", f"Direction: {result.direction or 'NONE'}"]
    if result.invalidation:
        lines.append(f"Invalidation: {result.invalidation}")
    for c in result.criteria:
        lines.append(f"- {c.name}: {c.status.value} — {c.evidence}")
    if result.missing_conditions:
        lines.append("Missing conditions: " + ", ".join(result.missing_conditions))
    if result.entry is not None:
        rr_txt = f"1:{result.rr}" if result.rr is not None else "n/a"
        lines.append(f"Entry {result.entry}, SL {result.stop_loss}, Target {result.target}, R:R {rr_txt}")
    lines.append(
        f"FundedNext: safety_level={result.fundednext.safety_level}, "
        f"daily_loss_used_pct={result.fundednext.daily_loss_used_pct}"
    )
    if result.context_evidence:
        lines.append("Context: " + " | ".join(result.context_evidence))
    return "\n".join(lines)


def attach_llm_explanation(result: StrategyEvaluationOut) -> StrategyEvaluationOut:
    """Best-effort enrichment only. Never touches rating/criteria/
    missing_conditions/invalidation — see module docstring."""
    try:
        provider = get_provider()
    except ProviderConfigError as exc:
        result.llm_error = f"AI assistant not configured: {exc}"
        return result

    try:
        response = provider.chat(STRATEGY_SYSTEM_PROMPT, [{"role": "user", "content": _render_for_llm(result)}])
    except (ProviderRequestError, ProviderResponseError) as exc:
        result.llm_error = str(exc)
        return result

    explanation = response.text
    if contains_actionable_directive(explanation):
        explanation = SAFETY_OVERRIDE_MESSAGE

    result.llm_explanation = explanation
    result.llm_provider = response.provider
    result.llm_model = response.model
    return result


def evaluate_current_setup() -> StrategyEvaluationOut:
    """Live wiring used by the API route: fetches current candles and
    FundedNext status, evaluates deterministically, then enriches with an
    LLM explanation. Raises market_data.MarketDataError exactly like
    /api/setup/current does — the route maps it to a 503, never a crash."""
    candles = market_data.get_all_candles(300)

    settings = settings_store.get_settings()
    fn_status = compute_status(
        AccountType(settings["account_type"]), Phase(settings["phase"]), settings["consistency_enabled"],
    )

    result = evaluate_deterministic(candles, fn_status)
    return attach_llm_explanation(result)
