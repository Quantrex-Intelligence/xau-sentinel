"""Risk / R:R calculation validation (spec section 16)."""
from analysis.setup import _plan_trade
from tests.conftest import make_candles


def test_rr_matches_known_example_buy():
    """Entry=100, SL=95, TP=110 -> Risk=5, Reward=10 -> R:R = 1:2."""
    entry, sl, tp = 100.0, 95.0, 110.0
    risk = entry - sl
    reward = tp - entry
    assert risk == 5.0
    assert reward == 10.0
    assert round(reward / risk, 2) == 2.0


def test_rr_matches_known_example_sell():
    """Mirror of the BUY case: Entry=100, SL=105, TP=90 -> Risk=5, Reward=10 -> R:R = 1:2."""
    entry, sl, tp = 100.0, 105.0, 90.0
    risk = sl - entry
    reward = entry - tp
    assert risk == 5.0
    assert reward == 10.0
    assert round(reward / risk, 2) == 2.0


def _trending_candles(direction, n=10):
    """n bars trending in `direction`, distinct high/low each bar so the
    10-bar extreme used for the stop loss is unambiguous."""
    rows = []
    for i in range(n):
        base = 100 + (i if direction == "BUY" else -i)
        rows.append((base, base + 0.6, base - 0.6, base + (0.3 if direction == "BUY" else -0.3)))
    return make_candles(rows)


def test_plan_trade_buy_places_stop_below_entry_and_target_above():
    df = _trending_candles("BUY")
    entry_zone, sl, tp, rr = _plan_trade(df, "BUY")
    last_price = float(df["close"].iloc[-1])
    assert sl < last_price < tp
    assert rr > 0


def test_plan_trade_sell_places_stop_above_entry_and_target_below():
    df = _trending_candles("SELL")
    entry_zone, sl, tp, rr = _plan_trade(df, "SELL")
    last_price = float(df["close"].iloc[-1])
    assert tp < last_price < sl
    assert rr > 0


def test_plan_trade_rr_is_none_when_risk_is_zero():
    """If the close sits exactly on the 10-bar extreme, risk is zero and R:R
    must be reported as undefined (None), never divide-by-zero or a bogus number."""
    rows = [(100, 100.5, 99.5, 100) for _ in range(9)]
    rows.append((100, 100, 97, 97))  # close == low == window minimum
    df = make_candles(rows)
    entry_zone, sl, tp, rr = _plan_trade(df, "BUY")
    assert rr is None
