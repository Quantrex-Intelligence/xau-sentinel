"""Integration tests for ai/strategy/evaluator.py. Mocks the underlying
analysis calls (analyze_structure, detect_sweeps, detect_equal_levels,
compute_zones, evaluate_sequence) exactly the way
tests/test_setup.py does for Stage 1 — each Stage 4 rating transition is
tested independently of whether the lower-level analysis functions
themselves are correct (those have their own dedicated test files)."""
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

import config
import ai.strategy.evaluator as evaluator_mod
from ai.strategy.schemas import CriterionStatus, Rating
from ai.providers.base import BaseProvider, ProviderConfigError, ProviderRequestError, ProviderResponse
from analysis.structure import StructureResult
from analysis.liquidity import LiquidityEvent
from analysis.sequence import SequenceResult
from risk.models import AccountType, FundedNextStatus, Phase, SafetyLevel
from tests.conftest import make_candles

NOW = datetime(2026, 1, 5, 12, 0, tzinfo=timezone.utc)


def _candles():
    rows = [(100 + i * 0.1, 100.3 + i * 0.1, 99.7 + i * 0.1, 100.1 + i * 0.1) for i in range(15)]
    df = make_candles(rows, start=NOW - timedelta(minutes=5 * 15))
    return {"H4": df, "H1": df, "M15": df, "M5": df}


def _sr(state, last_mss=None, last_bos=None, reason="reason"):
    return StructureResult(state=state, last_mss=last_mss, last_bos=last_bos, reason=reason)


def _sweep(kind, minutes_ago=10, level_name="Previous Day Low", level_price=99.9, label=None):
    return LiquidityEvent(time=NOW - timedelta(minutes=minutes_ago), label=label or f"{level_name} swept",
                           level_name=level_name, level_price=level_price, kind=kind)


def _safe_status(**overrides):
    defaults = dict(account_type=AccountType.STELLAR_2STEP, phase=Phase.CHALLENGE, mode="mock",
                     data_available=True, safety_level=SafetyLevel.SAFE, daily_loss_used_pct=10.0,
                     reason="All FundedNext limits within safe range.")
    defaults.update(overrides)
    return FundedNextStatus(**defaults)


def _patch_common(monkeypatch, h4, h1, m15, m5, zones, sweeps, displacement, retracement_ok,
                   equal_levels=None, mss=True, invalidated=False):
    """`displacement`/`mss`/`retracement_ok`/`invalidated` describe the M5
    bar sequence after the sweep (analysis/sequence.py, Stage 23A), mocked
    here the same way the other analysis calls are."""
    monkeypatch.setattr(evaluator_mod, "analyze_structure", Mock(side_effect=[h4, h1, m15, m5]))
    monkeypatch.setattr(evaluator_mod, "compute_zones", Mock(return_value=zones))
    monkeypatch.setattr(evaluator_mod, "detect_sweeps", Mock(return_value=sweeps))
    monkeypatch.setattr(evaluator_mod, "detect_equal_levels", Mock(return_value=equal_levels or []))
    seq = SequenceResult(
        sweep_index=3, mss_index=7 if mss else None, mss_level=100.0,
        displacement_index=7 if displacement else None, retracement_ok=retracement_ok,
        invalidated=invalidated,
        invalidation_reason="M5 closed back below the swept low (99.50) after the market structure shift."
        if invalidated else "",
    )
    monkeypatch.setattr(evaluator_mod, "evaluate_sequence", Mock(return_value=seq))


def _full_buy_setup(monkeypatch, **overrides):
    """A complete, all-criteria-passing BUY candidate — the baseline every
    "break one criterion" test starts from and perturbs."""
    params = dict(
        h4=_sr("BULLISH"), h1=_sr("BULLISH"), m15=_sr("BULLISH"), m5=_sr("PULLBACK", last_mss="bullish"),
        zones={"Previous Day Low": 99.9, "Previous Day High": 110.0},
        sweeps=[_sweep("sweep_low", minutes_ago=10)],
        displacement="bullish", retracement_ok=True,
    )
    params.update(overrides)
    _patch_common(monkeypatch, **params)


