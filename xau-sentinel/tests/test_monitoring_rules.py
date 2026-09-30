"""Tests for ai/monitoring/rules.py — one deterministic rule per AlertType.
Every test constructs MonitoringSnapshot/RawEvaluationBundle directly
(never depends on live mock randomness), proving: the right transition
fires the right alert with the right severity/payload, the reverse/no-op
case fires nothing, and the first-cycle baseline (previous=None) never
fires anything."""
import inspect

from ai.market_intelligence.quality import EventRiskItem
from ai.monitoring import rules
from ai.monitoring.models import AlertType, MonitoringSnapshot, RawEvaluationBundle, Severity
from ai.strategy.schemas import Criterion, CriterionStatus, FundedNextGateOut, Rating, StrategyEvaluationOut

_TS = "2026-01-01T00:00:00+00:00"


class _FakeSetupResult:
    def __init__(self, state="DEVELOPING", direction="BUY", checklist=None, reason="testing"):
        self.state = state
        self.direction = direction
        self.checklist = checklist or {}
        self.reason = reason


class _FakeFundedNextStatus:
    def __init__(self, safety_level="SAFE", reason="ok", daily_loss_used_pct=10.0, max_drawdown_used_pct=5.0):
        self.safety_level = safety_level
        self.reason = reason
        self.daily_loss_used_pct = daily_loss_used_pct
        self.max_drawdown_used_pct = max_drawdown_used_pct


class _FakeCategoryQuality:
    def __init__(self, quality="GOOD"):
        self.quality = quality


class _FakeIntelligenceSummary:
    def __init__(self, quality="GOOD"):
        self.macro = _FakeCategoryQuality(quality)
        self.cross_asset = _FakeCategoryQuality(quality)
        self.news = _FakeCategoryQuality(quality)


def _snapshot(**overrides):
    defaults = dict(
        setup_state="DEVELOPING", setup_direction="BUY", aplus_rating="DEVELOPING", aplus_direction="BUY",
        risk_safety_level="SAFE", mi_overall_quality="AVAILABLE", nearby_high_impact_event_key=None,
        timestamp=_TS,
    )
    defaults.update(overrides)
    return MonitoringSnapshot(**defaults)


def _strategy_result(**overrides):
    base = dict(
        rating=Rating.DEVELOPING, direction="BUY", criteria=[
            Criterion(name="Liquidity Sweep", status=CriterionStatus.PASSED, evidence="swept"),
        ],
        missing_conditions=[], invalidation=None, entry=3700.0, stop_loss=3690.0, target=3730.0, rr=3.0,
        fundednext=FundedNextGateOut(data_available=True, safety_level="SAFE", daily_loss_used_pct=10.0,
                                      max_daily_loss_used_pct_allowed=50.0, reason="SAFE"),
        evaluated_at=_TS, candidate_sweep_time="2026-01-01T00:00:00+00:00",
    )
    base.update(overrides)
    return StrategyEvaluationOut(**base)


def _bundle(setup_result=None, strategy_result=None, fundednext_status=None,
            intelligence_summary=None, nearest_event=None, nearest_event_country=None):
    return RawEvaluationBundle(
        setup_result=setup_result or _FakeSetupResult(),
        strategy_result=strategy_result or _strategy_result(),
        fundednext_status=fundednext_status or _FakeFundedNextStatus(),
        intelligence_summary=intelligence_summary or _FakeIntelligenceSummary(),
        nearest_event=nearest_event, nearest_event_country=nearest_event_country,
    )


# ---------------------------------------------------------------------------
# SETUP_STATE_CHANGED
# ---------------------------------------------------------------------------

def test_setup_state_changed_fires_on_transition():
    previous = _snapshot(setup_state="NO SETUP")
    current = _snapshot(setup_state="DEVELOPING")
    alerts = rules.setup_state_changed(previous, current, _bundle())
    assert len(alerts) == 1
    assert alerts[0].type == AlertType.SETUP_STATE_CHANGED
    assert alerts[0].severity == Severity.INFO
    assert alerts[0].payload["previous_state"] == "NO SETUP"
    assert alerts[0].payload["current_state"] == "DEVELOPING"


def test_setup_state_changed_does_not_fire_when_unchanged():
    previous = _snapshot(setup_state="DEVELOPING")
    current = _snapshot(setup_state="DEVELOPING")
    assert rules.setup_state_changed(previous, current, _bundle()) == []


def test_setup_state_changed_does_not_fire_on_first_cycle():
    current = _snapshot(setup_state="DEVELOPING")
    assert rules.setup_state_changed(None, current, _bundle()) == []


