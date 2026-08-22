from decimal import Decimal

import pytest

from accounting.ledger import Ledger
from domain.orders import Fill


def fill(fill_id="f1", token="yes", side="YES", shares="10", price="0.4", fee="0"):
    d_shares = Decimal(shares)
    d_price = Decimal(price)
    d_fee = Decimal(fee)
    gross = d_shares * d_price
    return Fill(
        fill_id=fill_id,
        condition_id="0xabc",
        token_id=token,
        side=side,
        requested_shares=d_shares,
        filled_shares=d_shares,
        average_price=d_price,
        gross_cost=gross,
        fee=d_fee,
        total_cost=gross + d_fee,
        timestamp_ms=1,
        source="TEST",
    )


def test_fill_debits_cash_and_creates_position():
    ledger = Ledger(initial_cash="100")
    assert ledger.record_fill(fill()) is True
    assert ledger.cash == Decimal("96.0")
    positions = ledger.positions()
    assert len(positions) == 1
    assert positions[0].shares == Decimal("10")
    assert positions[0].cost_basis == Decimal("4.0")


def test_duplicate_fill_is_idempotent():
    ledger = Ledger(initial_cash="100")
    assert ledger.record_fill(fill()) is True
    assert ledger.record_fill(fill()) is False
    assert ledger.cash == Decimal("96.0")


def test_reservation_reduces_available_cash():
    ledger = Ledger(initial_cash="100")
    assert ledger.reserve("o1", Decimal("30")) is True
    assert ledger.cash == Decimal("100")
    assert ledger.available_cash == Decimal("70")
    assert ledger.reserve("o2", Decimal("80")) is False
    ledger.release("o1")
    assert ledger.available_cash == Decimal("100")


def test_resolution_settles_once_and_realizes_pnl():
    ledger = Ledger(initial_cash="100")
    ledger.record_fill(fill())
    assert ledger.settle(
        condition_id="0xabc",
        winning_token_id="yes",
        winning_outcome="YES",
        timestamp_ms=2,
        event_key="resolution-1",
    ) is True
    assert ledger.cash == Decimal("106.0")
    assert ledger.realized_pnl == Decimal("6.0")
    assert ledger.positions() == []
    assert ledger.settle(
        condition_id="0xabc",
        winning_token_id="yes",
        winning_outcome="YES",
        timestamp_ms=3,
        event_key="resolution-duplicate",
    ) is False
    assert ledger.cash == Decimal("106.0")


def test_open_equity_requires_marks():
    ledger = Ledger(initial_cash="100")
    ledger.record_fill(fill())
    with pytest.raises(ValueError):
        ledger.equity({})
    assert ledger.equity({"yes": Decimal("0.5")}) == Decimal("101.0")
