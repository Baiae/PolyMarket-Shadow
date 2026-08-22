"""Polymarket taker-fee math for paper execution."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from domain.market import MarketIdentity

FEE_QUANTUM = Decimal("0.00001")
ZERO = Decimal(0)
ONE = Decimal(1)


def taker_fee(shares: Decimal, price: Decimal, market: MarketIdentity) -> Decimal:
    """Return USDC fee for a taker fill."""
    if not market.fees_enabled or market.fee_rate <= ZERO:
        return ZERO
    if shares <= ZERO:
        return ZERO
    if price < ZERO or price > ONE:
        raise ValueError("price must be within [0,1]")
    price_component = price * (ONE - price)
    fee = shares * market.fee_rate * (price_component**market.fee_exponent)
    rounded = fee.quantize(FEE_QUANTUM, rounding=ROUND_HALF_UP)
    return rounded if rounded >= FEE_QUANTUM else ZERO
