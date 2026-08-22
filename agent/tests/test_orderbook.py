import json
from decimal import Decimal
from pathlib import Path

import pytest

from domain.orderbook import OrderBook


FIXTURES = Path(__file__).parent / "fixtures" / "polymarket"


def fixture_book() -> tuple[OrderBook, dict]:
    event = json.loads((FIXTURES / "book.json").read_text())
    book = OrderBook(event["asset_id"])
    book.apply_snapshot(
        bids=event["bids"],
        asks=event["asks"],
        timestamp_ms=event["timestamp"],
        book_hash=event["hash"],
    )
    return book, event


def test_snapshot_builds_top_of_book():
    book, _ = fixture_book()
    assert book.best_bid == Decimal("0.08")
    assert book.best_ask == Decimal("0.09")
    assert book.spread == Decimal("0.01")


def test_quote_buy_walks_real_ask_depth():
    book, _ = fixture_book()
    quote = book.quote_buy("15")
    assert quote.complete is True
    assert quote.filled_shares == Decimal("15")
    assert quote.notional == Decimal("1.40")
    assert quote.average_price == Decimal("1.40") / Decimal("15")


def test_quote_reports_partial_fill():
    book, _ = fixture_book()
    quote = book.quote_buy("40")
    assert quote.complete is False
    assert quote.filled_shares == Decimal("30")
    assert quote.unfilled_shares == Decimal("10")


def test_zero_size_change_removes_level():
    book, _ = fixture_book()
    book.apply_change(side="SELL", price="0.09", size="0")
    assert book.best_ask == Decimal("0.10")


def test_change_updates_book_and_timestamp():
    book, _ = fixture_book()
    book.apply_change(
        side="BUY", price="0.085", size="12", timestamp_ms="1782753358000"
    )
    assert book.best_bid == Decimal("0.085")
    assert book.timestamp_ms == 1782753358000


def test_rejects_negative_size():
    book = OrderBook("token")
    with pytest.raises(ValueError):
        book.apply_change(side="BUY", price="0.5", size="-1")
