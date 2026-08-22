from decimal import Decimal

from domain.market import MarketIdentity
from domain.orderbook import OrderBook
from strategy.arbitrage import ExecutableArbitrageDetector


def market(*, fees=False, fee_rate="0"):
    return MarketIdentity(
        gamma_market_id="1",
        condition_id="0xabc",
        yes_token_id="yes",
        no_token_id="no",
        question="Test?",
        fees_enabled=fees,
        fee_rate=Decimal(fee_rate),
    )


def book(token, asks):
    b = OrderBook(token)
    b.apply_snapshot(bids=[], asks=[{"price": p, "size": s} for p, s in asks], timestamp_ms=1)
    return b


def test_detects_executable_equal_share_arb():
    detector = ExecutableArbitrageDetector(minimum_net_profit="0.01")
    opportunity = detector.evaluate(
        market(),
        book("yes", [("0.45", "10")]),
        book("no", [("0.45", "20")]),
    )
    assert opportunity is not None
    assert opportunity.matched_shares == Decimal("10")
    assert opportunity.locked_payout == Decimal("10")
    assert opportunity.total_cost == Decimal("9.00")
    assert opportunity.net_profit == Decimal("1.00")


def test_depth_can_make_only_shallow_prefix_profitable():
    detector = ExecutableArbitrageDetector(minimum_net_profit="0.01")
    opportunity = detector.evaluate(
        market(),
        book("yes", [("0.40", "10"), ("0.70", "90")]),
        book("no", [("0.40", "100")]),
    )
    assert opportunity is not None
    assert opportunity.matched_shares == Decimal("10")
    assert opportunity.net_profit == Decimal("2.00")


def test_fees_can_destroy_nominal_arb():
    detector = ExecutableArbitrageDetector(minimum_net_profit="0.01")
    opportunity = detector.evaluate(
        market(fees=True, fee_rate="0.07"),
        book("yes", [("0.49", "100")]),
        book("no", [("0.49", "100")]),
    )
    assert opportunity is None


def test_no_signal_when_one_leg_has_no_depth():
    detector = ExecutableArbitrageDetector()
    assert detector.evaluate(
        market(), book("yes", [("0.4", "10")]), book("no", [])
    ) is None
