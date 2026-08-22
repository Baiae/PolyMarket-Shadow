"""Depth-aware paper broker. No live-order capability exists here."""

from __future__ import annotations

from decimal import Decimal

from accounting.ledger import Ledger
from domain.market import MarketIdentity
from domain.orderbook import OrderBook, as_decimal
from domain.orders import Fill, PaperOrderResult
from execution_fees import taker_fee

ZERO = Decimal(0)


class PaperBroker:
    def __init__(self, ledger: Ledger):
        self.ledger = ledger

    @staticmethod
    def _build_fill(
        *,
        fill_id: str,
        market: MarketIdentity,
        side: str,
        requested: Decimal,
        book: OrderBook,
        source: str,
    ) -> Fill | None:
        quote = book.quote_buy(requested)
        if not quote.complete or quote.average_price is None:
            return None
        fee = sum(
            (taker_fee(level.shares, level.price, market) for level in quote.levels),
            ZERO,
        )
        return Fill(
            fill_id=fill_id,
            condition_id=market.condition_id,
            token_id=market.token_for_side(side),
            side=side,
            requested_shares=requested,
            filled_shares=quote.filled_shares,
            average_price=quote.average_price,
            gross_cost=quote.notional,
            fee=fee,
            total_cost=quote.notional + fee,
            timestamp_ms=book.timestamp_ms,
            source=source,
        )

    @staticmethod
    def _meets_minimum_order(market: MarketIdentity, fill: Fill) -> bool:
        minimum = market.minimum_order_size
        return minimum is None or fill.gross_cost >= minimum

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
                order_id,
                "REJECTED",
                requested,
                ZERO,
                reason="order book token mismatch",
            )
        if book.timestamp_ms is None:
            return PaperOrderResult(
                order_id,
                "REJECTED",
                requested,
                ZERO,
                reason="book has no freshness timestamp",
            )
        quote = book.quote_buy(requested)
        if quote.filled_shares <= ZERO:
            return PaperOrderResult(
                order_id,
                "NO_LIQUIDITY",
                requested,
                ZERO,
                reason="no executable asks",
            )
        if require_full_fill and not quote.complete:
            return PaperOrderResult(
                order_id,
                "INSUFFICIENT_LIQUIDITY",
                requested,
                ZERO,
                reason=f"only {quote.filled_shares} shares available",
            )
        actual_requested = requested if require_full_fill else quote.filled_shares
        fill = self._build_fill(
            fill_id=order_id,
            market=market,
            side=normalized_side,
            requested=actual_requested,
            book=book,
            source=source,
        )
        if fill is None:
            return PaperOrderResult(
                order_id,
                "INSUFFICIENT_LIQUIDITY",
                requested,
                ZERO,
            )
        if not self._meets_minimum_order(market, fill):
            return PaperOrderResult(
                order_id,
                "BELOW_MINIMUM_ORDER",
                requested,
                ZERO,
                reason=(
                    f"gross cost {fill.gross_cost} is below market minimum "
                    f"{market.minimum_order_size}"
                ),
            )
        if not self.ledger.reserve(order_id, fill.total_cost):
            return PaperOrderResult(
                order_id,
                "INSUFFICIENT_CASH",
                requested,
                ZERO,
                reason="paper cash below executable cost",
            )
        try:
            if not self.ledger.record_fill(fill):
                return PaperOrderResult(order_id, "DUPLICATE", requested, ZERO)
            return PaperOrderResult(
                order_id,
                "FILLED",
                requested,
                fill.filled_shares,
                fill=fill,
            )
        finally:
            self.ledger.release(order_id)

    def buy_binary_pair(
        self,
        *,
        order_id: str,
        market: MarketIdentity,
        shares: Decimal | str,
        yes_book: OrderBook,
        no_book: OrderBook,
        source: str = "ARB",
    ) -> tuple[PaperOrderResult, PaperOrderResult]:
        """Atomically paper-buy equal YES and NO share counts."""
        requested = as_decimal(shares)
        if (
            yes_book.token_id != market.yes_token_id
            or no_book.token_id != market.no_token_id
        ):
            rejected = PaperOrderResult(
                order_id,
                "REJECTED",
                requested,
                ZERO,
                reason="pair book token mismatch",
            )
            return rejected, rejected
        if yes_book.timestamp_ms is None or no_book.timestamp_ms is None:
            rejected = PaperOrderResult(
                order_id,
                "REJECTED",
                requested,
                ZERO,
                reason="pair book missing timestamp",
            )
            return rejected, rejected

        yes_fill = self._build_fill(
            fill_id=f"{order_id}:YES",
            market=market,
            side="YES",
            requested=requested,
            book=yes_book,
            source=source,
        )
        no_fill = self._build_fill(
            fill_id=f"{order_id}:NO",
            market=market,
            side="NO",
            requested=requested,
            book=no_book,
            source=source,
        )
        if yes_fill is None or no_fill is None:
            rejected = PaperOrderResult(
                order_id,
                "INSUFFICIENT_LIQUIDITY",
                requested,
                ZERO,
            )
            return rejected, rejected
        if not self._meets_minimum_order(market, yes_fill) or not self._meets_minimum_order(
            market, no_fill
        ):
            rejected = PaperOrderResult(
                order_id,
                "BELOW_MINIMUM_ORDER",
                requested,
                ZERO,
                reason="one or both arb legs are below the market minimum order size",
            )
            return rejected, rejected

        total_cost = yes_fill.total_cost + no_fill.total_cost
        if not self.ledger.reserve(order_id, total_cost):
            rejected = PaperOrderResult(
                order_id,
                "INSUFFICIENT_CASH",
                requested,
                ZERO,
            )
            return rejected, rejected
        try:
            if not self.ledger.record_fills_atomic([yes_fill, no_fill]):
                duplicate = PaperOrderResult(
                    order_id,
                    "DUPLICATE",
                    requested,
                    ZERO,
                )
                return duplicate, duplicate
            return (
                PaperOrderResult(
                    order_id,
                    "FILLED",
                    requested,
                    requested,
                    fill=yes_fill,
                ),
                PaperOrderResult(
                    order_id,
                    "FILLED",
                    requested,
                    requested,
                    fill=no_fill,
                ),
            )
        finally:
            self.ledger.release(order_id)
