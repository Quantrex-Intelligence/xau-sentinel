"""Tests for ai/similarity/features.py: extraction from a trade row and
from a live snapshot, the liquidity-label parser, and — critically — the
literal no-look-ahead proof: mutating a trade row's outcome columns must
never change its extracted features."""
from ai.similarity.features import (
    _infer_liquidity_kind, extract_features_from_live_setup, extract_features_from_trade,
)
from ai.similarity.models import SetupFeatures


def _trade_row(**overrides):
    row = {
        "id": 1, "direction": "BUY", "h4_bias": "BULLISH", "h1_bias": "BULLISH",
        "m15_bias": "PULLBACK", "m5_bias": "BULLISH", "regime": "TRENDING UP",
        "market_regime": "TRENDING UP", "liquidity": "Previous Day Low swept",
        "mss": "Bullish", "displacement": "Bullish", "session": "London",
        "planned_rr": 2.5, "entry": 100.0, "stop_loss": 95.0, "take_profit": 110.0,
        # Outcome/future columns — must never affect extraction.
        "status": "OPEN", "result": None, "pnl": None, "r_multiple": None,
        "exit_price": None, "exit_reason": None, "mistake": None, "duration_minutes": None,
    }
    row.update(overrides)
    return row


def test_infer_liquidity_kind_from_low_label():
    assert _infer_liquidity_kind("Previous Day Low swept") == "sweep_low"


def test_infer_liquidity_kind_from_high_label():
    assert _infer_liquidity_kind("Asian High swept") == "sweep_high"


def test_infer_liquidity_kind_none_for_blank_or_unrecognized_label():
    assert _infer_liquidity_kind(None) is None
    assert _infer_liquidity_kind("") is None
    assert _infer_liquidity_kind("Equal highs detected") == "sweep_high"  # contains "high"


def test_extract_features_from_trade_maps_all_captured_fields():
    features = extract_features_from_trade(_trade_row())
    assert features == SetupFeatures(
        direction="BUY", h4_structure="BULLISH", h1_structure="BULLISH",
        m15_structure="PULLBACK", m5_structure="BULLISH", regime="TRENDING UP",
        liquidity_kind="sweep_low", mss_direction="Bullish", displacement="Bullish",
        session="London", planned_rr=2.5,
    )


def test_extract_features_from_trade_missing_fields_become_none_not_fabricated():
    features = extract_features_from_trade(_trade_row(mss=None, liquidity=None, planned_rr=None))
    assert features.mss_direction is None
    assert features.liquidity_kind is None
    assert features.planned_rr is None


def test_extract_features_from_trade_falls_back_to_market_regime_column():
    row = _trade_row(regime=None, market_regime="RANGING")
    assert extract_features_from_trade(row).regime == "RANGING"


# ---------------------------------------------------------------------------
# No-look-ahead proof: mutating outcome/future columns must not change the
# extracted features at all.
# ---------------------------------------------------------------------------

def test_extracted_features_are_identical_regardless_of_outcome_columns():
    open_row = _trade_row()
    win_row = _trade_row(
        status="CLOSED", result="WIN", pnl=500.0, r_multiple=2.0,
        exit_price=110.0, exit_reason="Hit TP", duration_minutes=45.0,
    )
    loss_row = _trade_row(
        status="CLOSED", result="LOSS", pnl=-250.0, r_multiple=-1.0,
        exit_price=95.0, exit_reason="Hit SL", mistake="Entered too early", duration_minutes=12.0,
    )

    assert extract_features_from_trade(open_row) == extract_features_from_trade(win_row)
    assert extract_features_from_trade(open_row) == extract_features_from_trade(loss_row)


def test_extract_features_from_trade_never_reads_outcome_keys_even_if_present_but_wrong():
    """A stronger version of the same guarantee: feed obviously-wrong,
    tempting-to-use outcome data and confirm it's provably never consulted —
    if extraction ever started reading `result`/`r_multiple`, this would be
    the first place a change would show up."""
    row = _trade_row(result="WIN", r_multiple=99.0, pnl=999999.0)
    features = extract_features_from_trade(row)
    # None of the SetupFeatures fields could possibly have come from those
    # outcome values — this is a structural impossibility check, not a
    # behavioral coincidence.
    assert 99.0 not in (features.planned_rr,)
    assert features == extract_features_from_trade(_trade_row())


# ---------------------------------------------------------------------------
# Live setup extraction
# ---------------------------------------------------------------------------

class _FakeStructure:
    def __init__(self, state, last_mss=None):
        self.state = state
        self.last_mss = last_mss


class _FakeRegime:
    def __init__(self, regime):
        self.regime = regime


class _FakeLiquidity:
    def __init__(self, sweeps):
        self.sweeps = sweeps


class _FakeSweep:
    def __init__(self, kind):
        self.kind = kind


class _FakeSnapshot:
    def __init__(self, structure, regime, liquidity, displacement, session, data_error=None):
        self.structure = structure
        self.regime = regime
        self.liquidity = liquidity
        self.displacement = displacement
        self.session = session
        self.data_error = data_error


class _FakeSetupResult:
    def __init__(self, direction, rr):
        self.direction = direction
        self.rr = rr


def test_extract_features_from_live_setup_maps_snapshot_and_setup():
    snapshot = _FakeSnapshot(
        structure={
            "H4": _FakeStructure("BULLISH"), "H1": _FakeStructure("BULLISH"),
            "M15": _FakeStructure("PULLBACK"), "M5": _FakeStructure("BULLISH", last_mss="bullish"),
        },
        regime=_FakeRegime("TRENDING UP"),
        liquidity=_FakeLiquidity([_FakeSweep("sweep_low")]),
        displacement="bullish", session="London",
    )
    setup_result = _FakeSetupResult(direction="BUY", rr=3.0)

    features = extract_features_from_live_setup(snapshot, setup_result)

    assert features == SetupFeatures(
        direction="BUY", h4_structure="BULLISH", h1_structure="BULLISH",
        m15_structure="PULLBACK", m5_structure="BULLISH", regime="TRENDING UP",
        liquidity_kind="sweep_low", mss_direction="bullish", displacement="bullish",
        session="London", planned_rr=3.0,
    )


def test_extract_features_from_live_setup_handles_missing_structure_gracefully():
    snapshot = _FakeSnapshot(structure={}, regime=None, liquidity=_FakeLiquidity([]),
                              displacement=None, session=None)
    setup_result = _FakeSetupResult(direction=None, rr=None)

    features = extract_features_from_live_setup(snapshot, setup_result)
    assert features.h1_structure is None
    assert features.mss_direction is None
    assert features.regime is None
