"""Raw public Polymarket market-stream adapter."""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

import websockets

from config import settings
from .models import NormalizedMarketEvent, normalize_market_event

log = logging.getLogger(__name__)

EventHandler = Callable[[NormalizedMarketEvent], Awaitable[None] | None]


class PolymarketStream:
    def __init__(
        self,
        token_ids: Iterable[str],
        on_event: EventHandler,
        *,
        url: str | None = None,
    ):
        self.token_ids = tuple(dict.fromkeys(str(token) for token in token_ids if token))
        if not self.token_ids:
            raise ValueError("at least one CLOB token ID is required")
        self.on_event = on_event
        self.url = url or settings.polymarket_ws_url
        self._running = False

    @staticmethod
    def subscription_payload(token_ids: Iterable[str]) -> dict[str, Any]:
        tokens = list(dict.fromkeys(str(token) for token in token_ids if token))
        if not tokens:
            raise ValueError("at least one CLOB token ID is required")
        return {
            "assets_ids": tokens,
            "type": "market",
            "custom_feature_enabled": True,
        }

    async def start(self) -> None:
        self._running = True
        backoff = 1
        while self._running:
            try:
                async with websockets.connect(
                    self.url,
                    ping_interval=30,
                    ping_timeout=10,
                ) as websocket:
                    await websocket.send(json.dumps(
                        self.subscription_payload(self.token_ids)
                    ))
                    log.info("Polymarket stream subscribed to %d tokens", len(self.token_ids))
                    backoff = 1
                    async for raw_message in websocket:
                        if not self._running:
                            break
                        await self.process_message(raw_message)
            except asyncio.CancelledError:
                raise
            except (OSError, websockets.WebSocketException) as exc:
                if not self._running:
                    break
                log.warning("Polymarket stream error: %s; retrying in %ss", exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    def stop(self) -> None:
        self._running = False

    async def process_message(self, raw_message: str | bytes) -> None:
        try:
            decoded = json.loads(raw_message)
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError):
            log.debug("Ignoring malformed market-stream frame")
            return

        events = decoded if isinstance(decoded, list) else [decoded]
        for raw in events:
            if not isinstance(raw, dict):
                continue
            normalized = normalize_market_event(raw)
            if normalized is None:
                continue
            result = self.on_event(normalized)
            if inspect.isawaitable(result):
                await result
