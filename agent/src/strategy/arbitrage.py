"""Executable structural arbitrage for binary Polymarket books."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from domain.market import MarketIdentity
from domain.orderbook import OrderBook
from execution_fees import taker_fee


ZERO = Decimal(0)


@dataclass(frozen=True, slots=True)
class ArbOpportunity:
    condition_id: str
    question: str
    matched_shares: Decimal
    yes_cost: Decimal
    no_cost: Decimal
    total_fees: Decimal
    slippage_reserve: Decimal
    total_cost: Decimal
    locked_payout: Decimal
    net_profit: Decimal
    roi: Decimal
    yes_book_timestamp_ms: int
    no_book_timestamp_ms: int


class ExecutableArbitrageDetector:
    """Find fee- and depth-aware equal-share binary arbitrage."""

    def __init__(
        self,
        *,
        minimum_net_profit: Decimal | str = "0.01",
        slippage_reserve_per_share: Decimal | str = "0",
    ):
        self.minimum_net_profit = Decimal(str(minimum_net_profit))
        self.slippage_reserve_per_share = Decimal(
            str(slippage_reserve_per_share)
        )
        self.signals: list[ArbOpportunity] = []

    @staticmethod
    def _cumulative_depth(book: OrderBook) -> list[Decimal]:
        total = ZERO
        result: list[Decimal] = []
        for price in sorted(book.asks):
            total += book.asks[price]
            result.append(total)
        return result

    def evaluate(
        self,
        market: MarketIdentity,
        yes_book: OrderBook,
        no_book: OrderBook,
        *,
        max_shares: Decimal | str | None = None,
    ) -> ArbOpportunity | None:
        if (
            yes_book.token_id != market.yes_token_id
            or no_book.token_id != market.no_token_id
        ):
            raise ValueError(
                "order books do not match market YES/NO token identities"
            )
        if yes_book.timestamp_ms is None or no_book.timestamp_ms is None:
            return None

        yes_depth = sum(yes_book.asks.values(), ZERO)
        no_depth = sum(no_book.asks.values(), ZERO)
        depth_cap = min(yes_depth, no_depth)
        if max_shares is not None:
            depth_cap = min(depth_cap, Decimal(str(max_shares)))
        if depth_cap <= ZERO:
            return None

        candidates = {depth_cap}
        for value in self._cumulative_depth(yes_book) + self._cumulative_depth(
            no_book
        ):
            if ZERO < value <= depth_cap:
                candidates.add(value)

        best: ArbOpportunity | None = None
        for shares in sorted(candidates):
            yes_quote = yes_book.quote_buy(shares)
            no_quote = no_book.quote_buy(shares)
            if not yes_quote.complete or not no_quote.complete:
                continue
            yes_fee = sum(
                (
                    taker_fee(level.shares, level.price, market)
                    for level in yes_quote.levels
                ),
                ZERO,
            )
            no_fee = sum(
                (
                    taker_fee(level.shares, level.price, market)
                    for level in no_quote.levels
                ),
                ZERO,
            )
            fees = yes_fee + no_fee
            reserve = self.slippage_reserve_per_share * shares
            total_cost = yes_quote.notional + no_quote.notional + fees + reserve
            payout = shares
            net = payout - total_cost
            if net < self.minimum_net_profit:
                continue
            roi = net / total_cost if total_cost > ZERO else ZERO
            opportunity = ArbOpportunity(
                condition_id=market.condition_id,
                question=market.question,
                matched_shares=shares,
                yes_cost=yes_quote.notional,
                no_cost=no_quote.notional,
                total_fees=fees,
                slippage_reserve=reserve,
                total_cost=total_cost,
                locked_payout=payout,
                net_profit=net,
                roi=roi,
                yes_book_timestamp_ms=yes_book.timestamp_ms,
                no_book_timestamp_ms=no_book.timestamp_ms,
            )
            if best is None or opportunity.net_profit > best.net_profit:
                best = opportunity

        if best is not None:
            self.signals.append(best)
            if len(self.signals) > 500:
                self.signals = self.signals[-500:]
        return best


ArbitrageDetector = ExecutableArbitrageDetector
