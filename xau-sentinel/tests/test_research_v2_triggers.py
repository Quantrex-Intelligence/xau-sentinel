"""V2 sequence triggers: order, once-per-sweep, and continuation vs reversal."""
from backtest.research.v2_features import SEQ_TYPES, TRIGGER_DIRECTION, _Side, _step_triggers


def _row(**kw):
    base = {"f_sweep_now": 0, "f_mss_M5": 0, "f_bos_M5": 0, "f_disp": 0}
    base.update(kw)
    return base


def _run(events):
    low, high = _Side(), _Side()
    fired = []
    for i, row in events:
        t = _step_triggers(i, row, low, high)
        fired += [(i, name) for name in SEQ_TYPES if t[name]]
    return fired


def test_reversal_fires_only_after_sweep_then_bullish_mss():
    fired = _run([(10, _row(f_sweep_now=1)), (12, _row(f_mss_M5=1)), (13, _row(f_mss_M5=1))])
    assert (12, "LOW_R1") in fired
    assert [x for x in fired if x[1] == "LOW_R1"] == [(12, "LOW_R1")]  # once per sweep


def test_mss_on_the_sweep_bar_itself_does_not_count():
    fired = _run([(10, _row(f_sweep_now=1, f_mss_M5=1))])
    assert not any(name == "LOW_R1" for _, name in fired)


def test_reversal_r2_needs_mss_before_displacement():
    fired = _run([(10, _row(f_sweep_now=1)), (11, _row(f_disp=1))])
    assert not any(name == "LOW_R2" for _, name in fired)
    fired = _run([(10, _row(f_sweep_now=1)), (11, _row(f_mss_M5=1)), (12, _row(f_disp=1))])
    assert (12, "LOW_R2") in fired


def test_continuation_c1_on_bearish_bos_after_low_sweep():
    fired = _run([(10, _row(f_sweep_now=1)), (14, _row(f_bos_M5=-1))])
    assert (14, "LOW_C1") in fired
    assert TRIGGER_DIRECTION["LOW_C1"] == "SELL"


def test_continuation_c2_blocked_once_mss_has_happened():
    fired = _run([(10, _row(f_sweep_now=1)), (11, _row(f_mss_M5=1)), (12, _row(f_disp=-1))])
    assert not any(name == "LOW_C2" for _, name in fired)
    fired = _run([(10, _row(f_sweep_now=1)), (12, _row(f_disp=-1))])
    assert (12, "LOW_C2") in fired


def test_new_sweep_resets_the_side_and_sequences_are_directional():
    fired = _run([(10, _row(f_sweep_now=1)), (11, _row(f_mss_M5=1)), (20, _row(f_sweep_now=1)),
                  (22, _row(f_mss_M5=1))])
    assert [x for x in fired if x[1] == "LOW_R1"] == [(11, "LOW_R1"), (22, "LOW_R1")]
    assert TRIGGER_DIRECTION["LOW_R1"] == "BUY" and TRIGGER_DIRECTION["HIGH_R1"] == "SELL"


def test_sweep_window_expires():
    fired = _run([(10, _row(f_sweep_now=1)), (30, _row(f_mss_M5=1))])
    assert not any(name == "LOW_R1" for _, name in fired)
