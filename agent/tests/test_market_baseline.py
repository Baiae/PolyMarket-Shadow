from decimal import Decimal

from domain.market import MarketIdentity
from domain.orderbook import OrderBook
from evaluation.market_baseline import baseline_from_yes_book


def test_market_baseline_uses_timestamped_yes_midpoint_as_reference():
    market = MarketIdentity(
        gamma_market_id="1",
        condition_id="0xabc",
        yes_token_id="yes",
        no_token_id="no",
        question="Test?",
    )
    book = OrderBook("yes")
    book.apply_snapshot(
        bids=[{"price": "0.48", "size": "20"}],
        asks=[{"price": "0.52", "size": "20"}],
        timestamp_ms=1787421600000,
    )
    baseline = baseline_from_yes_book(market, book)
    assert baseline.probability_yes == Decimal("0.50")
    assert baseline.source == "yes_orderbook_midpoint"
