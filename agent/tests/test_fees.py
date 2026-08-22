from decimal import Decimal

from domain.market import MarketIdentity
from execution_fees import taker_fee


def market(rate="0.04", exponent="1", enabled=True):
    return MarketIdentity(
        gamma_market_id="1",
        condition_id="0xabc",
        yes_token_id="yes",
        no_token_id="no",
        question="Test?",
        fees_enabled=enabled,
        fee_rate=Decimal(rate),
        fee_exponent=Decimal(exponent),
    )


def test_current_fee_curve_at_fifty_percent():
    # 100 * .04 * .5 * .5 == 1 USDC
    assert taker_fee(Decimal("100"), Decimal("0.5"), market()) == Decimal("1.00000")


def test_fee_is_symmetric_around_half():
    left = taker_fee(Decimal("100"), Decimal("0.3"), market())
    right = taker_fee(Decimal("100"), Decimal("0.7"), market())
    assert left == right == Decimal("0.84000")


def test_fee_disabled_is_zero():
    assert taker_fee(Decimal("100"), Decimal("0.5"), market(enabled=False)) == 0