# ---------------------------------------------------------------------------
# APLUS_SETUP_DETECTED / APLUS_SETUP_INVALIDATED
# ---------------------------------------------------------------------------

def test_aplus_setup_detected_fires_on_transition_into_a_plus():
    previous = _snapshot(aplus_rating="DEVELOPING")
    current = _snapshot(aplus_rating="A+")
    bundle = _bundle(strategy_result=_strategy_result(rating=Rating.A_PLUS))
    alerts = rules.aplus_setup_detected(previous, current, bundle)
    assert len(alerts) == 1
    assert alerts[0].type == AlertType.APLUS_SETUP_DETECTED
    assert alerts[0].payload["entry"] == 3700.0
    assert alerts[0].payload["rr"] == 3.0


def test_aplus_setup_detected_does_not_fire_when_already_a_plus():
    previous = _snapshot(aplus_rating="A+")
    current = _snapshot(aplus_rating="A+")
    assert rules.aplus_setup_detected(previous, current, _bundle()) == []


def test_aplus_setup_detected_does_not_fire_on_first_cycle():
    current = _snapshot(aplus_rating="A+")
    assert rules.aplus_setup_detected(None, current, _bundle()) == []


def test_aplus_setup_invalidated_fires_on_transition_out_of_a_plus():
    previous = _snapshot(aplus_rating="A+", aplus_direction="BUY")
    current = _snapshot(aplus_rating="INVALID")
    bundle = _bundle(strategy_result=_strategy_result(rating=Rating.INVALID, invalidation="M5 structure broke"))
    alerts = rules.aplus_setup_invalidated(previous, current, bundle)
    assert len(alerts) == 1
    assert alerts[0].type == AlertType.APLUS_SETUP_INVALIDATED
    assert "M5 structure broke" in alerts[0].message
    assert alerts[0].payload["invalidation"] == "M5 structure broke"


def test_aplus_setup_invalidated_does_not_fire_when_never_was_a_plus():
    previous = _snapshot(aplus_rating="DEVELOPING")
    current = _snapshot(aplus_rating="INVALID")
    assert rules.aplus_setup_invalidated(previous, current, _bundle()) == []


def test_aplus_never_fires_both_detected_and_invalidated_for_the_same_transition():
    previous = _snapshot(aplus_rating="DEVELOPING")
    current = _snapshot(aplus_rating="A+")
    bundle = _bundle(strategy_result=_strategy_result(rating=Rating.A_PLUS))
    assert rules.aplus_setup_detected(previous, current, bundle) != []
    assert rules.aplus_setup_invalidated(previous, current, bundle) == []


# ---------------------------------------------------------------------------
# RISK_STATUS_CHANGED
# ---------------------------------------------------------------------------

def test_risk_status_changed_fires_with_severity_from_new_level():
    previous = _snapshot(risk_safety_level="SAFE")
    current = _snapshot(risk_safety_level="CRITICAL")
    bundle = _bundle(fundednext_status=_FakeFundedNextStatus(safety_level="CRITICAL"))
    alerts = rules.risk_status_changed(previous, current, bundle)
    assert len(alerts) == 1
    assert alerts[0].severity == Severity.CRITICAL


def test_risk_status_changed_warning_severity_for_warning_level():
    previous = _snapshot(risk_safety_level="SAFE")
    current = _snapshot(risk_safety_level="WARNING")
    alerts = rules.risk_status_changed(previous, current, _bundle())
    assert alerts[0].severity == Severity.WARNING


def test_risk_status_changed_info_severity_recovering_to_safe():
    previous = _snapshot(risk_safety_level="CRITICAL")
    current = _snapshot(risk_safety_level="SAFE")
    alerts = rules.risk_status_changed(previous, current, _bundle())
    assert alerts[0].severity == Severity.INFO


def test_risk_status_changed_does_not_fire_when_unchanged():
    previous = _snapshot(risk_safety_level="WARNING")
    current = _snapshot(risk_safety_level="WARNING")
    assert rules.risk_status_changed(previous, current, _bundle()) == []


# ---------------------------------------------------------------------------
# MARKET_INTELLIGENCE_QUALITY_CHANGED
# ---------------------------------------------------------------------------

def test_mi_quality_changed_fires_warning_on_degradation():
    previous = _snapshot(mi_overall_quality="AVAILABLE")
    current = _snapshot(mi_overall_quality="PARTIALLY_AVAILABLE")
    alerts = rules.market_intelligence_quality_changed(previous, current, _bundle())
    assert len(alerts) == 1
    assert alerts[0].severity == Severity.WARNING


