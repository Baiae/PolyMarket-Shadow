"""Gamma market discovery with canonical identity conversion."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from config import settings
from domain.market import MarketIdentity, MarketIdentityError

log = logging.getLogger(__name__)


class GammaAdapter:
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or settings.polymarket_gamma_url).rstrip("/")

    @staticmethod
    def is_trade_ready(market: dict[str, Any]) -> bool:
        """Require explicit current Gamma flags before enabling paper execution."""
        return (
            market.get("active") is True
            and market.get("closed") is False
            and market.get("acceptingOrders") is True
            and market.get("enableOrderBook") is True
        )

    async def fetch_active_markets(self, *, limit: int = 500) -> list[MarketIdentity]:
        """Fetch active trade-ready markets and reject identities that cannot be proven."""
        params = {"active": "true", "closed": "false", "limit": str(limit)}
        timeout = aiohttp.ClientTimeout(total=20)
        async with (
            aiohttp.ClientSession(timeout=timeout) as session,
            session.get(f"{self.base_url}/markets", params=params) as response,
        ):
            response.raise_for_status()
            payload: Any = await response.json()

        markets = payload if isinstance(payload, list) else payload.get("markets", [])
        identities: list[MarketIdentity] = []
        for market in markets:
            if not isinstance(market, dict) or not self.is_trade_ready(market):
                continue
            event_id = ""
            events = market.get("events")
            if isinstance(events, list) and events and isinstance(events[0], dict):
                event_id = str(events[0].get("id") or "")
            try:
                identities.append(MarketIdentity.from_gamma(market, event_id=event_id))
            except MarketIdentityError as exc:
                log.debug("Skipping Gamma market with incomplete identity: %s", exc)
        return identities
