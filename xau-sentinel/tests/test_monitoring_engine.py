"""Tests for ai/monitoring/engine.py::run_monitoring_cycle() — every
underlying dependency monkeypatched (same technique
tests/test_strategy_contextual_analysis.py already uses for
evaluate_current_setup()'s dependencies): first cycle establishes a
baseline with zero alerts, a changed mock on the second cycle produces
exactly the right alert, an unchanged third cycle produces zero (in-memory
dedup), and the engine never touches an LLM provider."""
import inspect
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

import config
from ai.monitoring import engine, store
from risk.models import AccountType, FundedNextStatus, Phase, SafetyLevel
from tests.conftest import flat_candles, make_candles
from tests.test_structure import BULLISH_POINTS, _ramp_path


def _candles():
    return {tf: flat_candles(60, price=3700.0, tf_minutes=m) for tf, m in
            (("M5", 5), ("M15", 15), ("H1", 60), ("H4", 240))}


def _fn_status(safety_level=SafetyLevel.SAFE):
    return FundedNextStatus(
        account_type=AccountType.STELLAR_2STEP, phase=Phase.CHALLENGE, mode="mock", data_available=True,
        safety_level=safety_level, reason="ok", daily_loss_used_pct=10.0, max_drawdown_used_pct=5.0,
    )


@pytest.fixture(autouse=True)
def _isolated_monitoring_table(temp_db):
    store.init_table()
    return temp_db


@pytest.fixture(autouse=True)
def _patch_dependencies(monkeypatch):
    monkeypatch.setattr(engine.market_data, "get_all_candles", lambda count=300: _candles())
    monkeypatch.setattr(engine.settings_store, "get_settings",
                         lambda: {"account_type": "stellar_2step", "phase": "challenge", "consistency_enabled": False})
    monkeypatch.setattr(engine, "compute_status", lambda *a, **k: _fn_status())

    class _FakeMiContext:
        data_available = True
        macro = None
        gold_fundamentals = None
        cross_asset = None
        events = []
        news = []
        sources = []

    monkeypatch.setattr(engine.mi_context, "build_market_intelligence_context", lambda: _FakeMiContext())


def test_first_cycle_establishes_baseline_with_no_alerts():
    created = engine.run_monitoring_cycle()
    assert created == []


def test_unchanged_second_cycle_creates_no_alerts():
    engine.run_monitoring_cycle()
    created = engine.run_monitoring_cycle()
    assert created == []


def test_live_mode_connects_mt5_before_fetching_candles_when_not_already_connected(monkeypatch):
    """OP-001 (docs/validation/OPERATIONAL_ISSUES.md): a cold start in
    MODE=live previously never connected MT5 on its own — only a UI/API
    request did, via app.py's/api/snapshot.py's own copy of this same idiom.
    Proves the fix by asserting connect() is actually called, not just that
    the cycle doesn't crash (get_all_candles is itself mocked above, so a
    missing connect() call wouldn't fail this test any other way)."""
    monkeypatch.setattr(config, "IS_LIVE", True)
    monkeypatch.setattr(engine.connection, "is_connected", lambda: False)
    connect_mock = Mock()
    monkeypatch.setattr(engine.connection, "connect", connect_mock)

    engine.run_monitoring_cycle()

    connect_mock.assert_called_once()


def test_live_mode_does_not_reconnect_mt5_when_already_connected(monkeypatch):
    """The other half of OP-001's fix: connect() shouldn't be called every
    cycle once already connected (connect() itself isn't a no-op — it
    re-runs mt5.initialize()/login() every call per mt5/connection.py)."""
    monkeypatch.setattr(config, "IS_LIVE", True)
    monkeypatch.setattr(engine.connection, "is_connected", lambda: True)
    connect_mock = Mock()
    monkeypatch.setattr(engine.connection, "connect", connect_mock)

    engine.run_monitoring_cycle()

    connect_mock.assert_not_called()


def test_risk_status_transition_creates_exactly_one_alert(monkeypatch):
    engine.run_monitoring_cycle()  # baseline: SAFE

    monkeypatch.setattr(engine, "compute_status", lambda *a, **k: _fn_status(SafetyLevel.CRITICAL))
    created = engine.run_monitoring_cycle()

    assert len(created) == 1
    assert created[0].type.value == "RISK_STATUS_CHANGED"
    assert created[0].severity.value == "CRITICAL"


def test_risk_status_transition_does_not_duplicate_on_repeated_identical_cycles(monkeypatch):
    engine.run_monitoring_cycle()  # baseline: SAFE
    monkeypatch.setattr(engine, "compute_status", lambda *a, **k: _fn_status(SafetyLevel.CRITICAL))
    engine.run_monitoring_cycle()  # transition: 1 alert

    created_again = engine.run_monitoring_cycle()  # still CRITICAL
    assert created_again == []

    all_alerts = store.list_alerts(limit=100)
    critical_alerts = [a for a in all_alerts if a.type.value == "RISK_STATUS_CHANGED"]
    assert len(critical_alerts) == 1