def test_mi_quality_changed_fires_info_on_recovery():
    previous = _snapshot(mi_overall_quality="UNAVAILABLE")
    current = _snapshot(mi_overall_quality="AVAILABLE")
    alerts = rules.market_intelligence_quality_changed(previous, current, _bundle())
    assert alerts[0].severity == Severity.INFO


def test_mi_quality_changed_does_not_fire_when_unchanged():
    previous = _snapshot(mi_overall_quality="AVAILABLE")
    current = _snapshot(mi_overall_quality="AVAILABLE")
    assert rules.market_intelligence_quality_changed(previous, current, _bundle()) == []


# ---------------------------------------------------------------------------
# HIGH_IMPACT_EVENT_NEAR
# ---------------------------------------------------------------------------

def _event_risk_item(**overrides):
    defaults = dict(event="US CPI", importance="HIGH", event_time=_TS, status="UPCOMING",
                     minutes_until=20, assets=["XAUUSD", "USD"], source="real")
    defaults.update(overrides)
    return EventRiskItem(**defaults)


def test_high_impact_event_near_fires_when_a_new_event_enters_the_window():
    previous = _snapshot(nearby_high_impact_event_key=None)
    current = _snapshot(nearby_high_impact_event_key="US CPI:" + _TS)
    bundle = _bundle(nearest_event=_event_risk_item(), nearest_event_country="US")
    alerts = rules.high_impact_event_near(previous, current, bundle)
    assert len(alerts) == 1
    assert alerts[0].severity == Severity.WARNING
    assert alerts[0].payload["minutes_until"] == 20
    assert alerts[0].payload["country"] == "US"
    assert "forecast" not in alerts[0].payload


def test_high_impact_event_near_does_not_repeat_for_the_same_event():
    previous = _snapshot(nearby_high_impact_event_key="US CPI:" + _TS)
    current = _snapshot(nearby_high_impact_event_key="US CPI:" + _TS)
    bundle = _bundle(nearest_event=_event_risk_item())
    assert rules.high_impact_event_near(previous, current, bundle) == []


def test_high_impact_event_near_fires_again_for_a_genuinely_different_event():
    previous = _snapshot(nearby_high_impact_event_key="US CPI:" + _TS)
    current = _snapshot(nearby_high_impact_event_key="FOMC Rate Decision:2026-01-02T00:00:00+00:00")
    bundle = _bundle(nearest_event=_event_risk_item(event="FOMC Rate Decision"))
    alerts = rules.high_impact_event_near(previous, current, bundle)
    assert len(alerts) == 1


def test_high_impact_event_near_does_not_fire_when_nothing_in_window():
    previous = _snapshot(nearby_high_impact_event_key="US CPI:" + _TS)
    current = _snapshot(nearby_high_impact_event_key=None)
    assert rules.high_impact_event_near(previous, current, _bundle()) == []


def test_high_impact_event_near_never_includes_a_predicted_result():
    previous = _snapshot(nearby_high_impact_event_key=None)
    current = _snapshot(nearby_high_impact_event_key="US CPI:" + _TS)
    bundle = _bundle(nearest_event=_event_risk_item())
    alerts = rules.high_impact_event_near(previous, current, bundle)
    text = (alerts[0].title + " " + alerts[0].message).lower()
    assert "will" not in text
    assert "forecast" not in text


# ---------------------------------------------------------------------------
# Dedup keys are stable identity, never random
# ---------------------------------------------------------------------------

def test_dedup_keys_are_stable_not_random():
    previous = _snapshot(setup_state="NO SETUP")
    current = _snapshot(setup_state="DEVELOPING")
    a1 = rules.setup_state_changed(previous, current, _bundle())[0]
    a2 = rules.setup_state_changed(previous, current, _bundle())[0]
    assert a1.dedup_key == a2.dedup_key


def test_transition_dedup_keys_are_anchored_to_the_baseline_not_the_cycle():
    """Stage 23B (VAL-019): a cycle that fails after inserting its alerts
    but before the baseline advances is retried against the SAME previous
    snapshot, at a later cycle timestamp. Every transition key must be
    identical on that retry, so the store's UNIQUE index absorbs it instead
    of storing (and sending) a duplicate."""
    previous = _snapshot(setup_state="NO SETUP", aplus_rating="A+", risk_safety_level="SAFE",
                         mi_overall_quality="AVAILABLE", timestamp="2026-01-01T00:00:00+00:00")
    changed = dict(setup_state="DEVELOPING", aplus_rating="INVALID", risk_safety_level="WARNING",
                   mi_overall_quality="UNAVAILABLE")
    first = rules.evaluate_all(previous, _snapshot(timestamp="2026-01-01T00:00:20+00:00", **changed), _bundle())
    retry = rules.evaluate_all(previous, _snapshot(timestamp="2026-01-01T00:00:40+00:00", **changed), _bundle())

    assert {a.type for a in first} == {
        AlertType.SETUP_STATE_CHANGED, AlertType.APLUS_SETUP_INVALIDATED,
        AlertType.RISK_STATUS_CHANGED, AlertType.MARKET_INTELLIGENCE_QUALITY_CHANGED,
    }
    assert sorted(a.dedup_key for a in first) == sorted(a.dedup_key for a in retry)


