"""Paper-order and fill records."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class Fill:
    fill_id: str
    condition_id: str
    token_id: str
    side: str
    requested_shares: Decimal
    filled_shares: Decimal
    average_price: Decimal
    gross_cost: Decimal
    fee: Decimal
    total_cost: Decimal
    timestamp_ms: int | None
    source: str


@dataclass(frozen=True, slots=True)
class Position:
    condition_id: str
    token_id: str
    side: str
    shares: Decimal
    cost_basis: Decimal

    @property
    def average_cost(self) -> Decimal:
        return self.cost_basis / self.shares if self.shares else Decimal(0)


@dataclass(frozen=True, slots=True)
class PaperOrderResult:
    order_id: str
    status: str
    requested_shares: Decimal
    filled_shares: Decimal
    fill: Fill | None = None
    reason: str = ""
