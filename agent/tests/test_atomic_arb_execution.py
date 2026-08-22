from decimal import Decimal

from accounting.ledger import Ledger
from domain.market import MarketIdentity
from domain.orderbook import OrderBook
from paper_broker import PaperBroker


def market():
    return MarketIdentity(
        gamma_market_id="1", condition_id="0xabc",
        yes_token_id="yes", no_token_id="no", question="Test?",
    )


def book(token, price, size="10"):
    b = OrderBook(token)
    b.apply_snapshot(bids=[], asks=[{"price": price, "size": size}], timestamp_ms=1)
    return b


def test_binary_pair_commits_equal_shares_atomically():
    ledger = Ledger(initial_cash="100")
    yes, no = PaperBroker(ledger).buy_binary_pair(
        order_id="arb-1",
        market=market(),
        shares="10",
        yes_book=book("yes", "0.45"),
        no_book=book("no", "0.45"),
    )
    assert yes.status == no.status == "FILLED"
    positions = sorted(ledger.positions(), key=lambda p: p.side)
    assert len(positions) == 2
    assert positions[0].shares == positions[1].shares == Decimal("10")
    assert ledger.cash == Decimal("91.00")


def test_pair_rejects_without_writing_either_leg_when_depth_is_missing():
    ledger = Ledger(initial_cash="100")
    yes, no = PaperBroker(ledger).buy_binary_pair(
        order_id="arb-1",
        market=market(),
        shares="10",
        yes_book=book("yes", "0.45"),
        no_book=book("no", "0.45", size="5"),
    )
    assert yes.status == no.status == "INSUFFICIENT_LIQUIDITY"
    assert ledger.positions() == []
    assert ledger.cash == Decimal("100")