def test_created_alerts_are_actually_persisted(monkeypatch):
    engine.run_monitoring_cycle()
    monkeypatch.setattr(engine, "compute_status", lambda *a, **k: _fn_status(SafetyLevel.WARNING))
    engine.run_monitoring_cycle()

    stored = store.list_alerts(limit=100)
    assert len(stored) == 1
    assert stored[0].id is not None


def test_reset_state_clears_baseline(monkeypatch):
    """With no in-memory AND no persisted baseline (a fresh install), the
    first cycle only baselines. (DEP-004: reset_state() alone now behaves
    like a restart and restores the persisted row; see the tests below.)"""
    engine.run_monitoring_cycle()  # baseline: SAFE
    engine.reset_state()
    store.clear_baseline()

    monkeypatch.setattr(engine, "compute_status", lambda *a, **k: _fn_status(SafetyLevel.CRITICAL))
    created = engine.run_monitoring_cycle()  # treated as a NEW baseline, not a transition
    assert created == []


def test_a_bad_cycle_never_crashes_run_forever_loop(monkeypatch):
    """run_forever() wraps each cycle in try/except — verified structurally
    since actually running the async loop would sleep indefinitely."""
    source = inspect.getsource(engine.run_forever)
    assert "except Exception" in source
    assert "await asyncio.sleep" in source


def _source_without_module_docstring(module) -> str:
    """Strips the module's own docstring by AST line range before a
    substring search — the docstring explains this file's safety
    guarantees in prose using the same words being searched for, which
    would otherwise false-positive a plain source-text search on itself
    (the same fix ai/strategy/evidence.py's equivalent test already uses)."""
    import ast
    source = inspect.getsource(module)
    tree = ast.parse(source)
    lines = source.splitlines()
    if tree.body and isinstance(tree.body[0], ast.Expr) and isinstance(tree.body[0].value, ast.Constant):
        node = tree.body[0]
        lines = lines[:node.lineno - 1] + lines[node.end_lineno:]
    return "\n".join(lines)


def test_engine_never_touches_an_llm_provider():
    """Structural guarantee: engine.py calls evaluate_deterministic()
    directly, never evaluate_current_setup()/attach_llm_explanation() — no
    code path here reaches an LLM."""
    code = _source_without_module_docstring(engine)
    for banned in ("get_provider", ".chat(", "attach_llm_explanation", "evaluate_current_setup"):
        assert banned not in code


def test_engine_imports_evaluate_deterministic_not_the_llm_wrapper():
    assert engine.evaluate_deterministic.__name__ == "evaluate_deterministic"


# ---------------------------------------------------------------------------
# Stage 21 (VAL-006): forming-candle-only movement must never produce a
# false transition -- detect_setup()/evaluate_deterministic() (the only
# things _build_bundle() calls) already filter to closed candles, so this
# proves that guarantee holds at the monitoring layer too, with zero
# changes needed to engine.py itself.
# ---------------------------------------------------------------------------

def _m5_bullish_history(extra_forming_close=None):
    """A known-good bullish HH/HL M5 sequence (same scenario as
    tests/test_structure.py's PULLBACK-flip test). With no
    `extra_forming_close`, every row is CLOSED. With one given, one more
    row is appended and made deliberately FORMING -- a close dramatic
    enough (well below the L112 pivot) to flip M5 to PULLBACK if it were
    (incorrectly) treated as closed."""
    path = _ramp_path(BULLISH_POINTS[:6], steps_per_leg=7)  # last confirmed low = L112 (HL)
    values = list(path) + [113, 114, 115]  # 3 confirming bars, stays above L112
    if extra_forming_close is not None:
        values = values + [extra_forming_close]
    rows = [(v, v, v, v) for v in values]

    start = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)
    if extra_forming_close is not None:
        now = start + timedelta(minutes=5 * (len(rows) - 1))  # only the appended row is forming
    else:
        now = start + timedelta(minutes=5 * len(rows))  # everything closed
    return make_candles(rows, start=start, now=now)


def test_forming_candle_only_movement_never_produces_a_false_transition(monkeypatch):
    other_tf_candles = {tf: flat_candles(60, price=115.0, tf_minutes=m)
                         for tf, m in (("M15", 15), ("H1", 60), ("H4", 240))}

    baseline_m5 = _m5_bullish_history()
    monkeypatch.setattr(engine.market_data, "get_all_candles",
                         lambda count=300: {"M5": baseline_m5, **other_tf_candles})
    engine.run_monitoring_cycle()  # establishes the baseline snapshot

    # Same closed history, plus one forming row that would flip M5 to
    # PULLBACK (and thus change setup_direction/aplus_direction) if it
    # leaked into structural analysis.
    forming_m5 = _m5_bullish_history(extra_forming_close=100.0)
    monkeypatch.setattr(engine.market_data, "get_all_candles",
                         lambda count=300: {"M5": forming_m5, **other_tf_candles})
    created = engine.run_monitoring_cycle()

    assert created == []


