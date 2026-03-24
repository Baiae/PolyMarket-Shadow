import asyncio
import json
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Deque

import aiohttp
import websockets

from config import settings

log = logging.getLogger(__name__)


@dataclass
class Trade:
    market_id: str
    outcome: str
    amount_usd: float
    price: float
    timestamp: datetime
    category: str = ""
    question: str = ""


@dataclass
class MarketMeta:
    market_id: str
    question: str
    category: str
    yes_price: float
    no_price: float
    end_date: str


class DataCollector:
    def __init__(self, on_queue_full: Callable[[list[str]], None]):
        self._on_queue_full = on_queue_full
        self._market_queue: Deque[str] = deque(maxlen=100)
        self._meta_cache: dict[str, MarketMeta] = {}
        self._running = False
        self.recent_trades: list[Trade] = []

    async def start(self) -> None:
        self._running = True
        async with asyncio.TaskGroup() as tg:
            tg.create_task(self._stream_trades())
            tg.create_task(self._refresh_metadata_loop())

    def stop(self) -> None:
        self._running = False

    async def _stream_trades(self) -> None:
        backoff = 1
        while self._running:
            try:
                async with websockets.connect(
                    settings.polymarket_ws_url, ping_interval=30, ping_timeout=10,
                ) as ws:
                    log.info("WebSocket connected")
                    backoff = 1
                    await ws.send(json.dumps({"type": "subscribe", "channel": "market"}))
                    async for raw in ws:
                        if not self._running:
                            break
                        await self._on_message(raw)
            except (websockets.WebSocketException, OSError) as exc:
                log.warning(f"WebSocket error: {exc}. Retrying in {backoff}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _on_message(self, raw: str) -> None:
        try:
            events = json.loads(raw)
            if not isinstance(events, list):
                events = [events]
            for event in events:
                if event.get("type") == "trade":
                    await self._process_trade(event)
        except json.JSONDecodeError:
            pass

    async def _process_trade(self, event: dict) -> None:
        try:
            amount = float(event.get("size", 0)) * float(event.get("price", 0))
            market_id = event.get("asset_id", "")
            if amount < settings.whale_threshold_usd:
                return
            meta = self._meta_cache.get(market_id)
            category = meta.category if meta else ""
            if category.lower() in settings.excluded_categories:
                return
            trade = Trade(
                market_id=market_id, outcome=event.get("outcome", ""),
                amount_usd=amount, price=float(event.get("price", 0)),
                timestamp=datetime.utcnow(), category=category,
                question=meta.question if meta else "",
            )
            self.recent_trades.append(trade)
            if len(self.recent_trades) > 200:
                self.recent_trades = self.recent_trades[-200:]
            log.info(f"🐋 Whale: ${amount:,.0f} on {trade.question[:50] or market_id}")
            if market_id not in self._market_queue:
                self._market_queue.append(market_id)
            if len(self._market_queue) >= settings.market_queue_trigger:
                batch = list(self._market_queue)
                self._market_queue.clear()
                self._on_queue_full(batch)
        except (KeyError, ValueError, TypeError) as exc:
            log.debug(f"Trade parse error: {exc}")

    async def _refresh_metadata_loop(self) -> None:
        while self._running:
            await self._fetch_active_markets()
            await asyncio.sleep(300)

    async def _fetch_active_markets(self) -> None:
        url = f"{settings.polymarket_gamma_url}/markets"
        params = {"active": "true", "closed": "false", "limit": 500}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params,
                        timeout=aiohttp.ClientTimeout(total=15)) as resp:
                    if resp.status != 200:
                        return
                    data = await resp.json()
                    markets = data if isinstance(data, list) else data.get("markets", [])
                    for m in markets:
                        mid = m.get("conditionId") or m.get("id", "")
                        if not mid:
                            continue
                        tokens = m.get("tokens", [])
                        yes_price = next(
                            (float(t.get("price", 0)) for t in tokens
                             if t.get("outcome") == "Yes"), 0.5)
                        no_price = next(
                            (float(t.get("price", 0)) for t in tokens
                             if t.get("outcome") == "No"), 0.5)
                        self._meta_cache[mid] = MarketMeta(
                            market_id=mid, question=m.get("question", ""),
                            category=m.get("category", ""),
                            yes_price=yes_price, no_price=no_price,
                            end_date=m.get("endDate", ""),
                        )
                    log.info(f"Gamma cache: {len(self._meta_cache)} markets")
        except Exception as exc:
            log.error(f"Gamma API error: {exc}")

    def get_meta(self, market_id: str) -> MarketMeta | None:
        return self._meta_cache.get(market_id)

    def all_meta(self) -> list[MarketMeta]:
        return list(self._meta_cache.values())
