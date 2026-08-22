"""Poly-Shadow v0.2 truthful paper core orchestrator."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import sys
import time
from decimal import Decimal
from pathlib import Path

import uvicorn

from accounting.ledger import Ledger
from adapters.polymarket.gamma import GammaAdapter
from adapters.polymarket.models import (
    BestBidAskEvent,
    BookEvent,
    LastTradeEvent,
    MarketResolvedEvent,
    PriceChangeEvent,
)
from adapters.polymarket.stream import PolymarketStream
from config import settings
from domain.market import MarketIdentity
from domain.orderbook import OrderBook
from paper_broker import PaperBroker
from resolution import ResolutionService
from risk import RiskManager
from strategy.arbitrage import ExecutableArbitrageDetector


Path(settings.log_dir).mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(Path(settings.log_dir) / "agent.log"),
    ],
)
log = logging.getLogger("main")


class AgentOrchestrator:
    def __init__(
        self,
        *,
        ledger_path: str | None = None,
        initial_cash: Decimal | str | None = None,
        max_book_age_ms: int | None = None,
    ):
        if not settings.paper_trading:
            raise RuntimeError(
                "Poly-Shadow v0.2 has no live-capital execution mode; PAPER_TRADING must remain true"
            )
        self.running = False
        self.last_error = ""
        self.last_event_received_ms: int | None = None
        self.max_book_age_ms = (
            settings.market_max_book_age_ms
            if max_book_age_ms is None
            else max_book_age_ms
        )
        self.gamma = GammaAdapter()
        self.ledger = Ledger(
            ledger_path or settings.database_path,
            initial_cash=(
                str(settings.initial_bankroll) if initial_cash is None else initial_cash
            ),
        )
        self.risk = RiskManager(
            self.ledger,
            max_drawdown_pct=settings.max_drawdown_pct,
            max_position_pct=settings.max_position_pct,
        )
        self.broker = PaperBroker(self.ledger)
        self.arbitrage = ExecutableArbitrageDetector(
            minimum_net_profit=settings.arb_min_net_profit,
            slippage_reserve_per_share=settings.arb_slippage_reserve_per_share,
        )
        self.resolution = ResolutionService(self.ledger)
        self.stream: PolymarketStream | None = None

        self.markets_by_condition: dict[str, MarketIdentity] = {}
        self.token_to_condition: dict[str, str] = {}
        self.books: dict[str, OrderBook] = {}
        self.last_trade_prices: dict[str, Decimal] = {}
        self.recent_trades: list[LastTradeEvent] = []
        self.order_results: list = []

    def load_markets(self, markets: list[MarketIdentity]) -> None:
        for market in markets:
            self.markets_by_condition[market.condition_id] = market
            for token_id in market.token_ids:
                self.token_to_condition[token_id] = market.condition_id
                self.books.setdefault(token_id, OrderBook(token_id))

    async def run(self) -> None:
        self.running = True
        self.last_error = ""
        try:
            markets = await self.gamma.fetch_active_markets(
                limit=settings.market_discovery_limit
            )
            self.load_markets(markets)
            if not self.markets_by_condition:
                raise RuntimeError("Gamma discovery returned no complete binary markets")
            token_ids = list(self.token_to_condition)
            self.stream = PolymarketStream(token_ids, self.handle_event)
            log.info(
                "Poly-Shadow v0.2 paper core: %d markets / %d tokens",
                len(self.markets_by_condition),
                len(token_ids),
            )
            await self.stream.start()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self.last_error = str(exc)
            log.exception("Agent stopped after runtime error")
            raise
        finally:
            self.running = False

    def stop(self) -> None:
        self.running = False
        if self.stream is not None:
            self.stream.stop()

    async def handle_event(self, event) -> None:
        self.last_event_received_ms = int(time.time() * 1000)
        affected_conditions: set[str] = set()

        if isinstance(event, BookEvent):
            book = self.books.get(event.token_id)
            if book is None:
                return
            book.apply_snapshot(
                bids=[{"price": str(x.price), "size": str(x.size)} for x in event.bids],
                asks=[{"price": str(x.price), "size": str(x.size)} for x in event.asks],
                timestamp_ms=event.timestamp_ms,
                book_hash=event.book_hash,
            )
            affected_conditions.add(event.condition_id)

        elif isinstance(event, PriceChangeEvent):
            for change in event.changes:
                book = self.books.get(change.token_id)
                if book is None:
                    continue
                book.apply_change(
                    side=change.side,
                    price=change.price,
                    size=change.size,
                    timestamp_ms=event.timestamp_ms,
                    book_hash=change.book_hash,
                )
                condition = self.token_to_condition.get(change.token_id)
                if condition:
                    affected_conditions.add(condition)

        elif isinstance(event, LastTradeEvent):
            self.last_trade_prices[event.token_id] = event.price
            self.recent_trades.append(event)
            if len(self.recent_trades) > 500:
                self.recent_trades = self.recent_trades[-500:]

        elif isinstance(event, BestBidAskEvent):
            # Top-of-book events are retained for feed health/marking context;
            # executable depth continues to come only from book state.
            condition = self.token_to_condition.get(event.token_id)
            if condition:
                affected_conditions.add(condition)

        elif isinstance(event, MarketResolvedEvent):
            self.resolution.handle(event)
            self._evaluate_risk_if_marked()
            return

        for condition_id in affected_conditions:
            self._consider_arbitrage(condition_id)

    def _books_fresh(self, *books: OrderBook) -> bool:
        if self.max_book_age_ms <= 0:
            return all(book.timestamp_ms is not None for book in books)
        now_ms = int(time.time() * 1000)
        return all(
            book.timestamp_ms is not None
            and 0 <= now_ms - book.timestamp_ms <= self.max_book_age_ms
            for book in books
        )

    def mark_prices(self) -> dict[str, Decimal]:
        marks: dict[str, Decimal] = {}
        for token_id, book in self.books.items():
            if book.best_bid is not None and book.best_ask is not None:
                marks[token_id] = (book.best_bid + book.best_ask) / Decimal("2")
            elif token_id in self.last_trade_prices:
                marks[token_id] = self.last_trade_prices[token_id]
        return marks

    def _evaluate_risk_if_marked(self) -> None:
        try:
            self.risk.evaluate(self.mark_prices())
        except ValueError:
            # Missing marks never authorize risk-taking; they simply prevent a
            # fresh equity calculation until complete book state is available.
            return

    def _consider_arbitrage(self, condition_id: str) -> None:
        if self.risk.is_killed:
            return
        market = self.markets_by_condition.get(condition_id)
        if market is None:
            return
        yes_book = self.books.get(market.yes_token_id)
        no_book = self.books.get(market.no_token_id)
        if yes_book is None or no_book is None or not self._books_fresh(yes_book, no_book):
            return
        opportunity = self.arbitrage.evaluate(
            market,
            yes_book,
            no_book,
            max_shares=settings.arb_max_shares,
        )
        if opportunity is None:
            return
        marks = self.mark_prices()
        try:
            if not self.risk.can_allocate(opportunity.total_cost, marks):
                return
        except ValueError:
            return
        if not self.risk.can_place_order():
            return

        fingerprint = (
            f"{condition_id}:{yes_book.hash}:{no_book.hash}:"
            f"{yes_book.timestamp_ms}:{no_book.timestamp_ms}:"
            f"{opportunity.matched_shares}:{opportunity.total_cost}"
        )
        order_id = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:24]
        results = self.broker.buy_binary_pair(
            order_id=order_id,
            market=market,
            shares=opportunity.matched_shares,
            yes_book=yes_book,
            no_book=no_book,
            source="ARB",
        )
        self.order_results.extend(results)
        if len(self.order_results) > 2000:
            self.order_results = self.order_results[-2000:]
        self._evaluate_risk_if_marked()

    @property
    def feed_healthy(self) -> bool:
        if self.last_event_received_ms is None:
            return False
        threshold = max(self.max_book_age_ms * 2, 60_000)
        return int(time.time() * 1000) - self.last_event_received_ms <= threshold


from api.server import create_app

orchestrator = AgentOrchestrator()
api_app = create_app(orchestrator)


if __name__ == "__main__":
    uvicorn.run(
        "main:api_app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        log_level="info",
    )
