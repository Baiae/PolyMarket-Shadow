from decimal import Decimal

import pytest

from adapters.polymarket.models import BookEvent
from domain.market import MarketIdentity
from domain.orderbook import PriceLevel
from main import AgentOrchestrator


def identity():
    return MarketIdentity(
        gamma_market_id="1",
        condition_id="0xabc",
        yes_token_id="yes",
        no_token_id="no",
        question="Test?",
    )


def event(token, ask, bid, timestamp_ms=1):
    return BookEvent(
        condition_id="0xabc",
        token_id=token,
        bids=(PriceLevel(Decimal(bid), Decimal("20")),),
        asks=(PriceLevel(Decimal(ask), Decimal("10")),),
        timestamp_ms=timestamp_ms,
        book_hash=f"{token}-hash",
    )


@pytest.mark.asyncio
async def test_replayed_books_create_only_equal_share_paper_positions():
    orchestrator = AgentOrchestrator(
        ledger_path=":memory:", initial_cash="1000", max_book_age_ms=0
    )
    orchestrator.load_markets([identity()])

    await orchestrator.handle_event(event("yes", "0.45", "0.44"))
    assert orchestrator.ledger.positions() == []

    await orchestrator.handle_event(event("no", "0.45", "0.44"))
    positions = sorted(orchestrator.ledger.positions(), key=lambda p: p.side)
    assert len(positions) == 2
    assert positions[0].shares == positions[1].shares == Decimal("10")
    assert len(orchestrator.order_results) == 2
    assert {result.status for result in orchestrator.order_results} == {"FILLED"}


@pytest.mark.asyncio
async def test_stale_books_fail_closed_before_paper_execution():
    orchestrator = AgentOrchestrator(
        ledger_path=":memory:", initial_cash="1000", max_book_age_ms=100
    )
    orchestrator.load_markets([identity()])
    await orchestrator.handle_event(event("yes", "0.45", "0.44", timestamp_ms=1))
    await orchestrator.handle_event(event("no", "0.45", "0.44", timestamp_ms=1))
    assert orchestrator.ledger.positions() == []
    assert orchestrator.order_results == []