# ---------------------------------------------------------------------------
# Stage 23B
# ---------------------------------------------------------------------------

def test_detect_setup_receives_the_cycles_own_now(monkeypatch):
    """Stage 23B follow-up to 23A: detect_setup() must judge candle closure
    against the same cycle clock evaluate_deterministic() gets."""
    seen = {}
    real_detect = engine.detect_setup
    real_eval = engine.evaluate_deterministic

    def _detect(candles, *args, **kwargs):
        seen["setup_now"] = kwargs.get("now")
        return real_detect(candles, *args, **kwargs)

    def _evaluate(candles, status, **kwargs):
        seen["strategy_now"] = kwargs.get("now")
        return real_eval(candles, status, **kwargs)

    monkeypatch.setattr(engine, "detect_setup", _detect)
    monkeypatch.setattr(engine, "evaluate_deterministic", _evaluate)
    engine.run_monitoring_cycle()
    assert seen["setup_now"] is not None
    assert seen["setup_now"] == seen["strategy_now"]


def test_insert_that_fails_mid_cycle_does_not_duplicate_on_retry(monkeypatch):
    """VAL-019: the alert row is written, then the cycle dies before the
    baseline advances. The retry re-detects the same transition at a new
    cycle timestamp, but must not store (or send) it twice."""
    engine.run_monitoring_cycle()  # baseline: SAFE
    monkeypatch.setattr(engine, "compute_status", lambda *a, **k: _fn_status(SafetyLevel.CRITICAL))

    real_create = store.create_alert

    def _create_then_fail(alert):
        real_create(alert)
        raise RuntimeError("simulated failure after the insert")

    monkeypatch.setattr(engine.store, "create_alert", _create_then_fail)
    with pytest.raises(RuntimeError):
        engine.run_monitoring_cycle()

    monkeypatch.setattr(engine.store, "create_alert", real_create)
    assert engine.run_monitoring_cycle() == []  # the retry dedups against the row already there
    risk_alerts = [a for a in store.list_alerts(limit=100) if a.type.value == "RISK_STATUS_CHANGED"]
    assert len(risk_alerts) == 1


def test_failing_purge_still_advances_the_baseline(monkeypatch):
    """VAL-019: a purge failure after the alerts are persisted must not pin
    the diff to the old baseline (which re-detected the transition and, with
    cycle-timestamped keys, re-sent it)."""
    engine.run_monitoring_cycle()  # baseline: SAFE
    monkeypatch.setattr(engine, "compute_status", lambda *a, **k: _fn_status(SafetyLevel.WARNING))

    def _boom(days):
        raise RuntimeError("purge failed")

    monkeypatch.setattr(engine.store, "purge_older_than", _boom)
    with pytest.raises(RuntimeError):
        engine.run_monitoring_cycle()
    with pytest.raises(RuntimeError):
        engine.run_monitoring_cycle()

    risk_alerts = [a for a in store.list_alerts(limit=100) if a.type.value == "RISK_STATUS_CHANGED"]
    assert len(risk_alerts) == 1


def _run_one_loop_iteration(module, cycle_name, monkeypatch, cycle):
    """Drives `module.run_forever()` through exactly one cycle: the cycle
    function is replaced by `cycle`, and asyncio.sleep is patched to end
    the otherwise-infinite loop."""
    import asyncio

    class _Stop(Exception):
        pass

    async def _sleep(_seconds):
        raise _Stop()

    monkeypatch.setattr(module, cycle_name, cycle)
    monkeypatch.setattr(module.asyncio, "sleep", _sleep)
    with pytest.raises(_Stop):
        asyncio.run(module.run_forever())


def test_run_forever_runs_the_cycle_off_the_event_loop_thread(monkeypatch):
    """Stage 23B (VAL-021): the blocking cycle runs via asyncio.to_thread,
    never on the event-loop thread itself."""
    import threading
    seen = {}

    def _cycle():
        seen["thread"] = threading.get_ident()

    _run_one_loop_iteration(engine, "run_monitoring_cycle", monkeypatch, _cycle)
    assert seen["thread"] != threading.get_ident()


def test_run_forever_logs_a_failed_cycle(monkeypatch, caplog):
    """Stage 23B (VAL-033): a failed cycle leaves a logged traceback."""
    def _cycle():
        raise RuntimeError("mt5 unreachable")

    with caplog.at_level("ERROR", logger="ai.monitoring.engine"):
        _run_one_loop_iteration(engine, "run_monitoring_cycle", monkeypatch, _cycle)
    assert any("Monitoring cycle failed" in r.getMessage() and r.exc_info for r in caplog.records)