def _full_sell_setup(monkeypatch, **overrides):
    params = dict(
        h4=_sr("BEARISH"), h1=_sr("BEARISH"), m15=_sr("BEARISH"), m5=_sr("PULLBACK", last_mss="bearish"),
        # Swept high above entry (101.5), so the SELL stop sits on the correct
        # side. This fixture's old 100.3 level put the stop BELOW entry and
        # only "passed" through the abs() risk bug (Stage 23A, VAL-010).
        zones={"Previous Day High": 101.9, "Previous Day Low": 90.0},
        sweeps=[_sweep("sweep_high", minutes_ago=10, level_name="Previous Day High", level_price=101.9)],
        displacement="bearish", retracement_ok=True,
    )
    params.update(overrides)
    _patch_common(monkeypatch, **params)


# ---------------------------------------------------------------------------
# No candidate / missing data
# ---------------------------------------------------------------------------

def test_no_qualifying_sweep_is_developing_with_missing_liquidity_sweep(monkeypatch):
    _patch_common(monkeypatch, _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("RANGING"),
                   zones={}, sweeps=[], displacement=None, retracement_ok=False)
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    assert result.rating == Rating.DEVELOPING
    assert result.direction is None
    assert result.missing_conditions == ["Liquidity Sweep"]


def test_equal_highs_lows_alone_never_satisfy_the_sweep_requirement(monkeypatch):
    """Locked decision #2: equal highs/lows are supporting evidence only."""
    _patch_common(monkeypatch, _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"),
                   zones={}, sweeps=[], displacement=None, retracement_ok=False,
                   equal_levels=[LiquidityEvent(time=NOW, label="Equal lows detected",
                                                 level_name="Equal Lows", level_price=99.0, kind="equal_low")])
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    assert result.rating != Rating.A_PLUS
    assert "Liquidity Sweep" in result.missing_conditions
    assert any("Equal" in e for e in result.context_evidence)  # surfaced as context, not a criterion


# ---------------------------------------------------------------------------
# Full A+ path, BUY/SELL symmetry
# ---------------------------------------------------------------------------

def test_full_a_plus_buy(monkeypatch):
    _full_buy_setup(monkeypatch)
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    assert result.rating == Rating.A_PLUS
    assert result.direction == "BUY"
    assert result.missing_conditions == []
    assert all(c.status == CriterionStatus.PASSED for c in result.criteria)
    assert result.stop_loss == 99.60  # 99.9 - 0.30
    assert result.target == 110.0
    assert result.rr is not None and result.rr >= config.AI_STRATEGY_MIN_RR


def test_full_a_plus_sell(monkeypatch):
    _full_sell_setup(monkeypatch)
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    assert result.rating == Rating.A_PLUS
    assert result.direction == "SELL"
    assert result.missing_conditions == []
    assert all(c.status == CriterionStatus.PASSED for c in result.criteria)
    assert result.stop_loss == 102.20  # 101.9 + 0.30


# ---------------------------------------------------------------------------
# Breaking exactly one criterion at a time keeps it DEVELOPING, never A+
# ---------------------------------------------------------------------------

def test_missing_mss_is_developing_not_a_plus(monkeypatch):
    _full_buy_setup(monkeypatch, m5=_sr("BULLISH", last_mss=None), mss=False)  # no shift bar after the sweep
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    assert result.rating == Rating.DEVELOPING
    assert "M5 MSS" in result.missing_conditions


def test_missing_displacement_is_developing(monkeypatch):
    _full_buy_setup(monkeypatch, displacement=None)
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    assert result.rating == Rating.DEVELOPING
    assert "Displacement" in result.missing_conditions


def test_missing_retracement_is_developing(monkeypatch):
    _full_buy_setup(monkeypatch, retracement_ok=False)
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    assert result.rating == Rating.DEVELOPING
    assert "Retracement" in result.missing_conditions


def test_rr_below_minimum_is_developing_not_a_plus(monkeypatch):
    """Target too close to entry for a 1:3 -> must not be A+, and must not
    be silently forced to a fixed 3R (locked decision #1). Entry (last M5
    close from _candles()) is 101.5; SL is 99.6; a target of 103.0 gives
    reward 1.5 against risk 1.9 -- well under the 1:3 minimum."""
    _full_buy_setup(monkeypatch, zones={"Previous Day Low": 99.9, "Previous Day High": 103.0})
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    assert result.rating == Rating.DEVELOPING
    assert "Minimum R:R" in result.missing_conditions
    assert result.rr is not None and result.rr < config.AI_STRATEGY_MIN_RR


