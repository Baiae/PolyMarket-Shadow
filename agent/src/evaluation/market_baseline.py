"""Capture a timestamped market-implied probability baseline."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from domain.market import MarketIdentity
from domain.orderbook import OrderBook
from forecasting.forecast import MarketBaseline


def baseline_from_yes_book(
    market: MarketIdentity,
    yes_book: OrderBook,
) -> MarketBaseline:
    """Use the two-sided YES midpoint as a reference baseline, never as a fill price."""
    if yes_book.token_id != market.yes_token_id:
        raise ValueError("YES book token does not match market identity")
    if yes_book.best_bid is None or yes_book.best_ask is None:
        raise ValueError("two-sided YES book is required for market baseline")
    if yes_book.timestamp_ms is None:
        raise ValueError("timestamped YES book is required for market baseline")
    midpoint = (yes_book.best_bid + yes_book.best_ask) / Decimal(2)
    captured_at = datetime.fromtimestamp(yes_book.timestamp_ms / 1000, tz=UTC)
    return MarketBaseline(
        condition_id=market.condition_id,
        probability_yes=midpoint,
        captured_at=captured_at,
        source="yes_orderbook_midpoint",
        best_bid=yes_book.best_bid,
        best_ask=yes_book.best_ask,
    )