def test_same_transition_from_a_later_baseline_is_a_new_alert():
    """The flip side of VAL-019: a genuine repeat (SAFE -> WARNING again,
    after the baseline has moved on) must still be a distinct alert."""
    earlier = rules.risk_status_changed(_snapshot(risk_safety_level="SAFE", timestamp="2026-01-01T00:00:00+00:00"),
                                        _snapshot(risk_safety_level="WARNING"), _bundle())[0]
    later = rules.risk_status_changed(_snapshot(risk_safety_level="SAFE", timestamp="2026-01-02T00:00:00+00:00"),
                                      _snapshot(risk_safety_level="WARNING"), _bundle())[0]
    assert earlier.dedup_key != later.dedup_key


# ---------------------------------------------------------------------------
# Stage 23B (VAL-023): a changed setup while already A+ is announced
# ---------------------------------------------------------------------------

def _aplus_bundle(direction="BUY", sweep="2026-01-01T00:00:00+00:00"):
    return _bundle(strategy_result=_strategy_result(rating=Rating.A_PLUS, direction=direction,
                                                    candidate_sweep_time=sweep))


def test_aplus_setup_detected_fires_when_direction_flips_while_a_plus():
    previous = _snapshot(aplus_rating="A+", aplus_direction="BUY", aplus_candidate_key="2026-01-01T00:00:00+00:00")
    current = _snapshot(aplus_rating="A+", aplus_direction="SELL", aplus_candidate_key="2026-01-01T01:00:00+00:00")
    alerts = rules.aplus_setup_detected(previous, current, _aplus_bundle("SELL", "2026-01-01T01:00:00+00:00"))
    assert len(alerts) == 1
    assert alerts[0].payload["direction"] == "SELL"
    # Never also reported as an invalidation — the rating never left A+.
    assert rules.aplus_setup_invalidated(previous, current, _aplus_bundle("SELL")) == []


def test_aplus_setup_detected_fires_when_a_new_candidate_replaces_the_prior_one():
    previous = _snapshot(aplus_rating="A+", aplus_direction="BUY", aplus_candidate_key="2026-01-01T00:00:00+00:00")
    current = _snapshot(aplus_rating="A+", aplus_direction="BUY", aplus_candidate_key="2026-01-01T02:00:00+00:00")
    old_alert = rules.aplus_setup_detected(_snapshot(aplus_rating="DEVELOPING"), previous, _aplus_bundle())[0]
    alerts = rules.aplus_setup_detected(previous, current, _aplus_bundle(sweep="2026-01-01T02:00:00+00:00"))
    assert len(alerts) == 1
    assert alerts[0].dedup_key != old_alert.dedup_key


def test_aplus_setup_detected_stays_quiet_for_the_same_a_plus_candidate():
    previous = _snapshot(aplus_rating="A+", aplus_direction="BUY", aplus_candidate_key="2026-01-01T00:00:00+00:00")
    current = _snapshot(aplus_rating="A+", aplus_direction="BUY", aplus_candidate_key="2026-01-01T00:00:00+00:00")
    assert rules.aplus_setup_detected(previous, current, _aplus_bundle()) == []


def test_no_rule_module_imports_an_llm_provider():
    """Structural guarantee: the LLM must not decide whether an alert
    condition exists — there is no code path from rules.py to any LLM
    provider at all."""
    source = inspect.getsource(rules)
    for banned in ("get_provider", ".chat(", "attach_llm_explanation", "evaluate_current_setup"):
        assert banned not in source


def test_evaluate_all_aggregates_every_rule():
    previous = _snapshot(setup_state="NO SETUP", risk_safety_level="SAFE")
    current = _snapshot(setup_state="DEVELOPING", risk_safety_level="WARNING")
    alerts = rules.evaluate_all(previous, current, _bundle())
    types = {a.type for a in alerts}
    assert AlertType.SETUP_STATE_CHANGED in types
    assert AlertType.RISK_STATUS_CHANGED in types