def test_rr_unknown_when_no_qualifying_target_exists(monkeypatch):
    _full_buy_setup(monkeypatch, zones={"Previous Day Low": 99.9})  # no High zone at all
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    assert result.rating == Rating.DEVELOPING
    assert result.target is None
    assert result.rr is None
    rr_criterion = next(c for c in result.criteria if c.name == "Minimum R:R")
    assert rr_criterion.status == CriterionStatus.UNKNOWN


def test_fundednext_not_safe_blocks_a_plus_even_when_everything_else_passes(monkeypatch):
    _full_buy_setup(monkeypatch)
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(safety_level=SafetyLevel.WARNING), now=NOW)
    assert result.rating == Rating.DEVELOPING
    assert "FundedNext Risk" in result.missing_conditions


def test_fundednext_daily_loss_at_threshold_blocks_a_plus(monkeypatch):
    _full_buy_setup(monkeypatch)
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(daily_loss_used_pct=50.0), now=NOW)
    assert result.rating == Rating.DEVELOPING
    assert "FundedNext Risk" in result.missing_conditions


def test_fundednext_unavailable_blocks_a_plus(monkeypatch):
    _full_buy_setup(monkeypatch)
    unavailable = FundedNextStatus(account_type=AccountType.STELLAR_2STEP, phase=Phase.CHALLENGE, mode="live",
                                    data_available=False, safety_level=SafetyLevel.UNKNOWN,
                                    reason="MT5 not connected")
    result = evaluator_mod.evaluate_deterministic(_candles(), unavailable, now=NOW)
    assert result.rating == Rating.DEVELOPING
    assert "FundedNext Risk" in result.missing_conditions
    assert result.fundednext.data_available is False
    assert result.fundednext.safety_level is None  # never fabricated when unavailable


# ---------------------------------------------------------------------------
# Invalidation
# ---------------------------------------------------------------------------

def test_opposing_m5_mss_invalidates(monkeypatch):
    _full_buy_setup(monkeypatch, m5=_sr("BEARISH"), invalidated=True)
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    assert result.rating == Rating.INVALID
    assert "Opposing M5" in result.invalidation
    assert "swept low" in result.invalidation


def test_bearish_m5_precursor_before_the_mss_is_not_invalid(monkeypatch):
    """VAL-008 regression: a BUY candidate right after its low sweep, M5
    still BEARISH and no MSS yet — DEVELOPING, not INVALID."""
    _full_buy_setup(monkeypatch, m5=_sr("BEARISH"), mss=False, displacement=None, retracement_ok=False)
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    assert result.rating == Rating.DEVELOPING
    assert result.invalidation is None
    assert "M5 MSS" in result.missing_conditions


# ---------------------------------------------------------------------------
# Stage 23A: R:R correctness (VAL-010) and staleness (VAL-011)
# ---------------------------------------------------------------------------

def test_stop_already_breached_yields_no_rr_and_says_so(monkeypatch):
    """Entry (101.5) is already below a BUY stop (102.0 swept low - 0.3
    buffer = 101.7): the stop has effectively been hit. abs() used to make
    this a positive risk and a plausible R:R."""
    _full_buy_setup(monkeypatch, sweeps=[_sweep("sweep_low", level_price=102.0)],
                    zones={"Previous Day Low": 102.0, "Previous Day High": 120.0})
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    assert result.rating == Rating.DEVELOPING
    assert result.rr is None
    rr_criterion = next(c for c in result.criteria if c.name == "Minimum R:R")
    assert rr_criterion.status == CriterionStatus.UNKNOWN
    assert "beyond the stop level" in rr_criterion.evidence


def test_rr_just_under_minimum_is_not_rounded_up_to_pass(monkeypatch):
    """Entry 101.5, SL 99.6 (risk 1.9). A target at 101.5 + 1.9 * 2.996 gives
    a true 2.996 that used to round to 3.0 and pass the 1:3 gate."""
    target = round(101.5 + 1.9 * 2.996, 2)
    _full_buy_setup(monkeypatch, zones={"Previous Day Low": 99.9, "Previous Day High": target})
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    assert result.rating == Rating.DEVELOPING
    assert "Minimum R:R" in result.missing_conditions
    assert result.rr == 2.99


