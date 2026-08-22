from decimal import Decimal

from accounting.ledger import Ledger
from adapters.polymarket.models import MarketResolvedEvent
from domain.orders import Fill
from resolution import ResolutionService


def test_resolution_event_is_idempotent_and_updates_cash():
    ledger = Ledger(initial_cash="100")
    ledger.record_fill(Fill(
        fill_id="f1", condition_id="0xabc", token_id="yes", side="YES",
        requested_shares=Decimal("10"), filled_shares=Decimal("10"),
        average_price=Decimal("0.4"), gross_cost=Decimal("4"),
        fee=Decimal("0"), total_cost=Decimal("4"), timestamp_ms=1,
        source="TEST",
    ))
    event = MarketResolvedEvent(
        gamma_market_id="1", condition_id="0xabc",
        token_ids=("yes", "no"), winning_token_id="yes",
        winning_outcome="YES", timestamp_ms=2,
    )
    service = ResolutionService(ledger)
    assert service.handle(event) is True
    assert service.handle(event) is False
    assert ledger.cash == Decimal("106")
    assert ledger.realized_pnl == Decimal("6")
