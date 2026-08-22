"""Decimal order-book state and executable ask-depth quoting."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

ZERO = Decimal(0)


def as_decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"invalid decimal value: {value!r}") from exc


@dataclass(frozen=True, slots=True)
class PriceLevel:
    price: Decimal
    size: Decimal

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> PriceLevel:
        price = as_decimal(value.get("price"))
        size = as_decimal(value.get("size"))
        if price < ZERO or price > Decimal(1):
            raise ValueError(f"prediction-market price outside [0,1]: {price}")
        if size < ZERO:
            raise ValueError(f"negative order-book size: {size}")
        return cls(price=price, size=size)


@dataclass(frozen=True, slots=True)
class ExecutionLevel:
    price: Decimal
    shares: Decimal


@dataclass(frozen=True, slots=True)
class FillQuote:
    requested_shares: Decimal
    filled_shares: Decimal
    notional: Decimal
    average_price: Decimal | None
    levels: tuple[ExecutionLevel, ...] = ()

    @property
    def complete(self) -> bool:
        return self.filled_shares >= self.requested_shares

    @property
    def unfilled_shares(self) -> Decimal:
        return max(self.requested_shares - self.filled_shares, ZERO)


class OrderBook:
    """Mutable local order book for exactly one CLOB token."""

    def __init__(self, token_id: str):
        if not token_id:
            raise ValueError("token_id is required")
        self.token_id = token_id
        self.bids: dict[Decimal, Decimal] = {}
        self.asks: dict[Decimal, Decimal] = {}
        self.timestamp_ms: int | None = None
        self.hash: str | None = None

    @property
    def best_bid(self) -> Decimal | None:
        return max(self.bids) if self.bids else None

    @property
    def best_ask(self) -> Decimal | None:
        return min(self.asks) if self.asks else None

    @property
    def spread(self) -> Decimal | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid

    def apply_snapshot(
        self,
        *,
        bids: Iterable[Mapping[str, Any]],
        asks: Iterable[Mapping[str, Any]],
        timestamp_ms: int | str | None = None,
        book_hash: str | None = None,
    ) -> None:
        self.bids = self._levels(bids)
        self.asks = self._levels(asks)
        self.timestamp_ms = (
            int(timestamp_ms) if timestamp_ms not in (None, "") else None
        )
        self.hash = book_hash

    def apply_change(
        self,
        *,
        side: str,
        price: Any,
        size: Any,
        timestamp_ms: int | str | None = None,
        book_hash: str | None = None,
    ) -> None:
        normalized = side.strip().upper()
        target = (
            self.bids
            if normalized == "BUY"
            else self.asks
            if normalized == "SELL"
            else None
        )
        if target is None:
            raise ValueError(f"unknown order side: {side!r}")
        parsed_price = as_decimal(price)
        parsed_size = as_decimal(size)
        if parsed_price < ZERO or parsed_price > Decimal(1):
            raise ValueError(
                f"prediction-market price outside [0,1]: {parsed_price}"
            )
        if parsed_size < ZERO:
            raise ValueError(f"negative order-book size: {parsed_size}")
        if parsed_size == ZERO:
            target.pop(parsed_price, None)
        else:
            target[parsed_price] = parsed_size
        if timestamp_ms not in (None, ""):
            self.timestamp_ms = int(timestamp_ms)
        if book_hash is not None:
            self.hash = book_hash

    def quote_buy(self, shares: Any) -> FillQuote:
        requested = as_decimal(shares)
        if requested <= ZERO:
            raise ValueError("requested shares must be positive")
        remaining = requested
        filled = ZERO
        notional = ZERO
        levels: list[ExecutionLevel] = []
        for price in sorted(self.asks):
            available = self.asks[price]
            if available <= ZERO:
                continue
            take = min(remaining, available)
            levels.append(ExecutionLevel(price=price, shares=take))
            filled += take
            notional += take * price
            remaining -= take
            if remaining <= ZERO:
                break
        average = notional / filled if filled > ZERO else None
        return FillQuote(requested, filled, notional, average, tuple(levels))

    @staticmethod
    def _levels(
        values: Iterable[Mapping[str, Any]],
    ) -> dict[Decimal, Decimal]:
        result: dict[Decimal, Decimal] = {}
        for value in values:
            level = PriceLevel.from_mapping(value)
            if level.size > ZERO:
                result[level.price] = level.size
        return result