def test_stale_feed_never_rates_a_plus(monkeypatch):
    """Everything passes, but the newest M5 candle is 15 minutes old."""
    _full_buy_setup(monkeypatch, sweeps=[_sweep("sweep_low", minutes_ago=0)])
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW + timedelta(minutes=10))
    assert result.rating == Rating.DEVELOPING
    assert result.missing_conditions == ["Data Freshness"]
    freshness = next(c for c in result.criteria if c.name == "Data Freshness")
    assert freshness.status == CriterionStatus.FAILED
    assert "stale" in freshness.evidence


def test_fresh_feed_passes_the_freshness_criterion(monkeypatch):
    _full_buy_setup(monkeypatch)
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    freshness = next(c for c in result.criteria if c.name == "Data Freshness")
    assert freshness.status == CriterionStatus.PASSED


def test_h1_flip_invalidates_before_entry(monkeypatch):
    _full_buy_setup(monkeypatch, h1=_sr("BEARISH"))
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    assert result.rating == Rating.INVALID
    assert "H1 bias flipped" in result.invalidation


def test_setup_expires_60_minutes_after_sweep(monkeypatch):
    _full_buy_setup(monkeypatch, sweeps=[_sweep("sweep_low", minutes_ago=61)])
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    assert result.rating == Rating.INVALID
    assert "expired" in result.invalidation.lower()


def test_sweep_within_window_is_not_expired(monkeypatch):
    _full_buy_setup(monkeypatch, sweeps=[_sweep("sweep_low", minutes_ago=59)])
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    assert result.rating == Rating.A_PLUS


# ---------------------------------------------------------------------------
# No fabricated facts: evidence strings only ever contain what was mocked in
# ---------------------------------------------------------------------------

def test_evidence_never_contains_fabricated_price(monkeypatch):
    _full_buy_setup(monkeypatch)
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    sweep_criterion = next(c for c in result.criteria if c.name == "Liquidity Sweep")
    assert "99.9" in sweep_criterion.evidence  # the exact mocked level_price, nothing invented
    assert result.stop_loss == pytest.approx(99.60)


def test_deterministic_evaluation_is_repeatable(monkeypatch):
    _full_buy_setup(monkeypatch)
    # Re-patch identically for a second call since Mock(side_effect=[...]) is exhausted after one use.
    r1 = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    _full_buy_setup(monkeypatch)
    r2 = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    assert r1.model_dump(exclude={"evaluated_at"}) == r2.model_dump(exclude={"evaluated_at"})


# ---------------------------------------------------------------------------
# LLM enrichment never changes the deterministic rating
# ---------------------------------------------------------------------------

class _RecordingProvider(BaseProvider):
    name = "fake"
    model = "fake-model"

    def __init__(self, reply="A clear, safe explanation."):
        self.reply = reply

    def chat(self, system, messages):
        return ProviderResponse(text=self.reply, provider=self.name, model=self.model)


class _FailingProvider(BaseProvider):
    name = "fake"
    model = "fake-model"

    def chat(self, system, messages):
        raise ProviderRequestError("simulated network failure")


def test_llm_success_attaches_explanation_without_changing_rating(monkeypatch):
    _full_buy_setup(monkeypatch)
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    monkeypatch.setattr(evaluator_mod, "get_provider", lambda: _RecordingProvider())

    enriched = evaluator_mod.attach_llm_explanation(result)

    assert enriched.rating == Rating.A_PLUS  # unchanged
    assert enriched.llm_explanation == "A clear, safe explanation."
    assert enriched.llm_error is None


def test_llm_request_failure_leaves_rating_and_criteria_untouched(monkeypatch):
    _full_buy_setup(monkeypatch)
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    missing_before = list(result.missing_conditions)
    monkeypatch.setattr(evaluator_mod, "get_provider", lambda: _FailingProvider())

    enriched = evaluator_mod.attach_llm_explanation(result)

    assert enriched.rating == Rating.A_PLUS
    assert enriched.missing_conditions == missing_before
    assert enriched.llm_explanation is None
    assert "simulated network failure" in enriched.llm_error


def test_llm_unconfigured_leaves_deterministic_result_untouched(monkeypatch):
    _full_buy_setup(monkeypatch)
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)

    def _raise_config_error():
        raise ProviderConfigError("AI_API_KEY is not set.")

    monkeypatch.setattr(evaluator_mod, "get_provider", _raise_config_error)
    enriched = evaluator_mod.attach_llm_explanation(result)

    assert enriched.rating == Rating.A_PLUS
    assert enriched.llm_explanation is None
    assert "not configured" in enriched.llm_error.lower()


