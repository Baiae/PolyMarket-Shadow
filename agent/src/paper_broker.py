"""Depth-aware paper broker. No live-order capability exists here."""

from __future__ import annotations

from decimal import Decimal

from accounting.ledger import Ledger
from domain.market import MarketIdentity
from domain.orderbook import OrderBook, as_decimal
from domain.orders import Fill, PaperOrderResult
from execution_fees import taker_fee


class PaperBroker:
    def __init__(self, ledger: Ledger):
        self.ledger = ledger

    def buy(
        self,
        *,
        order_id: str,
        market: MarketIdentity,
        side: str,
        shares: Decimal | str,
        book: OrderBook,
        source: str,
        require_full_fill: bool = True,
    ) -> PaperOrderResult:
        requested = as_decimal(shares)
        normalized_side = side.strip().upper()
        expected_token = market.token_for_side(normalized_side)
        if book.token_id != expected_token:
            return PaperOrderResult(
                order_id, "REJECTED", requested, Decimal("0"),
                reason="order book token does not match requested market side",
            )
        if book.timestamp_ms is None:
            return PaperOrderResult(
                order_id, "REJECTED", requested, Decimal("0"),
                reason="order book has no freshness timestamp",
            )

        quote = book.quote_buy(requested)
        if quote.filled_shares <= 0:
            return PaperOrderResult(
                order_id, "NO_LIQUIDITY", requested, Decimal("0"),
                reason="no executable asks",
            )
        if require_full_fill and not quote.complete:
            return PaperOrderResult(
                order_id, "INSUFFICIENT_LIQUIDITY", requested, Decimal("0"),
                reason=f"only {quote.filled_shares} of {requested} shares available",
            )

        fee = sum(
            (taker_fee(level.shares, level.price, market) for level in quote.levels),
            Decimal("0"),
        )
        total_cost = quote.notional + fee
        if not self.ledger.reserve(order_id, total_cost):
            return PaperOrderResult(
                order_id, "INSUFFICIENT_CASH", requested, Decimal("0"),
                reason="available paper cash is below executable cost",
            )

        try:
            fill = Fill(
                fill_id=order_id,
                condition_id=market.condition_id,
                token_id=expected_token,
                side=normalized_side,
                requested_shares=requested,
                filled_shares=quote.filled_shares,
                average_price=quote.average_price or Decimal("0"),
                gross_cost=quote.notional,
                fee=fee,
                total_cost=total_cost,
                timestamp_ms=book.timestamp_ms,
                source=source,
            )
            if not self.ledger.record_fill(fill):
                return PaperOrderResult(
                    order_id, "DUPLICATE", requested, Decimal("0"),
                    reason="fill id already exists in ledger",
                )
            return PaperOrderResult(
                order_id=order_id,
                status="FILLED",
                requested_shares=requested,
                filled_shares=quote.filled_shares,
                fill=fill,
            )
        finally:
            self.ledger.release(order_id)