# ---------------------------------------------------------------------------
# DEP-004: the baseline survives a restart
# ---------------------------------------------------------------------------

def test_restart_alerts_a_transition_that_happened_during_the_downtime(monkeypatch):
    """State A (SAFE) is persisted, the process restarts, and the first
    cycle observes B (CRITICAL). Before DEP-004 this re-baselined silently."""
    engine.run_monitoring_cycle()  # baseline: SAFE, persisted
    engine.reset_state()  # simulated restart: in-memory baseline gone

    monkeypatch.setattr(engine, "compute_status", lambda *a, **k: _fn_status(SafetyLevel.CRITICAL))
    created = engine.run_monitoring_cycle()

    assert [a.type.value for a in created] == ["RISK_STATUS_CHANGED"]
    assert created[0].payload["previous_status"] == "SAFE"


def test_stale_persisted_baseline_is_ignored_after_a_restart(monkeypatch):
    """A baseline older than BASELINE_MAX_AGE is not diffed against: the
    first cycle only re-baselines, and never alerts."""
    engine.run_monitoring_cycle()  # baseline: SAFE, persisted
    engine.reset_state()

    later = datetime.now(timezone.utc) + engine.BASELINE_MAX_AGE + timedelta(minutes=1)
    monkeypatch.setattr(engine, "_now", lambda: later)
    monkeypatch.setattr(engine, "compute_status", lambda *a, **k: _fn_status(SafetyLevel.CRITICAL))
    assert engine.run_monitoring_cycle() == []
    # ...and the new state is now the persisted baseline.
    snapshot, _ = store.load_baseline()
    assert snapshot.risk_safety_level == "CRITICAL"


def test_future_dated_persisted_baseline_is_ignored(monkeypatch):
    """Clock skew (saved_at after `now`) is treated as untrustworthy."""
    engine.run_monitoring_cycle()
    engine.reset_state()
    earlier = datetime.now(timezone.utc) - timedelta(minutes=1)
    monkeypatch.setattr(engine, "_now", lambda: earlier)
    monkeypatch.setattr(engine, "compute_status", lambda *a, **k: _fn_status(SafetyLevel.CRITICAL))
    assert engine.run_monitoring_cycle() == []


def test_restart_does_not_duplicate_an_alert_already_stored_before_the_crash(monkeypatch):
    """Crash between inserting A->B and persisting B: the restarted process
    restores A, re-detects A->B, and the baseline-timestamp dedup key
    (VAL-019) makes it a no-op instead of a duplicate."""
    engine.run_monitoring_cycle()  # SAFE persisted
    monkeypatch.setattr(engine, "compute_status", lambda *a, **k: _fn_status(SafetyLevel.CRITICAL))

    real_save = engine.store.save_baseline

    def _no_persist(snapshot, saved_at=None):
        raise RuntimeError("process died before the baseline was saved")

    monkeypatch.setattr(engine.store, "save_baseline", _no_persist)
    assert len(engine.run_monitoring_cycle()) == 1  # alert stored; the save failed but the cycle survived
    monkeypatch.setattr(engine.store, "save_baseline", real_save)

    engine.reset_state()  # restart: restores SAFE, observes CRITICAL again
    assert engine.run_monitoring_cycle() == []
    risk = [a for a in store.list_alerts(limit=100) if a.type.value == "RISK_STATUS_CHANGED"]
    assert len(risk) == 1


def test_baseline_persistence_failure_keeps_the_in_memory_baseline(monkeypatch, caplog):
    def _boom(snapshot, saved_at=None):
        raise RuntimeError("disk full")

    monkeypatch.setattr(engine.store, "save_baseline", _boom)
    with caplog.at_level("ERROR", logger="ai.monitoring.engine"):
        assert engine.run_monitoring_cycle() == []
    assert any("persist the monitoring baseline" in r.getMessage() for r in caplog.records)

    monkeypatch.setattr(engine, "compute_status", lambda *a, **k: _fn_status(SafetyLevel.WARNING))
    assert len(engine.run_monitoring_cycle()) == 1  # diffed against the in-memory baseline


def test_unreadable_persisted_baseline_falls_back_to_a_fresh_baseline(monkeypatch):
    from journal.database import get_connection
    engine.run_monitoring_cycle()
    with get_connection() as conn:
        conn.execute("UPDATE monitoring_baseline SET snapshot = '{not json'")
        conn.commit()
    engine.reset_state()
    monkeypatch.setattr(engine, "compute_status", lambda *a, **k: _fn_status(SafetyLevel.CRITICAL))
    assert engine.run_monitoring_cycle() == []
