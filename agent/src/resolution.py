"""Idempotent stream-driven market settlement."""

from __future__ import annotations

import hashlib

from accounting.ledger import Ledger
from adapters.polymarket.models import MarketResolvedEvent


class ResolutionService:
    def __init__(self, ledger: Ledger):
        self.ledger = ledger

    def handle(self, event: MarketResolvedEvent) -> bool:
        raw_key = (
            f"{event.gamma_market_id}:{event.condition_id}:"
            f"{event.winning_token_id}:{event.timestamp_ms or ''}"
        )
        event_key = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
        return self.ledger.settle(
            condition_id=event.condition_id,
            winning_token_id=event.winning_token_id,
            winning_outcome=event.winning_outcome,
            timestamp_ms=event.timestamp_ms,
            event_key=event_key,
        )
