import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from config import settings
from risk import RiskManager, PositionSize

log = logging.getLogger(__name__)


class OrderStatus(str, Enum):
    PAPER = "PAPER"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    RATE_LIMITED = "RATE_LIMITED"
    KILLED = "KILLED"


@dataclass
class Order:
    market_id: str
    question: str
    side: str
    size_usd: float
    price: float
    status: OrderStatus
    source: str
    confidence: float = 0.0
    timestamp: datetime = field(default_factory=datetime.utcnow)
    fill_price: float | None = None
    error: str = ""


class ExecutionEngine:
    """
    MVP: paper trading only.
    Post-MVP: uncomment CLOB client, set PAPER_TRADING=false in .env
    after >= 2 weeks of validated paper results.
    """

    def __init__(self, risk: RiskManager):
        self._risk = risk
        self.orders: list[Order] = []
        # ── CLOB client stub (activate post-MVP) ──────────────────────────────
        # from py_clob_client.client import ClobClient
        # self._clob = ClobClient(
        #     host=settings.polymarket_clob_url,
        #     key=settings.polymarket_api_key,
        #     chain_id=137,
        # )

    async def execute_arb(self, signal, meta) -> list[Order]:
        """Buy both YES and NO to lock in structural arb."""
        orders = []
        for side, price in [("YES", meta.yes_price), ("NO", meta.no_price)]:
            edge = (1.0 - (meta.yes_price + meta.no_price)) / 2
            sizing = self._risk.size_position(
                market_id=meta.market_id, side=side, edge=edge, price=price)
            order = await self._place(
                market_id=meta.market_id, question=meta.question,
                side=side, sizing=sizing, price=price,
                source="ARB", confidence=1.0)
            orders.append(order)
        return orders

    async def execute_signal(self, signal) -> Order:
        """Execute a swarm consensus directional signal."""
        side = signal.consensus.value
        price = signal.yes_price if side == "YES" else signal.no_price
        edge = signal.confidence - price
        sizing = self._risk.size_position(
            market_id=signal.market_id, side=side, edge=edge, price=price)
        return await self._place(
            market_id=signal.market_id, question=signal.question,
            side=side, sizing=sizing, price=price,
            source="SWARM", confidence=signal.confidence)

    async def _place(self, market_id, question, side, sizing,
                     price, source, confidence) -> Order:
        if self._risk.is_killed:
            return self._record(Order(
                market_id=market_id, question=question, side=side,
                size_usd=0, price=price, status=OrderStatus.KILLED,
                source=source, confidence=confidence,
                error=self._risk.kill_reason))
        if not self._risk.can_place_order():
            return self._record(Order(
                market_id=market_id, question=question, side=side,
                size_usd=0, price=price, status=OrderStatus.RATE_LIMITED,
                source=source, confidence=confidence))
        if sizing is None:
            return self._record(Order(
                market_id=market_id, question=question, side=side,
                size_usd=0, price=price, status=OrderStatus.REJECTED,
                source=source, confidence=confidence,
                error="No positive edge after Kelly sizing"))
        if settings.paper_trading:
            log.info(f"📋 PAPER {source} {side} ${sizing.recommended_usd:.2f}"
                     f" @ {price:.3f} | {question[:50]}")
            return self._record(Order(
                market_id=market_id, question=question, side=side,
                size_usd=sizing.recommended_usd, price=price,
                status=OrderStatus.PAPER, source=source,
                confidence=confidence, fill_price=price))
        raise RuntimeError("Live execution not enabled — keep PAPER_TRADING=true")

    def _record(self, order: Order) -> Order:
        self.orders.append(order)
        if len(self.orders) > 2000:
            self.orders = self.orders[-2000:]
        return order