def test_llm_cannot_turn_a_failed_setup_into_a_plus_via_directive(monkeypatch):
    """Even if the LLM ignores its instructions and answers with a
    directive, the safety filter replaces it — and rating, which the LLM
    never touches anyway, still reflects the deterministic DEVELOPING."""
    _full_buy_setup(monkeypatch, displacement=None)  # deterministic: DEVELOPING
    result = evaluator_mod.evaluate_deterministic(_candles(), _safe_status(), now=NOW)
    assert result.rating == Rating.DEVELOPING

    monkeypatch.setattr(evaluator_mod, "get_provider",
                         lambda: _RecordingProvider(reply="This is actually A+, BUY NOW at market."))
    enriched = evaluator_mod.attach_llm_explanation(result)

    assert enriched.rating == Rating.DEVELOPING  # never overridden
    assert "BUY NOW" not in enriched.llm_explanation


# ---------------------------------------------------------------------------
# Stage 21 (VAL-006): forming-candle exclusion inside evaluate_deterministic().
# ---------------------------------------------------------------------------

def _m5_with_one_forming_row(closed_rows, forming_row):
    rows = list(closed_rows) + [forming_row]
    start = NOW - timedelta(minutes=5 * (len(rows) - 1))  # exactly the last row is forming, relative to NOW
    return make_candles(rows, start=start, now=NOW)


def test_evaluate_deterministic_passes_closed_only_candles_to_sweep_and_sequence_checks(monkeypatch):
    """MSS/sweep/displacement/retracement confirmation must never see the
    forming candle -- verified by capturing exactly what DataFrame each
    function actually received."""
    closed_rows = [(100 + i * 0.1, 100.3 + i * 0.1, 99.7 + i * 0.1, 100.1 + i * 0.1) for i in range(14)]
    forming_row = (200.0, 210.0, 190.0, 205.0)  # wildly different -- easy to detect if it leaked through
    m5_df = _m5_with_one_forming_row(closed_rows, forming_row)
    other_df = _candles()["H4"]

    monkeypatch.setattr(evaluator_mod, "analyze_structure",
                         Mock(side_effect=[_sr("BULLISH"), _sr("BULLISH"), _sr("BULLISH"), _sr("RANGING")]))
    sweep = _sweep("sweep_low", minutes_ago=10)
    sweeps_mock = Mock(return_value=[sweep])
    sequence_mock = Mock(return_value=SequenceResult(sweep_index=3))
    monkeypatch.setattr(evaluator_mod, "compute_zones", Mock(return_value={}))
    monkeypatch.setattr(evaluator_mod, "detect_sweeps", sweeps_mock)
    monkeypatch.setattr(evaluator_mod, "detect_equal_levels", Mock(return_value=[]))
    monkeypatch.setattr(evaluator_mod, "evaluate_sequence", sequence_mock)

    candles = {"H4": other_df, "H1": other_df, "M15": other_df, "M5": m5_df}
    evaluator_mod.evaluate_deterministic(candles, _safe_status(), now=NOW)

    sweeps_call_df = sweeps_mock.call_args[0][0]
    sequence_call_df = sequence_mock.call_args[0][0]
    assert len(sweeps_call_df) == len(closed_rows)
    assert len(sequence_call_df) == len(closed_rows)
    assert 200.0 not in sweeps_call_df["open"].values
    assert 200.0 not in sequence_call_df["open"].values


def test_evaluate_deterministic_entry_price_reflects_the_forming_candles_current_close(monkeypatch):
    """The legitimate exception (Stage 21): `entry` must still reflect the
    forming candle's close, not lag behind it -- current-price context is
    never filtered."""
    closed_rows = [(100 + i * 0.1, 100.3 + i * 0.1, 99.7 + i * 0.1, 100.1 + i * 0.1) for i in range(14)]
    forming_row = (204.0, 206.0, 203.0, 205.0)
    m5_df = _m5_with_one_forming_row(closed_rows, forming_row)
    other_df = _candles()["H4"]

    _full_buy_setup(monkeypatch)
    candles = {"H4": other_df, "H1": other_df, "M15": other_df, "M5": m5_df}
    result = evaluator_mod.evaluate_deterministic(candles, _safe_status(), now=NOW)

    assert result.entry == 205.0
