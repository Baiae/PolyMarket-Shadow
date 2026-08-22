from decimal import Decimal

from accounting.ledger import Ledger
from domain.market import MarketIdentity
from domain.orderbook import OrderBook
from paper_broker import PaperBroker


def identity(*, fees=False, minimum_order_size=None):
    return MarketIdentity(
        gamma_market_id="1",
        condition_id="0xabc",
        yes_token_id="yes",
        no_token_id="no",
        question="Test?",
        fees_enabled=fees,
        fee_rate=Decimal("0.04") if fees else Decimal("0"),
        minimum_order_size=(
            Decimal(str(minimum_order_size)) if minimum_order_size is not None else None
        ),
    )


def book(token="yes"):
    result = OrderBook(token)
    result.apply_snapshot(
        bids=[{"price": "0.08", "size": "50"}],
        asks=[
            {"price": "0.09", "size": "10"},
            {"price": "0.10", "size": "20"},
        ],
        timestamp_ms=1000,
    )
    return result


def test_broker_walks_depth_and_debits_ledger():
    ledger = Ledger(initial_cash="100")
    result = PaperBroker(ledger).buy(
        order_id="o1",
        market=identity(),
        side="YES",
        shares="15",
        book=book(),
        source="TEST",
    )
    assert result.status == "FILLED"
    assert result.fill is not None
    assert result.fill.gross_cost == Decimal("1.40")
    assert result.fill.average_price == Decimal("1.40") / Decimal("15")
    assert ledger.cash == Decimal("98.60")
    assert ledger.reserved_cash == 0


def test_full_fill_requirement_rejects_partial_depth():
    ledger = Ledger(initial_cash="100")
    result = PaperBroker(ledger).buy(
        order_id="o1",
        market=identity(),
        side="YES",
        shares="40",
        book=book(),
        source="TEST",
    )
    assert result.status == "INSUFFICIENT_LIQUIDITY"
    assert ledger.cash == Decimal("100")


def test_token_mismatch_is_rejected():
    ledger = Ledger(initial_cash="100")
    result = PaperBroker(ledger).buy(
        order_id="o1",
        market=identity(),
        side="YES",
        shares="5",
        book=book("no"),
        source="TEST",
    )
    assert result.status == "REJECTED"


def test_fee_is_included_in_total_cost():
    ledger = Ledger(initial_cash="100")
    result = PaperBroker(ledger).buy(
        order_id="o1",
        market=identity(fees=True),
        side="YES",
        shares="10",
        book=book(),
        source="TEST",
    )
    assert result.status == "FILLED"
    assert result.fill.fee > 0
    assert result.fill.total_cost == result.fill.gross_cost + result.fill.fee


def test_broker_rejects_order_below_market_minimum_notional():
    ledger = Ledger(initial_cash="100")
    result = PaperBroker(ledger).buy(
        order_id="o1",
        market=identity(minimum_order_size="5"),
        side="YES",
        shares="10",
        book=book(),
        source="TEST",
    )
    assert result.status == "BELOW_MINIMUM_ORDER"
    assert ledger.cash == Decimal("100")
